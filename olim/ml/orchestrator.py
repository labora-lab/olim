"""
Training Orchestrator for ML Models

This module orchestrates the complete training lifecycle:
1. Load labeled data from the database
2. Train ConformalPredictor directly (no in-memory full dataset)
3. Rank unlabeled project entries in paginated batches for the uncertainty cache
4. Save artifacts and register a new MLModelVersion
"""

from __future__ import annotations

import math
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
from sklearn.cluster import KMeans
from sklearn.metrics import pairwise_distances_argmin_min as dist_argmin
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder, normalize

from olim import db
from olim.database import (
    Entry,
    Label,
    bulk_append_model_predictions,
    delete_model_predictions,
    get_entries_by_ids,
    get_label,
    get_label_entries,
    get_project_entries_page,
    get_setting_value,
    update_ml_model,
)
from olim.entry_types.registry import get_entry_type_instance
from olim.label_types import get_class_values, is_open_label, parse_label_value
from olim.ml.artifacts import ArtifactManager
from olim.ml.classifiers.conformal import ConformalPredictor
from olim.ml.classifiers.tfidf_sklearn import (
    TfidfDecisionTreeClassifier,
    TfidfLightGBMClassifier,
    TfidfLogisticRegressionClassifier,
    TfidfXGBoostClassifier,
)
from olim.ml.metrics import (
    auc_roc,
    bootstrap_bundle,
    f1,
    macro_bundle,
    precision,
    recall,
)
from olim.ml.registry import ModelRegistry
from olim.settings import ES_INDEX
from olim.utils.es import es_search

if TYPE_CHECKING:
    from olim.ml.models import MLModel, MLModelVersion

AVAILABLE_MODELS = {
    "TfidfXGBoostClassifier": TfidfXGBoostClassifier,
    "TfidfLogisticRegressionClassifier": TfidfLogisticRegressionClassifier,
    "TfidfDecisionTreeClassifier": TfidfDecisionTreeClassifier,
    "TfidfLightGBMClassifier": TfidfLightGBMClassifier,
}

#: Metrics a user may set an early-stop goal on. Single source of truth shared with
#: the active learning settings UI so the dropdown cannot offer a metric that
#: `_compute_metrics` never produces.
GOAL_METRICS = (
    "macro_f1",
    "balanced_accuracy",
    "accuracy",
    "auc_roc",
    "macro_precision",
    "macro_recall",
    "coverage",
)

#: Entries in `metrics` that describe how the run went rather than how good the
#: model is. Kept out of the metric tiles and the per-round history table.
DIAGNOSTIC_METRICS = (
    "per_class",
    "validation_balanced",
    "conformal_degenerate",
    "conformal_alpha_effective",
)

#: Unlabelled documents added to the TF-IDF fitting corpus, on top of every
#: labelled one.
DEFAULT_VECTORIZER_POOL_SAMPLE = 2000


