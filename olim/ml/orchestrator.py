"""
Training Orchestrator for ML Models

This module orchestrates the complete training lifecycle:
1. Load labeled data from the database
2. Train ConformalPredictor directly (no in-memory full dataset)
3. Rank unlabeled project entries in paginated batches for the uncertainty cache
4. Save artifacts and register a new MLModelVersion
"""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
from sklearn.cluster import KMeans
from sklearn.metrics import pairwise_distances_argmin_min as dist_argmin
from sklearn.preprocessing import LabelEncoder

from olim import db
from olim.database import (
    Entry,
    Label,
    add_model_prediction,
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
from olim.label_types import get_label_type_module
from olim.ml.artifacts import ArtifactManager
from olim.ml.classifiers.conformal import ConformalPredictor
from olim.ml.classifiers.tfidf_sklearn import (
    TfidfDecisionTreeClassifier,
    TfidfLightGBMClassifier,
    TfidfLogisticRegressionClassifier,
    TfidfXGBoostClassifier,
)
from olim.ml.metrics import accuracy, auc_roc, bootstrap_metric
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
            # 1. Load labeled data
            train_data, fields = self._prepare_training_data(model)

            # 2. Train ConformalPredictor directly
            conformal, val_list, label_values = self._build_and_train_conformal(
                model, train_data, overrides
            )

            # 3. Rank unlabeled entries in batches → uncertainty cache
            labeled_ids = set(train_data.keys())
            cache_entries, coverage = self._rank_entries_batched(conformal, model, fields, labeled_ids, overrides=overrides)

            # 4. Metrics from held-out validation split
            metrics = self._compute_metrics(conformal, val_list)
            if coverage is not None:
                metrics["coverage"] = round(coverage, 4)

            training_duration = time.time() - start_time

            # 5. Persist artifacts
            encoder = LabelEncoder()
            encoder.fit(label_values)

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

            # 6. Conformal threshold (set during calibration).
            # threshold is annotated list[float]|None but is actually a numpy scalar after training.
            raw_threshold = getattr(conformal, "threshold", None)
            try:
                conformal_threshold = float(raw_threshold) if raw_threshold is not None else None  # type: ignore[arg-type]
            except (TypeError, ValueError):
                conformal_threshold = None

            # 7. Register version
            version = self.registry.create_version(
                model_id=model_id,
                artifact_path=str(artifact_path),
                n_train_samples=len(train_data),
                n_val_samples=len(val_list),
                metrics=metrics,
                created_by=user_id,
                trained_at=datetime.now(),
                training_duration=training_duration,
                class_distribution=self._get_class_distribution(train_data),
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

    def _prepare_training_data(
        self, model: MLModel
    ) -> tuple[dict[int, tuple[str, int]], list[str]]:
        """Load labeled entries from the DB and extract their texts.

        Returns:
            train_data: {entry_db_id: (text, label_idx)}
            fields: list of text field names
        """
        if model.label_id is None:
            raise ValueError("Model is not linked to a label")

        label = get_label(model.label_id)
        if label is None:
            raise ValueError(f"Label {model.label_id} not found")

        label_entries = get_label_entries(label.id)
        if not label_entries:
            raise ValueError(f"No labeled data found for label {label.id}")

        fields = self._get_fields_from_label(label)

        label_values_sorted = sorted({le.value for le in label_entries if le.value is not None})
        value_to_idx = {val: idx for idx, val in enumerate(label_values_sorted)}

        train_data: dict[int, tuple[str, int]] = {}
        for le in label_entries:
            text = self._extract_entry_text(le.entry, fields)
            train_data[le.entry.id] = (text, value_to_idx[le.value])

        return train_data, fields

    # ------------------------------------------------------------------ #
    # Training                                                             #
    # ------------------------------------------------------------------ #

    def _build_and_train_conformal(
        self,
        model: MLModel,
        train_data: dict[int, tuple[str, int]],
        overrides: dict | None = None,
    ) -> tuple[ConformalPredictor, list[tuple[str, int]], list[str]]:
        """Instantiate and train a ConformalPredictor from labeled data.

        Returns:
            conformal: Trained ConformalPredictor
            val_list:  Held-out calibration samples [(text, label_idx), ...]
            label_values: Ordered list of label value strings
        """
        if model.label_id is None:
            raise ValueError("Model is not linked to a label")
        label = get_label(model.label_id)
        if label is None:
            raise ValueError(f"Label {model.label_id} not found")
        label_type_module = get_label_type_module(label.label_type)
        label_values = [opt[0] for opt in label_type_module.get_label_options()]
        n_classes = len(label_values)

        overrides = overrides or {}
        training_config = model.training_config or {}
        model_config = model.model_config or {}

        split_ratio = float(overrides.get("split", training_config.get("split", 0.8)))
        split_ratio = max(0.1, min(0.95, split_ratio))
        global_alpha = float(get_setting_value("ml.conformal_alpha") or 0.1)
        alpha = float(overrides.get("alpha", training_config.get("alpha", global_alpha)))

        all_items: list[tuple[str, int]] = list(train_data.values())
        split = max(1, int(len(all_items) * split_ratio))
        train_list = all_items[:split]
        val_list = all_items[split:]

        model_cls = AVAILABLE_MODELS.get(model.algorithm, TfidfXGBoostClassifier)
        inner = model_cls(**{**model_config, "n_classes": n_classes})
        conformal = ConformalPredictor(
            model=inner,
            alpha=alpha,
            n_classes=n_classes,
        )
        conformal.train(train_list, val_list if val_list else None)

        return conformal, val_list, label_values

    # ------------------------------------------------------------------ #
    # Batch uncertainty ranking                                            #
    # ------------------------------------------------------------------ #

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

        Returns a list of dicts with keys:
            id     — Entry DB primary key
            score  — Uncertainty score (higher = more uncertain)
            reason — "diverse" | "uncertainty" | "certain"

        certain_rate (0–1) controls what fraction of the cache is filled with
        low-uncertainty entries so the model also sees confident examples.

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
        pool_size    = int(overrides.get("pool_size",    subsample_config[0]))
        cache_size   = int(overrides.get("cache_size",   subsample_config[-2] if len(subsample_config) >= 2 else 20))
        n_clusters   = int(overrides.get("n_clusters",   subsample_config[-1] if len(subsample_config) >= 2 else 20))
        certain_rate = float(overrides.get("certain_rate", 0.0))
        certain_rate = max(0.0, min(0.5, certain_rate))  # cap at 50 %

        n_certain  = int(cache_size * certain_rate)
        n_uncertain = cache_size - n_certain

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
                # Only accumulate ranking candidates until we have enough
                if len(scores) < pool_size * 3:
                    scores.extend(zip([e.id for e in unlabeled], uncertainties.tolist(), strict=False))
            # Expire batch objects so SQLAlchemy doesn't accumulate them in the identity map
            db.session.expire_all()
            # No early break — scan full dataset for accurate coverage

        coverage: float | None = n_trusted / n_total if n_total > 0 else None

        if not scores:
            return [], coverage

        # Sort descending by uncertainty
        scores.sort(key=lambda x: x[1], reverse=True)

        # Certain entries: take from the low-uncertainty tail (outside the uncertain pool)
        certain_entries: list[dict] = []
        if n_certain > 0:
            tail = scores[pool_size:] if len(scores) > pool_size else []
            # tail is sorted descending, so the last items are most certain
            certain_candidates = list(reversed(tail[:n_certain * 3])) if tail else []
            certain_entries = [
                {"id": eid, "score": round(sc, 4), "reason": "certain"}
                for eid, sc in certain_candidates[:n_certain]
            ]

        top = scores[:pool_size]
        score_map = dict(top)

        if len(top) <= n_clusters:
            uncertain_entries = [
                {"id": eid, "score": round(sc, 4), "reason": "uncertainty"}
                for eid, sc in top[:n_uncertain]
            ]
            return self._interleave_certain(uncertain_entries, certain_entries, certain_rate), coverage

        # KMeans clustering for diversity
        top_ids = [eid for eid, _ in top]
        entry_map: dict[int, Entry] = {
            e.id: e
            for e in get_entries_by_ids(top_ids)
        }
        top_texts = [self._extract_entry_text(entry_map[eid], fields) for eid in top_ids]

        raw_embeddings = conformal.get_embeddings(top_texts)
        embeddings = raw_embeddings.toarray() if hasattr(raw_embeddings, "toarray") else np.array(raw_embeddings)
        kmeans = KMeans(n_clusters=min(n_clusters, len(top_ids)), n_init="auto").fit(embeddings)
        centroid_idxs = dist_argmin(kmeans.cluster_centers_, embeddings)[0]
        best_ids = [top_ids[i] for i in centroid_idxs]
        diverse_set = set(best_ids)
        rest = [eid for eid in top_ids if eid not in diverse_set]

        uncertain_entries = (
            [{"id": eid, "score": round(score_map[eid], 4), "reason": "diverse"} for eid in best_ids]
            + [{"id": eid, "score": round(score_map[eid], 4), "reason": "uncertainty"} for eid in rest]
        )[:n_uncertain]

        return self._interleave_certain(uncertain_entries, certain_entries, certain_rate), coverage

    @staticmethod
    def _interleave_certain(
        uncertain: list[dict], certain: list[dict], rate: float
    ) -> list[dict]:
        """Interleave certain entries into the uncertain list at the given rate.

        E.g. rate=0.2 → insert one certain entry every 5 positions.
        """
        if not certain or rate <= 0:
            return uncertain
        step = max(1, round(1.0 / rate))  # positions between certain insertions
        result: list[dict] = []
        ci = ui = 0
        pos = 0
        while ui < len(uncertain) or ci < len(certain):
            if ci < len(certain) and pos > 0 and pos % step == step - 1:
                result.append(certain[ci])
                ci += 1
            elif ui < len(uncertain):
                result.append(uncertain[ui])
                ui += 1
            else:
                result.append(certain[ci])
                ci += 1
            pos += 1
        return result

    # ------------------------------------------------------------------ #
    # Prediction storage                                                   #
    # ------------------------------------------------------------------ #

    def _store_cache_predictions(
        self,
        conformal: ConformalPredictor,
        encoder: LabelEncoder,
        ml_model: MLModel,
        version: MLModelVersion,
        cache_entries: list[dict],
        fields: list[str],
    ) -> None:
        """Batch-predict cache entries and store results in model_predictions table.

        Called after a new version is registered so version.id is available.
        Runs predict_proba on cache entry texts to extract the predicted class,
        then upserts one ModelPrediction row per entry.
        """
        entry_ids = [item["id"] for item in cache_entries]
        entry_map: dict[int, Entry] = {
            e.id: e
            for e in get_entries_by_ids(entry_ids)
        }
        score_map = {item["id"]: item["score"] for item in cache_entries}

        texts = [self._extract_entry_text(entry_map[eid], fields) for eid in entry_ids if eid in entry_map]
        valid_ids = [eid for eid in entry_ids if eid in entry_map]
        if not texts:
            return

        try:
            probas = conformal.model.predict_proba(texts)
        except Exception:
            return

        threshold = getattr(conformal, "threshold", None)
        classes = encoder.classes_
        for eid, proba in zip(valid_ids, probas, strict=False):
            predicted_idx = int(np.argmax(proba))
            predicted_class: str | None = None
            if classes is not None and 0 <= predicted_idx < len(classes):
                predicted_class = str(classes[predicted_idx])

            if threshold is not None and classes is not None:
                scores = 1 - np.array(proba)
                pred_set = [str(classes[i]) for i in range(len(proba)) if scores[i] <= threshold]
            else:
                pred_set = [predicted_class] if predicted_class else []

            try:
                add_model_prediction(
                    entry_id=eid,
                    label_id=ml_model.label_id,  # type: ignore[arg-type]
                    model_id=ml_model.id,
                    version_id=version.id,
                    value=predicted_class,
                    score=score_map.get(eid),
                    prediction_set=pred_set,
                )
            except Exception:
                pass  # don't fail training if prediction storage fails

    # ------------------------------------------------------------------ #
    # Metrics                                                              #
    # ------------------------------------------------------------------ #

    def _compute_metrics(
        self,
        conformal: ConformalPredictor,
        val_list: list[tuple[str, int]],
    ) -> dict[str, Any]:
        """Compute accuracy and AUC-ROC on the held-out validation split."""
        if not val_list:
            return {}

        val_texts  = [text for text, _ in val_list]
        val_labels = np.array([lbl for _, lbl in val_list])
        preds      = np.array(conformal.model.predict(val_texts))

        metrics: dict[str, Any] = {}
        try:
            pt, lo, hi = bootstrap_metric(accuracy, val_labels, preds)
            metrics["accuracy"] = pt
            metrics["accuracy_ci"] = [lo, hi]
        except Exception:
            pass
        try:
            proba_matrix = np.array(conformal.model.predict_proba(val_texts))
            pt, lo, hi = bootstrap_metric(auc_roc, val_labels, preds, label_proba=proba_matrix)
            metrics["auc_roc"] = pt
            metrics["auc_roc_ci"] = [lo, hi]
        except Exception:
            pass

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
                    hit["_id"]: hit["_source"]
                    for hit in res.get("hits", {}).get("hits", [])
                }
                for i, entry in zip(indices, batch_entries, strict=False):
                    src = id_to_src.get(str(entry.entry_id), {})
                    text_parts = [str(src[f]) for f in fields if src.get(f)]
                    if not text_parts:
                        fallback = src.get("text", "")
                        text_parts = [str(fallback)] if fallback else []
                    texts[i] = " ".join(text_parts) if text_parts else self._extract_entry_text(entry, fields)
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
                    pred_set = [str(classes[i]) for i in range(len(proba)) if entry_scores[i] <= threshold]
                else:
                    pred_set = [predicted_class] if predicted_class else []

                pending.append({
                    "entry_id": entry.id,
                    "label_id": ml_model.label_id,
                    "model_id": ml_model.id,
                    "version_id": version.id,
                    "value": predicted_class,
                    "score": score_map.get(entry.id),
                    "prediction_set": pred_set,
                })

            if len(pending) >= insert_chunk:
                bulk_append_model_predictions(pending)
                pending = []

            db.session.expire_all()

        if pending:
            bulk_append_model_predictions(pending)

    def _get_class_distribution(self, train_data: dict) -> dict:
        distribution: dict[int, int] = {}
        for _, label_idx in train_data.values():
            distribution[label_idx] = distribution.get(label_idx, 0) + 1
        return {str(k): v for k, v in distribution.items()}

    def get_next_al_entries(self, model_id: int, n: int = 10) -> list[int]:
        """Return the first n entry IDs from the active version's uncertainty cache."""
        version = self.registry.get_active_version(model_id)
        if version is None:
            raise ValueError(f"No active version found for model {model_id}")
        if version.cache_entries:
            return [item["id"] for item in version.cache_entries[:n]]
        return []
