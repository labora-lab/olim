from typing import Literal, Union
import os
import shutil
from contextlib import asynccontextmanager
from pathlib import Path
import json
import uuid
from threading import Lock

from fastapi import FastAPI, Body
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import numpy as np

from data import unlabelled_floripa_dataset
from public_api import EntryId, ActiveLearningBackend, Labelling, SlotSet
from active.policies import EntropyPolicy, KeywordPolicyCombinator
from bandits import ConformalUCB

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

rng = np.random.default_rng(0)  # XXX remove fixed seed?

unlabelled_dataset: dict[EntryId, str] = unlabelled_floripa_dataset()
precomputed_unlabelled_dataset_keys: SlotSet[EntryId] = SlotSet(
    unlabelled_dataset.keys()
)

SERVER_STATE_DIR = Path("server-state")
if not os.path.isdir(SERVER_STATE_DIR):
    os.makedirs(SERVER_STATE_DIR)
if not os.path.isdir(SERVER_STATE_DIR / "concepts"):
    os.mkdir(SERVER_STATE_DIR / "concepts")
if not os.path.isfile(SERVER_STATE_DIR / "concepts" / "mapping.json"):
    with open(SERVER_STATE_DIR / "concepts" / "mapping.json", "w") as file:
        json.dump({}, file)

master_lock = Lock()
locks: dict[str, Lock] = {}


@asynccontextmanager
async def active_learning_backend(concept: str) -> ActiveLearningBackend:
    with master_lock:
        if concept not in locks:
            locks[concept] = Lock()
        locks[concept].acquire(timeout=10)

    try:
        with open(SERVER_STATE_DIR / "concepts" / "mapping.json") as file:
            mapping = json.load(file)
        concept_state_path = SERVER_STATE_DIR / "concepts" / mapping[concept]
        concept_state_path_tmp = (
            SERVER_STATE_DIR / "concepts" / (mapping[concept] + ".tmp")
        )

        os.rename(concept_state_path, concept_state_path_tmp)
        backend = ActiveLearningBackend.load(
            concept_state_path_tmp,
            unlabelled_dataset,
            precomputed_original_dataset_keys=precomputed_unlabelled_dataset_keys,
            rng=rng,
        )
        yield backend
        backend.save(concept_state_path)

        shutil.rmtree(concept_state_path_tmp)
    finally:
        with master_lock:
            locks[concept].release()


class NewConceptUnguided(BaseModel):
    method: Literal["unguided"]


class NewConceptKeywordGuided(BaseModel):
    method: Literal["keyword-guided"]
    keywords: list[str]


@app.post("/api/v0/new_concept")
def new_concept(
    name: str,
    *,
    n_kickstart: int = 10,
    body: Union[
        NewConceptUnguided,
        NewConceptKeywordGuided,
    ] = Body(..., discriminator="method"),
):
    with master_lock:
        if name not in locks:
            locks[name] = Lock()
        locks[name].acquire(timeout=10)

    try:
        with open(SERVER_STATE_DIR / "concepts" / "mapping.json") as file:
            mapping = json.load(file)
        assert name not in mapping
        id = str(uuid.uuid4())

        match body.method:
            case "unguided":
                policy = EntropyPolicy()
            case "keyword-guided":
                policy = KeywordPolicyCombinator(
                    subpolicy=EntropyPolicy(),
                    bandit_explorer=ConformalUCB(
                        n_levers=2, reward_upper_bound=1, rng=np.random.default_rng(0)
                    ),  # FIXME RNG
                    keywords=body.keywords,
                )
        backend = ActiveLearningBackend(
            unlabelled_dataset,
            policy=policy,
            n_kickstart=n_kickstart,
            precomputed_original_dataset_keys=precomputed_unlabelled_dataset_keys,
            rng=rng,
        )

        backend.save(SERVER_STATE_DIR / "concepts" / id)
        mapping[name] = id
        with open(SERVER_STATE_DIR / "concepts" / "mapping.json.tmp", "w") as file:
            json.dump(mapping, file)
        os.rename(
            SERVER_STATE_DIR / "concepts" / "mapping.json.tmp",
            SERVER_STATE_DIR / "concepts" / "mapping.json",
        )
    finally:
        with master_lock:
            locks[name].release()

    return {}


@app.get("/api/v0/list_concepts")
def list_concepts():
    with master_lock:
        with open(SERVER_STATE_DIR / "concepts" / "mapping.json") as file:
            mapping = json.load(file)
        out = {}
        for concept_name, concept_id in mapping.items():
            out[concept_name] = {
                "id": concept_id,
            }
    return out


@app.get("/api/v0/request_next_entry")
async def request_next_entry(concept: str):
    async with active_learning_backend(concept) as backend:
        entry_id = backend.request_next_entry()
        return {
            "entry_id": entry_id,
            "text": unlabelled_dataset[entry_id],
        }


@app.get("/api/v0/submit_labelling")
async def submit_labelling(
    concept: str,
    entry_id: EntryId,
    labelling: Literal["yes"] | Literal["no"] | Literal["dunno"],
):
    async with active_learning_backend(concept) as backend:
        backend.submit_labelling(
            entry_id,
            {
                "yes": Labelling.YES,
                "no": Labelling.NO,
                "dunno": Labelling.DUNNO,
            }[labelling],
        )
        return {}


@app.get("/api/v0/peek_evaluation")
async def peek_evaluation(concept: str, *, alpha: float = 0.1):
    assert 0 < alpha < 1
    async with active_learning_backend(concept) as backend:
        return {
            "accuracy": backend.peek_accuracy(alpha=alpha),
            "precision_yes": backend.peek_precision(target=Labelling.YES, alpha=alpha),
            "precision_no": backend.peek_precision(target=Labelling.NO, alpha=alpha),
            "precision_dunno": backend.peek_precision(
                target=Labelling.DUNNO, alpha=alpha
            ),
            "recall_yes": backend.peek_recall(target=Labelling.YES, alpha=alpha),
            "recall_no": backend.peek_recall(target=Labelling.NO, alpha=alpha),
            "recall_dunno": backend.peek_recall(target=Labelling.DUNNO, alpha=alpha),
            "auc_yes": backend.peek_auc_roc_single(target=Labelling.YES, alpha=alpha),
            "auc_no": backend.peek_auc_roc_single(target=Labelling.NO, alpha=alpha),
            "auc_dunno": backend.peek_auc_roc_single(
                target=Labelling.DUNNO, alpha=alpha
            ),
            "auc_ovr": backend.peek_auc_roc_ovr(alpha=alpha),
        }


@app.get("/api/v0/make_predictions")
async def make_predictions(concept: str):
    async with active_learning_backend(concept) as backend:
        preds = backend.make_predictions(unlabelled_dataset.values())

    translation = {
        Labelling.YES: "yes",
        Labelling.NO: "no",
        Labelling.DUNNO: "dunno",
    }

    return [
        (
            text,
            (
                {translation[y]: prob for y, prob in probs.items()},
                translation[point_pred],
            ),
        )
        for text, (probs, point_pred) in preds
    ]