class TrainingOrchestrator:
    """Orchestrator for ML model training lifecycle."""

    def __init__(self, work_path: Path | str) -> None:
        self.work_path = Path(work_path)
        self.artifact_manager = ArtifactManager(self.work_path / "ml_models")
        self.registry = ModelRegistry()

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def train_new_version(
        self,
        model_id: int,
        user_id: int,
        force_retrain: bool = False,
        training_overrides: dict | None = None,
    ) -> MLModelVersion:
        """Train a new version of the model.

        Args:
            model_id: ID of the MLModel to train
            user_id: ID of the user triggering training
            force_retrain: Unused; kept for API compatibility

        Returns:
            Created MLModelVersion instance
        """
        model = self.registry.get_model(model_id)
        if model is None:
            raise ValueError(f"Model {model_id} not found")

        update_ml_model(model.id, status="training")

        start_time = time.time()

        overrides = training_overrides or {}
        try:
            # 1. Load labeled data (class_values fixes one ordering for the whole run)
            train_data, fields, class_values = self._prepare_training_data(model, overrides)

            # 2. Train ConformalPredictor directly
            conformal, val_list, balanced = self._build_and_train_conformal(
                model, train_data, class_values, fields, overrides
            )

            # 3. Rank unlabeled entries in batches → uncertainty cache
            labeled_ids = set(train_data.keys())
            cache_entries, coverage = self._rank_entries_batched(
                conformal, model, fields, labeled_ids, overrides=overrides
            )

            # 4. Metrics from held-out validation split
            metrics = self._compute_metrics(conformal, val_list, class_values)
            if coverage is not None:
                metrics["coverage"] = round(coverage, 4)
            metrics["validation_balanced"] = balanced
            metrics["conformal_alpha_effective"] = round(conformal.alpha_effective, 4)
            if conformal.degenerate:
                # Calibration set too small for the requested alpha; the threshold
                # was loosened so uncertainty ranking stays meaningful.
                metrics["conformal_degenerate"] = True

            training_duration = time.time() - start_time

            # 5. Persist artifacts
            encoder = LabelEncoder()
            encoder.fit(class_values)

            last_version = self.registry.get_active_version(model_id)
            version_number = 1 if last_version is None else last_version.version + 1

            artifact_path = self.artifact_manager.save_artifacts(
                model_id=model_id,
                version=version_number,
                model=conformal,
                encoder=encoder,
                policy=getattr(conformal, "_policy", None),
                fields=fields,
            )

            # 6. Conformal threshold (set during calibration)
            raw_threshold = getattr(conformal, "threshold", None)
            try:
                conformal_threshold = float(raw_threshold) if raw_threshold is not None else None
            except (TypeError, ValueError):
                conformal_threshold = None

            # 7. Register version
            version = self.registry.create_version(
                model_id=model_id,
                artifact_path=str(artifact_path),
                n_train_samples=len(train_data) - len(val_list),
                n_val_samples=len(val_list),
                metrics=metrics,
                created_by=user_id,
                trained_at=datetime.now(),
                training_duration=training_duration,
                class_distribution=self._get_class_distribution(train_data, class_values),
                conformal_threshold=conformal_threshold,
                cache_entries=cache_entries,
                auto_activate=True,
            )

            update_ml_model(model.id, status="active")

            # 8. Store model predictions for all unlabeled entries
            if model.label_id is not None:
                self._store_full_predictions(
                    conformal, encoder, model, version, cache_entries, fields, labeled_ids
                )

            return version

        except Exception as e:
            update_ml_model(model.id, status="draft")
            raise RuntimeError(f"Training failed: {e}") from e

    # ------------------------------------------------------------------ #
    # Data loading                                                         #
    # ------------------------------------------------------------------ #

    def _get_class_values(self, label: Label, include_abstain: bool) -> list[str]:
        """Return the sorted class value strings this model predicts.

        Resolved from the label's own configuration — see
        olim.label_types.get_class_values. One ordering is derived here and reused
        for the training indices, the classifier's class space and the LabelEncoder;
        deriving them separately is how predictions used to come back attached to
        the wrong class name.
        """
        return get_class_values(label, include_abstain=include_abstain)

    def _prepare_training_data(
        self, model: MLModel, overrides: dict | None = None
    ) -> tuple[dict[int, tuple[str, int]], list[str], list[str]]:
        """Load labeled entries from the DB and extract their texts.

        Returns:
            train_data: {entry_db_id: (text, label_idx)}
            fields: list of text field names
            class_values: ordered class value strings; index == label_idx
        """
        if model.label_id is None:
            raise ValueError("Model is not linked to a label")

        label = get_label(model.label_id)
        if label is None:
            raise ValueError(f"Label {model.label_id} not found")

        overrides = overrides or {}
        training_config = model.training_config or {}
        include_abstain = bool(
            overrides.get("include_abstain", training_config.get("include_abstain", False))
        )

        label_entries = get_label_entries(label.id)
        if not label_entries:
            raise ValueError(f"No labeled data found for label {label.id}")

        fields = self._get_fields_from_label(label)

        decoded = {le.entry.id: parse_label_value(le.value) for le in label_entries}
        observed = {v for values in decoded.values() for v in values}
        class_values = self._get_class_values(label, include_abstain)
        if is_open_label(label.label_type) and not class_values:
            # No declared option set to go on; the values in the database are all
            # there is. Only reachable for label types that do not fix their options.
            class_values = sorted(observed)
        if len(class_values) < 2:
            raise ValueError(
                f"Label {label.id} has fewer than two trainable classes "
                f"({class_values}) — nothing to learn."
            )
        value_to_idx = {val: idx for idx, val in enumerate(class_values)}

        train_data: dict[int, tuple[str, int]] = {}
        skipped_abstain = 0
        skipped_multi = 0
        for le in label_entries:
            values = decoded[le.entry.id]
            if len(values) != 1:
                # Nothing selected, or a genuine multi-select answer this
                # single-label classifier has no way to represent.
                skipped_multi += 1
                continue
            value = values[0]
            # "Don't know" style answers say something about the annotator, not the
            # text, and training on them as a class blurs the real boundary.
            if value not in value_to_idx:
                skipped_abstain += 1
                continue
            text = self._extract_entry_text(le.entry, fields)
            train_data[le.entry.id] = (text, value_to_idx[value])

        if skipped_abstain or skipped_multi:
            print(
                f"[training] label {label.id}: skipped {skipped_abstain} abstain and "
                f"{skipped_multi} empty/multi-select value(s); classes: {class_values}"
            )
        if not train_data:
            # Almost always a configuration mismatch rather than missing data: the
            # values in the database are not the ones the label declares.
            raise ValueError(
                f"No trainable labeled data for label {label.id} "
                f"(type={label.label_type!r}): {len(label_entries)} annotation(s) "
                f"hold {sorted(observed)}, but the label declares {class_values}. "
                f"Check the label's type and its configured options."
            )

        return train_data, fields, class_values

    # ------------------------------------------------------------------ #
    # Training                                                             #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _balanced_split(
        items: list[tuple[str, int]], split_ratio: float, seed: int
    ) -> tuple[list[tuple[str, int]], list[tuple[str, int]]] | None:
        """Hold out the same number of examples from every class.

        A proportional (stratified) holdout on a 90/10 dataset produces a 90/10
        validation set, where predicting the majority class scores 0.90 accuracy —
        enough to satisfy a typical early-stop goal with a model that never gets a
        minority case right. Equal per-class counts remove that free ride.

        Returns None when the data cannot support a balanced holdout, leaving the
        caller to fall back to a stratified split.
        """
        by_class: defaultdict[int, list[tuple[str, int]]] = defaultdict(list)
        for item in items:
            by_class[item[1]].append(item)

        present = sorted(by_class)
        if len(present) < 2:
            return None

        min_count = min(len(by_class[c]) for c in present)
        if min_count < 2:
            return None

        # Size the holdout from the whole dataset's budget, not from the rarest
        # class: with 12% prevalence, `min_count * (1 - split)` yields two entries
        # even at a hundred labels, and a metric measured on two entries is noise
        # no averaging can rescue.
        # +1e-9 absorbs binary float error — 1 - 0.8 is 0.19999999999999996.
        budget = math.floor(len(items) * (1 - split_ratio) / len(present) + 1e-9)
        # ...but never take more than half of a class, or the rare class the model
        # most needs to learn from ends up in validation instead of training.
        per_class_val = min(budget, min_count // 2)
        per_class_val = max(1, per_class_val)

        rng = np.random.default_rng(seed)
        train: list[tuple[str, int]] = []
        val: list[tuple[str, int]] = []
        for cls in present:
            group = by_class[cls]
            order = rng.permutation(len(group))
            # Never strip a class of every training example.
            take = min(per_class_val, len(group) - 1)
            val.extend(group[i] for i in order[:take])
            train.extend(group[i] for i in order[take:])

        if not train or not val:
            return None
        return train, val

    def _collect_vectorizer_corpus(
        self,
        project_id: int,
        fields: list[str],
        labeled_texts: list[str],
        limit: int,
        batch_size: int = 500,
    ) -> list[str]:
        """Labelled texts plus a capped sample of unlabelled ones.

        Fitting TF-IDF on the training split alone means a round-one vocabulary of a
        handful of documents, so validation and pool texts vectorise to near-empty
        rows. Only the texts are used, never the labels — no leakage.
        """
        corpus = list(labeled_texts)
        if limit <= 0:
            return corpus

        added = 0
        offset = 0
        while added < limit:
            batch: list[Entry] = get_project_entries_page(project_id, offset, batch_size)
            if not batch:
                break
            offset += batch_size
            texts = self._batch_extract_texts(batch, fields)
            corpus.extend(texts[: limit - added])
            added += len(texts)
            db.session.expire_all()
        return corpus

    def _build_and_train_conformal(
        self,
        model: MLModel,
        train_data: dict[int, tuple[str, int]],
        class_values: list[str],
        fields: list[str],
        overrides: dict | None = None,
    ) -> tuple[ConformalPredictor, list[tuple[str, int]], bool]:
        """Instantiate and train a ConformalPredictor from labeled data.

        Returns:
            conformal: Trained ConformalPredictor
            val_list:  Held-out calibration samples [(text, label_idx), ...]
            balanced:  Whether the validation split is class-balanced
        """
        if model.label_id is None:
            raise ValueError("Model is not linked to a label")
        label = get_label(model.label_id)
        if label is None:
            raise ValueError(f"Label {model.label_id} not found")
        n_classes = len(class_values)

        overrides = overrides or {}
        training_config = model.training_config or {}
        model_config = dict(model.model_config or {})

        split_ratio = float(overrides.get("split", training_config.get("split", 0.8)))
        split_ratio = max(0.1, min(0.95, split_ratio))
        global_alpha = float(get_setting_value("ml.conformal_alpha") or 0.1)
        alpha = float(overrides.get("alpha", training_config.get("alpha", global_alpha)))
        balance_classes = bool(
            overrides.get("balance_classes", training_config.get("balance_classes", True))
        )
        pool_sample = int(
            overrides.get(
                "vectorizer_pool_sample",
                training_config.get("vectorizer_pool_sample", DEFAULT_VECTORIZER_POOL_SAMPLE),
            )
        )

        all_items: list[tuple[str, int]] = list(train_data.values())
        # Seed with the model id so the split is deterministic across
        # retrains of the same model, without sharing an identical split
        # pattern across different models.
        split_seed = model.id

        balanced = True
        split = self._balanced_split(all_items, split_ratio, split_seed)
        if split is None:
            balanced = False
            item_labels = [lbl for _, lbl in all_items]
            try:
                # Stratify so every class is represented in both splits in
                # roughly the same proportion instead of a positional slice,
                # which can leave a rare class entirely out of training.
                train_list, val_list = train_test_split(
                    all_items,
                    test_size=1 - split_ratio,
                    random_state=split_seed,
                    stratify=item_labels,
                )
            except ValueError:
                # A class with too few samples to stratify (e.g. a single
                # example); fall back to a plain shuffled split.
                train_list, val_list = train_test_split(
                    all_items,
                    test_size=1 - split_ratio,
                    random_state=split_seed,
                )
        else:
            train_list, val_list = split

        fit_corpus = self._collect_vectorizer_corpus(
            label.project_id,
            fields,
            [text for text, _ in all_items],
            pool_sample,
        )

        model_cls = AVAILABLE_MODELS.get(model.algorithm, TfidfXGBoostClassifier)
        inner = model_cls(
            **{
                **model_config,
                "n_classes": n_classes,
                "balance_classes": balance_classes,
            }
        )
        conformal = ConformalPredictor(
            model=inner,
            alpha=alpha,
            n_classes=n_classes,
        )
        conformal.train(train_list, val_list if val_list else None, fit_corpus=fit_corpus)

        return conformal, val_list, balanced

    # ------------------------------------------------------------------ #
    # Batch uncertainty ranking                                            #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _assemble_pool(
        scores: list[tuple[int, float]], pool_size: int, certain_rate: float
    ) -> tuple[list[tuple[int, float]], set[int]]:
        """Candidate pool for clustering: uncertain head plus a certain tail.

        `scores` must already be sorted by descending uncertainty. `certain_rate` is
        the share of the pool taken from the most-certain end — those points go in
        *before* clustering so they shape the centroids, per Genari & Goedert (2025),
        whose headline configuration is 30/70 high/low.

        Returns the pool and the ids that came from the certain end.
        """
        n_low = round(pool_size * certain_rate)
        n_high = max(1, pool_size - n_low)
        low_candidates = list(reversed(scores[-n_low:])) if n_low else []
        low_ids = {eid for eid, _ in low_candidates}

        pool: list[tuple[int, float]] = []
        seen: set[int] = set()
        for eid, score in scores[:n_high] + low_candidates:
            if eid in seen:
                continue  # pool wider than the dataset — the two ends overlap
            seen.add(eid)
            pool.append((eid, score))
        # An id reached from the uncertain head first is not a "certain" pick.
        return pool, low_ids - {eid for eid, _ in scores[:n_high]}

    def _rank_entries_batched(
        self,
        conformal: ConformalPredictor,
        ml_model: MLModel,
        fields: list[str],
        labeled_ids: set[int],
        batch_size: int = 500,
        overrides: dict | None = None,
    ) -> tuple[list[dict], float | None]:
        """Score all unlabeled project entries in batches and return ranked cache.

        Follows the selection procedure of Genari & Goedert (2025), arXiv:2502.04372:
        rank the unlabelled pool by conformal score, take the top `pool_size`
        candidates, mix in a `certain_rate` share of *low*-uncertainty points, cluster
        the whole pool with k-means over the model's embeddings, and take the entry
        nearest each centroid. Remaining cache slots are filled at random from the
        rest of the pool, as the paper specifies — filling them in score order would
        reintroduce exactly the redundancy the clustering step exists to remove.

        The low-uncertainty share joins the pool *before* clustering so those points
        influence the centroids. They keep a running check that the model still gets
        easy cases right; the paper's headline configuration is 30/70 high/low.

        Returns a list of dicts with keys:
            id     — Entry DB primary key
            score  — Uncertainty score (higher = more uncertain)
            reason — "diverse" | "uncertainty" | "certain"

        Uses paginated DB queries to avoid loading the full dataset into RAM.
        Session objects are expired after each batch to keep memory usage flat.
        """
        if ml_model.label_id is None:
            return [], None
        label = get_label(ml_model.label_id)
        if label is None:
            return [], None
        project_id = label.project_id

        overrides = overrides or {}
        subsample_config = ml_model.subsample_config
        if not subsample_config or not isinstance(subsample_config, list):
            subsample_config = [1000, 20, 20]
        pool_size = int(overrides.get("pool_size", subsample_config[0]))
        cache_size = int(
            overrides.get("cache_size", subsample_config[-2] if len(subsample_config) >= 2 else 20)
        )
        n_clusters = int(
            overrides.get("n_clusters", subsample_config[-1] if len(subsample_config) >= 2 else 20)
        )
        certain_rate = float(overrides.get("certain_rate", 0.0))
        certain_rate = max(0.0, min(0.9, certain_rate))

        rng = np.random.default_rng(ml_model.id)

        # Both ends of the ranking are needed, so prune from the middle rather than
        # capping the head: this keeps the most uncertain and the most certain exactly
        # while still bounding memory on very large pools.
        retain = max(pool_size * 2, 1000)

        scores: list[tuple[int, float]] = []
        n_trusted = 0
        n_total = 0
        offset = 0
        while True:
            batch: list[Entry] = get_project_entries_page(project_id, offset, batch_size)
            if not batch:
                break
            offset += batch_size
            unlabeled = [e for e in batch if e.id not in labeled_ids]
            if unlabeled:
                texts = self._batch_extract_texts(unlabeled, fields)
                uncertainties = conformal.predict_uncert(texts)
                trusted_mask = conformal.predict_trusted(texts)
                n_trusted += int(np.sum(trusted_mask))
                n_total += len(texts)
                scores.extend(
                    zip(
                        [e.id for e in unlabeled],
                        (float(u) for u in uncertainties),
                        strict=False,
                    )
                )
                if len(scores) > retain * 3:
                    scores.sort(key=lambda x: x[1], reverse=True)
                    scores = scores[:retain] + scores[-retain:]
            # Expire batch objects so SQLAlchemy doesn't accumulate them in the identity map
            db.session.expire_all()
            # No early break — scan full dataset for accurate coverage

        coverage: float | None = n_trusted / n_total if n_total > 0 else None

        if not scores:
            return [], coverage

        # Sort descending by uncertainty
        scores.sort(key=lambda x: x[1], reverse=True)

        pool, low_ids = self._assemble_pool(scores, pool_size, certain_rate)
        pool_ids = [eid for eid, _ in pool]

        embeddings = None
        if len(pool_ids) > n_clusters:
            entry_map: dict[int, Entry] = {e.id: e for e in get_entries_by_ids(pool_ids)}
            pool_texts = [self._extract_entry_text(entry_map[eid], fields) for eid in pool_ids]
            embeddings = conformal.get_embeddings(pool_texts)

        selected = self._select_from_pool(pool, low_ids, embeddings, n_clusters, cache_size, rng)
        return selected, coverage

    @staticmethod
    def _select_from_pool(
        pool: list[tuple[int, float]],
        low_ids: set[int],
        embeddings: Any,  # noqa: ANN401 — sparse matrix or None
        n_clusters: int,
        cache_size: int,
        rng: np.random.Generator,
    ) -> list[dict]:
        """Pick the cache from the candidate pool: cluster centroids, then random fill.

        Split out from the paging loop above so it can be exercised without a
        database — see tests/benchmarks.
        """
        score_map = dict(pool)
        pool_ids = [eid for eid, _ in pool]

        def as_entry(eid: int, reason: str | None = None) -> dict:
            return {
                "id": eid,
                "score": round(score_map[eid], 4),
                "reason": reason or ("certain" if eid in low_ids else "uncertainty"),
            }

        if embeddings is None or len(pool_ids) <= n_clusters:
            return [as_entry(eid) for eid in pool_ids[:cache_size]]

        # L2-normalise so clustering compares direction rather than document length,
        # and keep the matrix sparse — densifying a 1000 x 50k TF-IDF pool would cost
        # hundreds of MB.
        normalised = normalize(embeddings)
        kmeans = KMeans(
            n_clusters=min(n_clusters, len(pool_ids)), n_init="auto", random_state=0
        ).fit(normalised)
        centroid_idxs = dist_argmin(kmeans.cluster_centers_, normalised)[0]
        best_ids = [pool_ids[i] for i in centroid_idxs]
        diverse_set = set(best_ids)

        rest = [eid for eid in pool_ids if eid not in diverse_set]
        rng.shuffle(rest)

        selected = [as_entry(eid, "diverse") for eid in best_ids]
        selected += [as_entry(eid) for eid in rest]
        return selected[:cache_size]

    # ------------------------------------------------------------------ #
    # Metrics                                                              #
    # ------------------------------------------------------------------ #

    def _compute_metrics(
        self,
        conformal: ConformalPredictor,
        val_list: list[tuple[str, int]],
        class_values: list[str],
    ) -> dict[str, Any]:
        """Score the held-out validation split.

        Macro (per-class averaged) figures sit alongside accuracy on purpose: on an
        imbalanced label, accuracy flatters a model that only ever predicts the
        majority class, and an early-stop goal set on it fires far too soon.

        The split doubles as the conformal calibration set. That is not leakage for
        these numbers — calibration picks a threshold, it never refits the
        classifier — and `coverage` is measured on the unlabelled pool instead.
        """
        if not val_list:
            return {}

        n_classes = len(class_values)
        val_texts = [text for text, _ in val_list]
        val_labels = np.array([lbl for _, lbl in val_list])
        preds = np.array(conformal.model.predict(val_texts))
        try:
            proba_matrix = np.array(conformal.model.predict_proba(val_texts))
        except Exception:
            proba_matrix = None

        metrics: dict[str, Any] = {}

        def bundle(labels: Any, predictions: Any, proba: Any) -> dict[str, float]:  # noqa: ANN401
            scores = macro_bundle(labels, predictions, n_classes)
            if proba is not None:
                auc = auc_roc(labels, predictions, label_proba=proba)
                if np.isfinite(auc):
                    scores["auc_roc"] = auc
            return scores

        try:
            bootstrapped = bootstrap_bundle(bundle, val_labels, preds, label_proba=proba_matrix)
        except Exception:
            bootstrapped = {}

        for name, (point, low, high, valid) in bootstrapped.items():
            if point is None or not np.isfinite(point):
                continue
            metrics[name] = round(float(point), 4)
            if low is not None and high is not None:
                metrics[f"{name}_ci"] = [round(low, 4), round(high, 4)]
            else:
                # Too few usable resamples to state an interval — say so rather
                # than imply the point estimate is precise.
                metrics[f"{name}_ci_valid_frac"] = round(valid, 3)

        # Per-class breakdown (display only — not selectable as a goal)
        per_class: dict[str, dict[str, float]] = {}
        for idx, value in enumerate(class_values):
            support = int(np.sum(val_labels == idx))
            try:
                per_class[value] = {
                    "precision": round(precision(val_labels, preds, target=idx), 4),
                    "recall": round(recall(val_labels, preds, target=idx), 4),
                    "f1": round(f1(val_labels, preds, target=idx), 4),
                    "support": support,
                }
            except Exception:
                continue
        if per_class:
            metrics["per_class"] = per_class

        return metrics

    # ------------------------------------------------------------------ #
    # Helpers                                                              #
    # ------------------------------------------------------------------ #

    def _get_fields_from_label(self, label: Label) -> list[str]:
        if label.learner_parameters and "fields" in label.learner_parameters:
            return label.learner_parameters["fields"]
        return ["text"]

    def _extract_entry_text(self, entry: Entry, fields: list[str]) -> str:
        instance = get_entry_type_instance(entry.type)
        if instance is None:
            return str(entry.entry_id)

        df = instance.extract_texts(entry.entry_id, dataset_id=entry.dataset_id)
        if df.empty:
            return str(entry.entry_id)

        text_parts = [str(df[f].iloc[0]) for f in fields if f in df.columns]
        if not text_parts:
            text_parts = [
                str(df[col].iloc[0])
                for col in df.columns
                if col != "entry_id" and df[col].dtype == object
            ]
        return " ".join(text_parts) if text_parts else str(entry.entry_id)

    def _batch_extract_texts(self, entries: list[Entry], fields: list[str]) -> list[str]:
        """Batch ES text extraction grouped by dataset — one query per batch per dataset.

        For single_text entries, fires one ES query per dataset covering all entries in
        the batch.  Other entry types fall back to per-entry extraction.
        """
        from collections import defaultdict

        if not entries:
            return []

        texts: list[str] = [str(e.entry_id) for e in entries]
        groups: defaultdict[tuple[str, int], list[int]] = defaultdict(list)
        for i, entry in enumerate(entries):
            groups[(entry.type, entry.dataset_id)].append(i)

        for (entry_type, dataset_id), indices in groups.items():
            batch_entries = [entries[i] for i in indices]

            if entry_type != "single_text":
                for i, entry in zip(indices, batch_entries, strict=False):
                    texts[i] = self._extract_entry_text(entry, fields)
                continue

            entry_ids = [str(e.entry_id) for e in batch_entries]
            try:
                index = ES_INDEX.format(dataset_id=dataset_id)
                res = es_search(
                    query={"terms": {"_id": entry_ids}},
                    index=index,
                    size=len(entry_ids),
                )
                id_to_src: dict[str, dict] = {
                    hit["_id"]: hit["_source"] for hit in res.get("hits", {}).get("hits", [])
                }
                for i, entry in zip(indices, batch_entries, strict=False):
                    src = id_to_src.get(str(entry.entry_id), {})
                    text_parts = [str(src[f]) for f in fields if src.get(f)]
                    if not text_parts:
                        fallback = src.get("text", "")
                        text_parts = [str(fallback)] if fallback else []
                    texts[i] = (
                        " ".join(text_parts)
                        if text_parts
                        else self._extract_entry_text(entry, fields)
                    )
            except Exception:
                for i, entry in zip(indices, batch_entries, strict=False):
                    texts[i] = self._extract_entry_text(entry, fields)

        return texts

    def _store_full_predictions(
        self,
        conformal: ConformalPredictor,
        encoder: LabelEncoder,
        ml_model: MLModel,
        version: MLModelVersion,
        cache_entries: list[dict],
        fields: list[str],
        labeled_ids: set[int],
        batch_size: int = 500,
        insert_chunk: int = 5000,
    ) -> None:
        """Store predictions for ALL unlabeled entries using batch ES extraction.

        Replaces any existing predictions for this model version.
        Writes in chunks of insert_chunk rows to keep memory usage bounded.
        """
        if ml_model.label_id is None:
            return
        label = get_label(ml_model.label_id)
        if label is None:
            return
        project_id = label.project_id

        score_map = {item["id"]: item["score"] for item in cache_entries}
        threshold = getattr(conformal, "threshold", None)
        classes = encoder.classes_

        # Delete old predictions first
        delete_model_predictions(ml_model.id, version.id)

        pending: list[dict] = []
        offset = 0
        while True:
            batch: list[Entry] = get_project_entries_page(project_id, offset, batch_size)
            if not batch:
                break
            offset += batch_size
            unlabeled = [e for e in batch if e.id not in labeled_ids]
            if not unlabeled:
                db.session.expire_all()
                continue

            texts = self._batch_extract_texts(unlabeled, fields)
            try:
                probas = conformal.model.predict_proba(texts)
            except Exception:
                db.session.expire_all()
                continue

            for entry, proba in zip(unlabeled, probas, strict=False):
                predicted_idx = int(np.argmax(proba))
                predicted_class: str | None = None
                if classes is not None and 0 <= predicted_idx < len(classes):
                    predicted_class = str(classes[predicted_idx])

                if threshold is not None and classes is not None:
                    entry_scores = 1 - np.array(proba)
                    pred_set = [
                        str(classes[i])
                        for i in range(min(len(proba), len(classes)))
                        if entry_scores[i] <= threshold
                    ]
                else:
                    pred_set = [predicted_class] if predicted_class else []

                pending.append(
                    {
                        "entry_id": entry.id,
                        "label_id": ml_model.label_id,
                        "model_id": ml_model.id,
                        "version_id": version.id,
                        "value": predicted_class,
                        "score": score_map.get(entry.id),
                        "prediction_set": pred_set,
                    }
                )

            if len(pending) >= insert_chunk:
                bulk_append_model_predictions(pending)
                pending = []

            db.session.expire_all()

        if pending:
            bulk_append_model_predictions(pending)

    def _get_class_distribution(self, train_data: dict, class_values: list[str]) -> dict:
        counts: dict[int, int] = {}
        for _, label_idx in train_data.values():
            counts[label_idx] = counts.get(label_idx, 0) + 1
        return {
            (class_values[idx] if 0 <= idx < len(class_values) else str(idx)): n
            for idx, n in sorted(counts.items())
        }

    def get_next_al_entries(self, model_id: int, n: int = 10) -> list[int]:
        """Return the first n entry IDs from the active version's uncertainty cache."""
        version = self.registry.get_active_version(model_id)
        if version is None:
            raise ValueError(f"No active version found for model {model_id}")
        if version.cache_entries:
            return [item["id"] for item in version.cache_entries[:n]]
        return []
