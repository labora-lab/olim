"""Offline active learning harness for comparing against arXiv:2502.04372.

Runs OLIM's real components — `_balanced_split`, `ConformalPredictor`,
`_assemble_pool`, `_select_from_pool`, `_compute_metrics` — against the Amazon
reviews corpus, with a deterministic oracle standing in for the human annotator.
Only the database paging loop of `_rank_entries_batched` is replaced, since that
is the one part that needs Postgres and Elasticsearch.

## Reading the numbers

The paper's four labels (Pet product, Drinkable, Low quality, Damaged) were
labelled by hand; those labels are not published, so absolute accuracy is **not**
directly comparable. What is comparable is the *structure* of the results:
mixed-vs-high-only uncertainty, active-vs-random selection, and how many positives
each finds. Those are the claims the tests assert.

Three oracles are keyword-defined. Left as-is, a TF-IDF model recovers them almost
perfectly (AUC ~0.95+) and every configuration saturates, which would make the
comparison meaningless — so the trigger words are **stripped from the text the
model sees**. The label still exists, but it has to be inferred from context, which
lands the difficulty at AUC 0.65-0.76, the paper's range. `low_quality` needs no
such treatment: it comes from the star rating, not from words in the review.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from olim.ml.classifiers.conformal import ConformalPredictor
from olim.ml.orchestrator import AVAILABLE_MODELS, TrainingOrchestrator

REVIEWS_CSV = Path(__file__).resolve().parents[2] / "Reviews.csv"

#: Keyword oracles approximating the paper's labels. The pattern both defines the
#: ground truth and is removed from the model's input (see the module docstring).
KEYWORD_ORACLES = {
    "pet_product": r"\b(?:dog|cat|puppy|kitten|pet|feline|canine|kibble|paw)s?\b",
    "drinkable": r"\b(?:coffee|tea|drink|beverage|juice|soda|latte|espresso|brew|cocoa)s?\b",
    "damaged": (
        r"\b(?:broken|damaged|melted|crushed|leaked|leaking|smashed|spoiled"
        r"|stale|expired|mold|moldy|dented|torn)\b"
    ),
}
LABELS = (*KEYWORD_ORACLES, "low_quality")


@dataclass
class Corpus:
    """Texts the model sees, plus ground truth per label."""

    texts: np.ndarray
    labels: dict[str, np.ndarray]

    def prevalence(self, label: str) -> float:
        return float(self.labels[label].mean())


def load_corpus(n_rows: int = 60_000, csv: Path | None = None) -> Corpus:
    frame = pd.read_csv(csv or REVIEWS_CSV, usecols=["Score", "Summary", "Text"], nrows=n_rows)
    raw = (frame.Summary.fillna("") + " " + frame.Text.fillna("")).str.lower().to_numpy()

    labels = {"low_quality": (frame.Score <= 2).to_numpy().astype(int)}
    masked = list(raw)
    for name, pattern in KEYWORD_ORACLES.items():
        labels[name] = np.array([1 if re.search(pattern, t) else 0 for t in raw])
        masked = [re.sub(pattern, " ", t) for t in masked]
    return Corpus(texts=np.array(masked, dtype=object), labels=labels)


@dataclass
class RunResult:
    label: str
    strategy: str
    certain_rate: float
    n_labels: int
    accuracy: float
    auc_roc: float
    positives: int
    history: list[dict] = field(default_factory=list)

    @property
    def yes_no(self) -> str:
        return f"{self.positives}/{self.n_labels - self.positives}"


def _train(train_items, val_items, fit_corpus, algorithm, alpha=0.1):
    inner = AVAILABLE_MODELS[algorithm](n_classes=2, balance_classes=True)
    conformal = ConformalPredictor(model=inner, alpha=alpha, n_classes=2)
    conformal.train(train_items, val_items, fit_corpus=fit_corpus)
    return conformal


def _held_out_scores(conformal, corpus, label, test_idx):
    from sklearn.metrics import accuracy_score, roc_auc_score

    texts = [corpus.texts[i] for i in test_idx]
    probs = np.asarray(conformal.model.predict_proba(texts))
    truth = corpus.labels[label][test_idx]
    preds = probs.argmax(axis=1)
    auc = float("nan")
    if len(np.unique(truth)) > 1:
        auc = float(roc_auc_score(truth, probs[:, 1]))
    return float(accuracy_score(truth, preds)), auc


def run_active_learning(
    corpus: Corpus,
    label: str,
    *,
    budget: int = 200,
    seed_labels: int = 20,
    retrain_every: int = 10,
    pool_size: int = 500,
    n_clusters: int = 6,
    certain_rate: float = 0.3,
    strategy: str = "active",
    algorithm: str = "TfidfXGBoostClassifier",
    split_ratio: float = 0.8,
    seed: int = 0,
    test_size: int = 6_000,
    candidates: int = 10_000,
    fit_rows: int = 10_000,
    seed_positives: int = 0,
) -> RunResult:
    """Simulate one labelling campaign and score it on a held-out set.

    strategy="active" uses OLIM's conformal ranking; "random" draws uniformly, the
    paper's baseline. `seed_positives` mimics the paper's "started with N
    pre-labelled texts", where positives were found by keyword search.
    """
    rng = np.random.default_rng(seed)
    truth = corpus.labels[label]
    order = rng.permutation(len(corpus.texts))
    test_idx, work_idx = order[:test_size], order[test_size:]

    # Seed set: random, optionally salted with known positives as the paper does.
    seed_idx = list(work_idx[:seed_labels])
    if seed_positives:
        pos = [i for i in work_idx[seed_labels:] if truth[i] == 1][:seed_positives]
        seed_idx = list(work_idx[: max(0, seed_labels - len(pos))]) + pos
    labelled = list(dict.fromkeys(seed_idx))
    seen = set(labelled)  # hoisted: rebuilding it per element is O(n * len(labelled))
    unlabelled = [i for i in work_idx if i not in seen]

    orch = TrainingOrchestrator("/tmp")
    fit_corpus = [corpus.texts[i] for i in work_idx[:fit_rows]]
    history: list[dict] = []
    conformal = None

    while len(labelled) < budget:
        items = [(corpus.texts[i], int(truth[i])) for i in labelled]
        split = orch._balanced_split(items, split_ratio, seed=seed)
        if split is None:
            from sklearn.model_selection import train_test_split

            split = train_test_split(items, test_size=1 - split_ratio, random_state=seed)
        train_items, val_items = split
        conformal = _train(train_items, val_items, fit_corpus, algorithm)

        metrics = orch._compute_metrics(conformal, val_items, ["no", "yes"])
        acc, auc = _held_out_scores(conformal, corpus, label, test_idx)
        history.append(
            {
                "round": len(history) + 1,
                "n_labels": len(labelled),
                "positives": int(sum(truth[i] for i in labelled)),
                "val_accuracy": metrics.get("accuracy"),
                "test_accuracy": acc,
                "test_auc_roc": auc,
            }
        )

        take = min(retrain_every, budget - len(labelled))
        if strategy == "random":
            picks = list(rng.choice(unlabelled, size=take, replace=False))
        else:
            cand = unlabelled[: min(len(unlabelled), candidates)]
            scored = sorted(
                zip(cand, conformal.predict_uncert([corpus.texts[i] for i in cand]), strict=False),
                key=lambda x: x[1],
                reverse=True,
            )
            scored = [(int(i), float(s)) for i, s in scored]
            pool, low_ids = orch._assemble_pool(scored, pool_size, certain_rate)
            pool_texts = [corpus.texts[i] for i, _ in pool]
            embeddings = conformal.get_embeddings(pool_texts) if len(pool) > n_clusters else None
            picks = [
                e["id"]
                for e in orch._select_from_pool(pool, low_ids, embeddings, n_clusters, take, rng)
            ]

        picked = set(picks)
        labelled += [int(i) for i in picks]
        unlabelled = [i for i in unlabelled if i not in picked]

    items = [(corpus.texts[i], int(truth[i])) for i in labelled]
    split = orch._balanced_split(items, split_ratio, seed=seed)
    if split is None:
        from sklearn.model_selection import train_test_split

        split = train_test_split(items, test_size=1 - split_ratio, random_state=seed)
    conformal = _train(split[0], split[1], fit_corpus, algorithm)
    acc, auc = _held_out_scores(conformal, corpus, label, test_idx)

    return RunResult(
        label=label,
        strategy=strategy,
        certain_rate=certain_rate,
        n_labels=len(labelled),
        accuracy=acc,
        auc_roc=auc,
        positives=int(sum(truth[i] for i in labelled)),
        history=history,
    )


def repeat(n_seeds: int = 3, **kwargs: Any) -> list[RunResult]:
    return [run_active_learning(seed=s, **kwargs) for s in range(n_seeds)]


def summarise(runs: list[RunResult]) -> dict[str, Any]:
    acc = np.array([r.accuracy for r in runs])
    auc = np.array([r.auc_roc for r in runs])
    pos = np.array([r.positives for r in runs])
    return {
        "accuracy": (float(acc.mean()), float(acc.std())),
        "auc_roc": (float(np.nanmean(auc)), float(np.nanstd(auc))),
        "positives": (float(pos.mean()), float(pos.std())),
        "n_labels": runs[0].n_labels,
    }
