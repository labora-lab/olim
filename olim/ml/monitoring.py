"""Model health checks for maintenance active learning.

A model that trained well months ago says nothing about whether it is still right on
the data arriving now. These are the three questions the maintenance task asks, in
increasing order of evidential weight:

1. **New confident predictions nobody has checked** — how much the model has committed
   to without adjudication. Cheap, but only a measure of exposure, not of error.
2. **Confidence drop** — re-score the current pool and compare conformal `coverage`
   against its value at training time. Needs no new labels; catches shifted data.
3. **Measured agreement** — where a human labelled an entry *after* the model had
   already predicted it, compare the two. The only direct evidence, and the reason the
   task asks for a small audit sample.

(3) is sound and leak-free because `TrainingOrchestrator._store_full_predictions` only
writes prediction rows for entries that were unlabeled when the version trained, so
any human label on one of them necessarily postdates the model's guess.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from olim import db
from olim.database import Entry, LabelEntry, ModelPrediction
from olim.label_types import parse_label_value

#: Signals a maintenance run can rank models by.
RANK_SIGNALS = ("audit_accuracy", "coverage_drop", "unchecked_predictions")

#: Below this many adjudicated entries an accuracy figure is noise, not evidence —
#: the same guard the active learning stopping rule applies to its own metrics.
DEFAULT_MIN_AUDIT_SAMPLES = 10


@dataclass
class ModelHealth:
    """One model's health, as far as the available evidence allows."""

    model_id: int
    model_name: str
    label_id: int | None
    label_name: str
    version_id: int | None = None
    version_number: int | None = None
    trained_at: str | None = None

    n_checked: int = 0
    n_agree: int = 0
    audit_accuracy: float | None = None
    per_class: dict[str, dict[str, Any]] = field(default_factory=dict)

    coverage_at_training: float | None = None
    coverage_now: float | None = None
    coverage_drop: float | None = None

    unchecked_predictions: int = 0
    reasons: list[str] = field(default_factory=list)

    def is_degraded(self, accuracy_threshold: float, coverage_drop_threshold: float) -> bool:
        """Whether any signal with enough evidence behind it says this model is unwell."""
        if self.audit_accuracy is not None and self.audit_accuracy < accuracy_threshold:
            return True
        return self.coverage_drop is not None and self.coverage_drop > coverage_drop_threshold

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if not k.startswith("_")}


def prediction_agreement(
    label_id: int, version_id: int, trained_at: datetime | None = None
) -> dict[str, Any]:
    """Compare what the model predicted against what a human decided afterwards.

    Only counts entries labelled after `trained_at`; a label that predates the version
    was part of its training data, not a verdict on it.
    """
    query = (
        db.select(ModelPrediction, LabelEntry)
        .join(
            LabelEntry,
            (LabelEntry.entry_id == ModelPrediction.entry_id)
            & (LabelEntry.label_id == ModelPrediction.label_id),
        )
        .filter(
            ModelPrediction.version_id == version_id,
            ModelPrediction.label_id == label_id,
            ModelPrediction.value.isnot(None),
            LabelEntry.value.isnot(None),
            LabelEntry.is_deleted.is_(False),
        )
    )
    if trained_at is not None:
        query = query.filter(LabelEntry.created > trained_at)

    n_checked = 0
    n_agree = 0
    per_class: dict[str, dict[str, int]] = {}
    for prediction, label_entry in db.session.execute(query).all():
        # Manual and active learning writers store values in different formats.
        human = parse_label_value(label_entry.value)
        if len(human) != 1:
            continue
        truth = human[0]
        n_checked += 1
        bucket = per_class.setdefault(truth, {"n": 0, "agree": 0})
        bucket["n"] += 1
        if prediction.value == truth:
            n_agree += 1
            bucket["agree"] += 1

    return {
        "n_checked": n_checked,
        "n_agree": n_agree,
        "accuracy": (n_agree / n_checked) if n_checked else None,
        "per_class": {
            value: {**counts, "accuracy": counts["agree"] / counts["n"]}
            for value, counts in per_class.items()
        },
    }


