from typing import Sequence
from pathlib import Path
import json
import pickle
from threading import Thread, Lock
from statistics import multimode

from icecream import ic
import numpy as np
from sklearn.preprocessing import LabelEncoder
from sklearn.cluster import KMeans
from sklearn.metrics import pairwise_distances_argmin_min as dist_argmin

from .active import ClassificationModel
from .models import DummyClassificationModel
from .models.conformal import ConformalPredictor
from .active.policies import Policy, ConformalUnsertantyPolicy
from .bandits import BanditExplorer, EpsilonGreedy, ConformalUCB, DummyBandit
from .utils import dict_to_list, SlotSet, sanitize_data
from .settings import CLASSIFICATION_MODEL, SKIP_AL, UNCERTAIN_PERC

if CLASSIFICATION_MODEL == "TfidfXGBoostClassifier":
    from .models.tfidf_sklearn import TfidfXGBoostClassifier
elif CLASSIFICATION_MODEL == "DebertaV3Wrapper":
    from .models.keras_classifiers import DebertaV3Wrapper


Labelling = str
EntryId = int | str



class ActiveLearningBackend:
    n_kickstart: int
    labels: list[str]

    subsample_size: list[int]
    # [N, n, k] entries to cache based policy
    # N entries to be ranked, embeeded or predicted (optional)
    # n entries to be clustered, this is also our cache size
    # k cluster to select best entries
    # N > n > k
    _original_dataset: dict[EntryId, str]
    _unlabelled_dataset: SlotSet[EntryId]
    _train_dataset: dict[EntryId, tuple[str, int]]
    _val_dataset: dict[EntryId, tuple[str, int]]
    # ([entry, labelling, user_id, timestamp], is_validation, true_labelling)
    _dataset: dict[EntryId, tuple[list[tuple[str, int, int, float]], bool, int]]
    _cached_subsample: list[EntryId]
    _given_nexts: list[EntryId]

    _label_encoder: LabelEncoder
    _bandit_explorer: BanditExplorer
    _policy: Policy
    _model: ClassificationModel
    _rng: np.random.Generator

    _training: bool
    _retrain: bool
    _data_lock: Lock
    _cache_lock: Lock
    _validate: bool

    def __init__(
        self,
        original_dataset: dict[EntryId, str],
        labels: list[str],
        *,
        # model_factory: Callable[[], ClassificationModel],
        policy: Policy = ConformalUnsertantyPolicy(),
        initial_labelled_dataset: dict[EntryId, Labelling] | None = None,
        n_kickstart: int = 10,
        subsample_size: list[int] = [5_000, 1_000, 20],
        unbiased_evaluation: bool = False,
        entry_ids_to_remove: set[EntryId] | None = None,
        precomputed_original_dataset_keys: SlotSet[EntryId] | None = None,
        rng: np.random.Generator,
        save_path: Path | str | None = None,
    ):
        if not (isinstance(n_kickstart, int) and n_kickstart >= 1):
            raise TypeError("`n_kickstart` must be an `int` >= 1")

        self.messages = []
        self.msg_lock = Lock()
        self.metrics_strs = []
        self.save_path = save_path

        self.n_kickstart = n_kickstart
        self.subsample_size = subsample_size
        self.unbiased_evaluation = unbiased_evaluation

        self._original_dataset = original_dataset
        self._dataset = {}

        self.labels = labels
        self._label_encoder = LabelEncoder()
        self._label_encoder.fit(labels)

        if precomputed_original_dataset_keys is None:
            self._unlabelled_dataset = SlotSet(original_dataset.keys())
        else:
            self._unlabelled_dataset = precomputed_original_dataset_keys.shallow_copy()
        if entry_ids_to_remove is not None:
            for entry_id in entry_ids_to_remove:
                self._unlabelled_dataset.remove(entry_id)
        if initial_labelled_dataset is not None:
            for entry_id, label in initial_labelled_dataset.items():
                # TODO: Keep track of it
                self._dataset[entry_id] = ([(original_dataset[entry_id], self._encode(
                    label
                ), -1, -1)], False, self._encode(label))
                self._unlabelled_dataset.remove(entry_id)

        self._rng = rng

        # Start cache ranromly while we dont have a trained model
        cached_subsample_is = self._rng.choice(
            np.arange(len(self._unlabelled_dataset)),
            min(self.subsample_size[-2], len(self._unlabelled_dataset)),
            replace=False,
        )
        self._cached_subsample = [
            self._unlabelled_dataset[i] for i in cached_subsample_is
        ]
        self._given_nexts = []
        self._validate = False

        # self._bandit_explorer = EpsilonGreedy(n_levers=2, epsilon=0.1, rng=self._rng)
        # self._bandit_explorer = ConformalUCB(
        #     n_levers=2, reward_upper_bound=1, rng=self._rng
        # )
        self._bandit_explorer = DummyBandit(
            n_levers=len(labels), prob_levers=[0.8, 0.2], rng=self._rng
        )
        self._policy = policy

        self._data_lock = Lock()
        self._cache_lock = Lock()
        self._model = DummyClassificationModel(n_classes=len(self.labels))

        # If we have enought entries we start training
        self._training = False
        self._retrain = False
        self._count_since_last_train = 0
        self._check_training()

    def _encode(self, labelling: Labelling | list[Labelling]) -> int | list[int]:
        if isinstance(labelling, Labelling):
            return self._label_encoder.transform([labelling])[0]
        else:
            return self._label_encoder.transform(labelling)

    def _cache_whether_to_validate(self):
        self._validate = self._bandit_explorer.select_lever() == 1

    def _check_training(self):
        with self._data_lock:
            if (
                self._count_since_last_train >= 5
                or len(self._train_dataset) + len(self._val_dataset) == 100
            ):
                if (
                    len(self._train_dataset) + len(self._val_dataset) >= self.n_kickstart
                    and not self._training
                ):
                    self._training = True
                    Thread(target=self._train).start()
                else:
                    self._retrain = True

    def _train(self):
        self.message("Starting training.")
        # Load data
        with self._data_lock:
            unlabelled_ids = np.array(self._unlabelled_dataset)
            unlabelled = [
                self._original_dataset[entry_id] for entry_id in unlabelled_ids
            ]
            unlabelled_dict = {
                entry_id: self._original_dataset[entry_id]
                for entry_id in unlabelled_ids
            }
            labelled = [
                (entry, labelling) for entry, labelling in self._train_dataset.values()
            ]
            validation = [
                (entry, labelling) for entry, labelling in self._val_dataset.values()
            ]
            rng = np.random.default_rng(seed=self._rng.integers(np.iinfo(int).max))
            # del self._model
            # self._model = DummyClassificationModel(n_classes=len(self.labels))
            with self._cache_lock:
                self._count_since_last_train = 0

        # Train new model
        if CLASSIFICATION_MODEL == "TfidfXGBoostClassifier":
            class_model = TfidfXGBoostClassifier(n_classes=len(self.labels))
        elif CLASSIFICATION_MODEL == "DebertaV3Wrapper":
            class_model = DebertaV3Wrapper(
                n_classes=len(self.labels),
                model="deberta_v3_base_en",
                verbose=0,
            )
        model = ConformalPredictor(
            model=class_model,
            alpha=0.1,
            n_classes=len(self.labels),
        )
        self.message("Instanced model")
        model.train(labelled, validation)  # , epochs=3)
        self.message("Done training")

        if not SKIP_AL:
            if len(self.subsample_size) == 3:
                ids = rng.integers(len(unlabelled), size=(self.subsample_size[-3]))
                candidates_ids = unlabelled_ids[ids]
                candidates_txt = [unlabelled[i] for i in ids]
            else:
                candidates_ids = unlabelled_ids
                candidates_txt = unlabelled

            # Get k most uncertain
            sorted_ids = candidates_ids[self._policy.rank(candidates_txt, model)][
                : int(self.subsample_size[-2])
            ]
            sorted_ids = np.concatenate(
                (
                    sorted_ids[: int(self.subsample_size[-2] * UNCERTAIN_PERC)],
                    sorted_ids[-int(self.subsample_size[-2] * (1 - UNCERTAIN_PERC)) :],
                )
            )
            ic("Done hanking")

            # Cluster in n, and get cosest to each centroid to be highest priority on cache
            to_cluster = [unlabelled_dict[entry_id] for entry_id in sorted_ids]
            to_cluster_emb = model.get_embeddings(to_cluster)
            kmean = KMeans(self.subsample_size[-1], n_init="auto").fit(to_cluster_emb)

            best_ids = np.unique(
                np.array(
                    [
                        sorted_ids[i]
                        for i in dist_argmin(kmean.cluster_centers_, to_cluster_emb)[0]
                    ]
                )
            )
            other_ids = sorted_ids[~np.isin(sorted_ids, best_ids)]
            rng.shuffle(best_ids)
            rng.shuffle(other_ids)

            new_cache = np.concatenate((best_ids, other_ids))
            if type(list(self._original_dataset)[0]) is int:
                new_cache = (
                    new_cache[np.isin(new_cache, self._unlabelled_dataset.array)]
                    .astype(int)
                    .tolist()
                )
            else:
                new_cache = new_cache[
                    np.isin(new_cache, self._unlabelled_dataset.array)
                ].tolist()

        # Store data and do flow control
        with self._cache_lock:
            with self._data_lock:
                if not SKIP_AL:
                    self._previous_cache_top = self._cached_subsample[0]
                    self._cached_subsample = new_cache
                self._model = model
                retrain = self._retrain
                self._retrain = False
                if not retrain:
                    self._training = False

        self.metrics_strs = ["Last trained model:"]
        self.metrics_strs.append(f"n labeled: {len(labelled) + len(validation)}")
        self.metrics_strs.append(f"split train/val: {len(labelled)}/{len(validation)}")
        l, h = self.peek_auc_roc_ovr(alpha=0.1)
        self.metrics_strs.append(f"AUC_ROC: ${(l+h)/2:.2f} \pm {(h-l)/2:.2f}$")
        l, h = self.peek_accuracy(alpha=0.1)
        self.metrics_strs.append(f"Accuracy: ${(l+h)/2:.2f} \pm {(h-l)/2:.2f}$")
        if len(self.labels) == 2:
            l, h = self.peek_precision(target=self.labels[1], alpha=0.1)
            self.metrics_strs.append(f"Precision: ${(l+h)/2:.2f} \pm {(h-l)/2:.2f}$")
            l, h = self.peek_recall(target=self.labels[1], alpha=0.1)
            self.metrics_strs.append(f"Recall: ${(l+h)/2:.2f} \pm {(h-l)/2:.2f}$")
        else:
            for lb in self.labels:
                l, h = self.peek_precision(target=lb, alpha=0.1)
                self.metrics_strs.append(
                    f"Precision ({lb}): ${(l+h)/2:.2f} \pm {(h-l)/2:.2f}$"
                )
                l, h = self.peek_recall(target=lb, alpha=0.1)
                self.metrics_strs.append(
                    f"Recall ({lb}): ${(l+h)/2:.2f} \pm {(h-l)/2:.2f}$"
                )

        for m in self.metrics_strs:
            self.message(m)

        if self.save_path is not None:
            self.save(self.save_path)
            self.message("Saved Learner")

        if retrain:
            self._train()

    def _is_labeled(self, entry_id: EntryId) -> bool:
        with self._data_lock:
            return (entry_id in self._train_dataset) or (entry_id in self._val_dataset)

    def request_next_entry(self) -> EntryId:
        # Should not mutate ANYTHING in self (including `rng`)!
        with self._cache_lock:
            next_id = self._cached_subsample[0]
            if next_id in self._train_dataset or next_id in self._val_dataset:
                self._cached_subsample = self._cached_subsample[1:]
                skip = True
            else:
                self._given_nexts.append(next_id)
                skip = False
        if skip:
            return self.request_next_entry()
        else:
            return next_id

    @property
    def _train_dataset(self) -> dict[EntryId, tuple[str, int]]:
        # TODO: Verify trustness from _dataset
        
        train_dataset = {}
        for label_id in self._dataset:
            if self._dataset[label_id][1] == False and self._dataset[label_id][2] != -1:
                train_dataset[label_id] = self._dataset[label_id][2]
        
        return train_dataset
        
    @property
    def _val_dataset(self) -> dict[EntryId, tuple[str, int]]:
        # TODO: Verify trustness from _dataset
        
        val_dataset = {}
        for label_id in self._dataset:
            if self._dataset[label_id][1] == True and self._dataset[label_id][2] != -1:
                val_dataset[label_id] = self._dataset[label_id][2]
        
        return val_dataset
    
    def message(self, msg):
        ic(msg)
        with self.msg_lock:
            self.messages.append(msg)

    def update_trustness(self, entry_id: EntryId) -> None:
        # Updates trustness following data structures.
        labellings = [labelling for labelling, *rest in enumerate(self._dataset[entry_id][0])]
        modes = multimode(labellings)
        if len(modes) == 1:
            # We have a single mode, we can trust this entry
            self._dataset[entry_id][2] = modes[0]
        else:
            # We have multiple modes, we cannot trust this entry
            self._dataset[entry_id][2] = -1
            
        
    
    # TODO: Verify if adding timestamp and user breaks this.
    def sync_labelling(self, labelled_data: dict[EntryId, Labelling]) -> None:
        
        ic(labelled_data)
        with self._data_lock:
            for entry_id, labelling in labelled_data.items():
                # We add everything new to self._train_dataset because manualy labelled data can be biased.
                # Verify if entry in
                # false is_validate
                if not (entry_id in self._dataset):
                    self._dataset[entry_id] = (
                        [(self._original_dataset[entry_id],
                        self._encode(labelling),
                        -1,  # user_id
                        -1),  # timestamp
                        ],
                        False,
                        self._encode(labelling),
                    )
                    self._unlabelled_dataset.remove(entry_id)
                    self._count_since_last_train += 1
        self._check_training()

        # FIXME, Recalculate bandit rewards?!?!?!?!

    def submit_labelling(self, entry_id: EntryId, labelling: Labelling,
                         user_id: int, timestamp: float) -> None:
        if not isinstance(labelling, Labelling):
            raise TypeError("`labelling` must be a `Labelling`")

        assert entry_id in self._given_nexts, "submitted an unexpected label"
        inf_auc_before, _ = self.peek_auc_roc_ovr(alpha=0.1)

        with self._data_lock:
            # TODO: Test this.
            if entry_id not in self._dataset:
                self._dataset[entry_id] = (
                    [(self._original_dataset[entry_id],
                    self._encode(labelling),
                    user_id,
                    timestamp),],
                    self._validate,
                    self._encode(labelling),
                )
            else:
                self._train_dataset[entry_id][0].append(
                    (self._original_dataset[entry_id],
                    self._encode(labelling),
                    user_id,
                    timestamp,)
                )
                self.update_trustness(entry_id)

            if entry_id in self._unlabelled_dataset:
                self.message(f"removing from unlabeled: {entry_id}")
                self._unlabelled_dataset.remove(entry_id)

        self.message(
            f"dataset: {len(self._train_dataset)}, validation: {len(self._val_dataset)}"
        )

        # FIXME: this auc_roc will not change between training sessions, this might break the bandit
        inf_auc_after, _ = self.peek_auc_roc_ovr(alpha=0.1)
        reward = inf_auc_after - inf_auc_before
        with self._data_lock:
            self._bandit_explorer.inform(
                {True: 1, False: 0}[self._validate], reward
            )  # dict lookup so that we get an error if an unexpected value shows up (e.g. because we've changed the number of levers)
            self._policy.inform(reward)

        # Update cached_subsample and validate
        with self._cache_lock:
            assert len(self._cached_subsample) >= 1  # FIXME: Beter treatment for this
            self._cached_subsample = self._cached_subsample[1:]
            self._count_since_last_train += 1
        self._cache_whether_to_validate()

        self._check_training()

    def peek_predictions(self, *, alpha: float):
        with self._data_lock:
            model = self._model
            unlabeled_data = self._unlabelled_dataset
        if len(self.subsample_size) == 3:
            ids = self._rng.integers(
                len(unlabeled_data), size=(self.subsample_size[-3])
            )
            unlabeled_data = [self._original_dataset[unlabeled_data[i]] for i in ids]
        preds = model.predict(unlabeled_data)
        return np.mean([len(pred) in [0, 1] for pred in preds])

    def peek_accuracy(
        self, *, alpha: float
    ) -> tuple[float, float]:  # returns a confidence interval
        # FIXME proper implementation accounting for covariate shift and producing and proper sequential inference
        with self._data_lock:
            val_dataset = self._val_dataset
            model = self._model
        n = len(val_dataset)
        k = sum(
            [
                model.predict_proba([text])[0][label]
                == max(model.predict_proba([text])[0].values())
                for text, label in val_dataset.values()
            ]
        )
        return k / (n + 1), (k + 1) / (n + 1)

    def peek_precision(
        self, *, target: Labelling, alpha: float
    ) -> tuple[float, float]:  # returns a confidence interval
        # FIXME proper implementation accounting for covariate shift and producing and proper sequential inference
        with self._data_lock:
            val_dataset = self._val_dataset
            model = self._model
        samples = [
            label == self._encode(target)
            for text, label in val_dataset.values()
            if model.predict_proba([text])[0][self._encode(target)]
            == max(model.predict_proba([text])[0].values())
        ]
        k = sum(samples)
        n = len(samples)
        return k / (n + 1), (k + 1) / (n + 1)

    def peek_recall(
        self, *, target: Labelling, alpha: float
    ) -> tuple[float, float]:  # returns a confidence interval
        # FIXME proper implementation accounting for covariate shift and producing and proper sequential inference
        with self._data_lock:
            val_dataset = self._val_dataset
            model = self._model
        samples = [
            model.predict_proba([text])[0][self._encode(target)]
            == max(model.predict_proba([text])[0].values())
            for text, label in val_dataset.values()
            if label == self._encode(target)
        ]
        k = sum(samples)
        n = len(samples)
        return k / (n + 1), (k + 1) / (n + 1)

    def peek_auc_roc_single(
        self, *, target: Labelling, alpha: float
    ) -> tuple[float, float]:  # returns a confidence interval
        with self._data_lock:
            val_dataset = self._val_dataset
            model = self._model
        samples_y1 = [
            text
            for text, label in val_dataset.values()
            if label == self._encode(target)
        ]
        samples_y0 = [
            text
            for text, label in val_dataset.values()
            if label != self._encode(target)
        ]
        if len(samples_y1) == 0 or len(samples_y0) == 0:
            return 0, 1

        preds_y1 = model.predict_proba(samples_y1)
        preds_y0 = model.predict_proba(samples_y0)

        pair_samples = [
            (
                1
                if pred0[self._encode(target)] < pred1[self._encode(target)]
                else (
                    0
                    if pred0[self._encode(target)] > pred1[self._encode(target)]
                    else 0.5
                )
            )
            for pred1, pred0 in zip(
                preds_y1, preds_y0
            )  # NOTE: zip instead of product because we need independent samples to produce a confidence interval from
        ]

        # rng = np.random.default_rng(0)
        # MAX_N = 30**2
        # if len(pair_samples) >= MAX_N:
        #     subsample = rng.choice(np.arange(len(pair_samples)), replace=False, size=MAX_N)
        #     pair_samples = [pair_samples[i] for i in subsample]

        k = sum(pair_samples)
        n = len(pair_samples)
        return k / (n + 1), (k + 1) / (n + 1)

    def peek_auc_roc_ovr(
        self, *, alpha: float
    ) -> tuple[float, float]:  # returns a confidence interval
        infs = []
        sups = []
        for l in self.labels:
            inf_l, sup_l = self.peek_auc_roc_single(target=l, alpha=alpha)
            infs.append(inf_l)
            sups.append(sup_l)

        return np.mean(infs), np.mean(sups)

    def make_predictions(
        self, texts: Sequence[str]
    ) -> list[tuple[str, tuple[dict[Labelling, float], Labelling]]]:
        with self._data_lock:
            texts = list(texts)
            probass = self._model.predict_proba(texts)
            point_preds = self._model.predict(texts)

        return [
            (
                text,
                (
                    {Labelling(y): float(p) for y, p in probas.items()},
                    Labelling(point_pred),
                ),
            )
            for text, probas, point_pred in zip(texts, probass, point_preds)
        ]

    def export_preditictions(
        self,
        entry_ids: list[EntryId] | None = None,
        alpha: float = 0.95,
    ) -> dict[EntryId, list[Labelling]]:
        if isinstance(self._model, DummyClassificationModel):
            raise ValueError("Trained model not available, please add more labels to trigger a model training.")
        with self._data_lock:
            unlabelled_ids = entry_ids or np.array(self._unlabelled_dataset)
            unlabelled = [
                self._original_dataset[entry_id] for entry_id in unlabelled_ids
            ]
            labelled = [
                (entry, labelling) for entry, labelling in self._train_dataset.values()
            ]
            validation = [
                (entry, labelling) for entry, labelling in self._val_dataset.values()
            ]
        self._model.train(labelled, validation, skip_model_train=True, alpha=alpha)

        return {
            entry_id: [self.labels[p] for p in pred]
            for entry_id, pred in zip(unlabelled_ids, self._model.predict(unlabelled))
        }

    def save(self, path: str | Path) -> None:
        path = Path(path)
        if not path.is_dir():
            path.mkdir()
        with self._data_lock:
            with open(path / "fields.json", "w") as file:
                json.dump(
                    sanitize_data(
                        {
                            "messages": self.messages,
                            "n_kickstart": self.n_kickstart,
                            "subsample_size": self.subsample_size,
                            "unbiased_evaluation": self.unbiased_evaluation,
                            "_dataset": self._dataset,
                            "labels": self.labels,
                            "_cached_subsample": self._cached_subsample,
                            "_validate": bool(self._validate),
                            "_given_nexts": self._given_nexts,
                        }
                    ),
                    file,
                )

            with open(path / "bandit_explorer.pickle", "wb") as file:
                pickle.dump(self._bandit_explorer, file)
            with open(path / "label_encoder.pickle", "wb") as file:
                pickle.dump(self._label_encoder, file)
            with open(path / "policy.pickle", "wb") as file:
                pickle.dump(self._policy, file)
            with open(path / "model.pickle", "wb") as file:
                pickle.dump(self._model, file)

    @classmethod
    def load(
        cls,
        path: str | Path,
        original_dataset: dict[EntryId, str],
        *,
        precomputed_original_dataset_keys: SlotSet[EntryId] | None = None,
        rng: np.random.Generator,
    ):
        path = Path(path)

        with open(path / "fields.json") as file:
            data = json.load(file)
        with open(path / "policy.pickle", "rb") as file:
            policy = pickle.load(file)

        if type(list(original_dataset.keys())[0]) is int:
            data["_dataset"] = {int(k): v for k, v in data["_dataset"].items()}

        out = cls(
            original_dataset,
            labels=data["labels"],
            policy=policy,
            n_kickstart=data["n_kickstart"],
            subsample_size=data["subsample_size"],
            unbiased_evaluation=data["unbiased_evaluation"],
            entry_ids_to_remove=set(data["_dataset"].keys()),
            precomputed_original_dataset_keys=precomputed_original_dataset_keys,
            rng=rng,
        )

        out._dataset = data["_dataset"]
        out._unlabelled_dataset = SlotSet(
            [
                entry_id
                for entry_id in original_dataset.keys()
                if entry_id not in out._dataset
            ]
        )
        out.messages = data["messages"]
        out._given_nexts = data["_given_nexts"]
        out._cached_subsample = data["_cached_subsample"]
        out._validate = data["_validate"]

        with open(path / "label_encoder.pickle", "rb") as file:
            out._label_encoder = pickle.load(file)
        with open(path / "bandit_explorer.pickle", "rb") as file:
            out._bandit_explorer = pickle.load(file)
        # out._model = DummyClassificationModel(n_classes=len(data["labels"]))
        with open(path / "model.pickle", "rb") as file:
            out._model = pickle.load(file)
        ic(out._model)

        out._count_since_last_train = 5
        out._check_training()

        return out


# This is outdated

# def simulate_public_api(
#     labelled_dataset: dict[EntryId, tuple[str, Literal[2] | Literal[1] | Literal[0]]],
#     *,
#     n_rounds: int = 200,
#     show_progress: bool = True,
#     policy: Policy,
#     rng: np.random.Generator,
# ) -> list[tuple[float, float]]:
#     ALPHA = 0.1

#     unlabelled_dataset = {
#         entry_id: text for entry_id, (text, _) in labelled_dataset.items()
#     }
#     label_mapping = {
#         entry_id: {
#             2: Labelling.YES,
#             1: Labelling.DUNNO,
#             0: Labelling.NO,
#         }[label]
#         for entry_id, (_, label) in labelled_dataset.items()
#     }

#     backend = ActiveLearningBackend(unlabelled_dataset, policy=policy, rng=rng)

#     results = []
#     results.append(backend.peek_accuracy(alpha=ALPHA))
#     for i in trange(n_rounds, disable=not show_progress):
#         queried_entry_id = backend.request_next_entry()
#         backend.submit_labelling(queried_entry_id, label_mapping[queried_entry_id])
#         results.append(backend.peek_accuracy(alpha=ALPHA))

#     return results