def _unchecked_confident_predictions(label_id: int, version_id: int) -> list[ModelPrediction]:
    """Confident predictions this version made that no human has ruled on, most recent first.

    Confident means a singleton conformal prediction set — the cases where the model
    committed to an answer, which is exactly where a silent regression hides.

    Ordered by descending entry id: `Entry` carries no timestamp, so the
    autoincrementing primary key is the only available proxy for "most recent".
    """
    labelled = (
        db.select(LabelEntry.entry_id)
        .filter(LabelEntry.label_id == label_id, LabelEntry.is_deleted.is_(False))
        .scalar_subquery()
    )
    query = (
        db.select(ModelPrediction.entry_id)
        .join(Entry, Entry.id == ModelPrediction.entry_id)
        .filter(
            ModelPrediction.version_id == version_id,
            ModelPrediction.label_id == label_id,
            ModelPrediction.value.isnot(None),
            ModelPrediction.entry_id.notin_(labelled),
        )
        .order_by(Entry.id.desc())
    )
    rows = db.session.execute(query).scalars().all()

    # prediction_set is JSON, so the singleton filter is applied in Python rather
    # than in SQL, which would not be portable across SQLite and Postgres.
    by_entry = {
        p.entry_id: p
        for p in db.session.execute(
            db.select(ModelPrediction).filter(
                ModelPrediction.version_id == version_id,
                ModelPrediction.entry_id.in_(rows),
            )
        ).scalars()
    }
    confident: list[ModelPrediction] = []
    for entry_id in rows:
        prediction = by_entry.get(entry_id)
        if prediction is not None and len(prediction.prediction_set or []) == 1:
            confident.append(prediction)
    return confident


def unchecked_prediction_ids(label_id: int, version_id: int) -> list[int]:
    """Entry ids this version predicted confidently that no human has ruled on."""
    return [p.entry_id for p in _unchecked_confident_predictions(label_id, version_id)]


def audit_sample(label_id: int, version_id: int, n: int) -> list[int]:
    """Up to `n` confident-but-unchecked entries, balanced across predicted answers.

    An audit sample built by recency alone mostly reflects whatever the model
    predicts most often — the majority class dominates the sample and the resulting
    accuracy figure says little about the classes that matter most, usually the rare
    ones. Round-robin across predicted values instead, taking the most recent
    unchecked entry for each answer in turn, so a model that is confidently wrong on
    a minority class gets caught instead of averaged away.
    """
    n = max(0, n)
    if n == 0:
        return []

    buckets: dict[str | None, list[int]] = {}
    for prediction in _unchecked_confident_predictions(label_id, version_id):
        buckets.setdefault(prediction.value, []).append(prediction.entry_id)

    values = sorted(buckets, key=str)
    picked: list[int] = []
    while len(picked) < n and any(buckets[value] for value in values):
        for value in values:
            if not buckets[value]:
                continue
            picked.append(buckets[value].pop(0))
            if len(picked) == n:
                break
    return picked


def rank_models(
    reports: list[ModelHealth],
    rank_by: str = "audit_accuracy",
    min_audit_samples: int = DEFAULT_MIN_AUDIT_SAMPLES,
) -> list[ModelHealth]:
    """Order models worst-first by the configured signal.

    A model whose chosen signal has too little evidence behind it sorts last rather
    than winning on a number that means nothing — an accuracy of 0.0 measured on two
    entries must not outrank a real 0.6 measured on fifty.
    """
    if rank_by not in RANK_SIGNALS:
        rank_by = "audit_accuracy"

    def key(report: ModelHealth) -> tuple[int, float]:
        if rank_by == "audit_accuracy":
            if report.audit_accuracy is None or report.n_checked < min_audit_samples:
                return (1, 0.0)
            return (0, report.audit_accuracy)  # ascending: lowest accuracy first
        if rank_by == "coverage_drop":
            if report.coverage_drop is None:
                return (1, 0.0)
            return (0, -report.coverage_drop)  # largest drop first
        return (0, -float(report.unchecked_predictions))

    return sorted(reports, key=key)
