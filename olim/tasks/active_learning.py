from __future__ import annotations

from typing import TYPE_CHECKING, Any

from olim.entry_types.registry import get_entry_type_instance

from .. import app as flask_app, settings
from ..celery_app import app
from ..database import (
    get_entries_by_dataset,
    get_label,
    get_project,
    link_label_to_model,
    update_label,
)
from ..ml.models import MLModel
from ..ml.services import MLModelService

if TYPE_CHECKING:
    from ..database import Label

COMPOSITE_ID = "({dataset_id},{entry_id})"


def get_or_create_ml_model(label: Label, user_id: int) -> MLModel:
    """Get existing MLModel for label or create new one

    Args:
        label: Label instance
        user_id: User ID creating the model

    Returns:
        MLModel instance
    """
    service = MLModelService(settings.WORK_PATH)

    # Check if label already has MLModel
    if label.ml_model_id:
        model = service.get_model(label.ml_model_id)
        if model:
            return model

    # Create new MLModel from label configuration
    print(f"Creating new MLModel for Label {label.id}: {label.name}")
    model = service.create_model_for_label(
        label=label,
        user_id=user_id,
    )

    link_label_to_model(label.id, model.id)

    print(f"Created MLModel {model.id} for Label {label.id}")
    return model


def sync_label_from_version(label: Label) -> None:
    """Sync Label fields from active MLModelVersion for backward compatibility

    Updates label.metrics and label.cache from the active version.

    Args:
        label: Label instance to update
    """
    if not label.ml_model_id:
        return

    service = MLModelService(settings.WORK_PATH)
    version = service.get_active_version(label.ml_model_id)

    if not version:
        return

    updates: dict = {}
    if version.metrics:
        metrics_strs = []
        for key, value in version.metrics.items():
            if isinstance(value, float):
                metrics_strs.append(f"{key}: {value:.4f}")
            else:
                metrics_strs.append(f"{key}: {value}")
        updates["metrics"] = metrics_strs
    if version.cache_entries:
        updates["cache"] = version.cache_entries
    if updates:
        update_label(label.id, **updates)


def _update_label_in_context(label_id: int, **to_update: Any) -> None:  # noqa: ANN401
    """Update label fields within an app context (thin wrapper for Celery use)."""
    with flask_app.app_context():
        result = update_label(label_id, **to_update)
        if result is None:
            raise ValueError(f"Label {label_id} not found")


@app.task(bind=True, name="learner.train_model", track_progress=True)
def train_model(
    self,
    user_id: int,
    project_id: int | None = None,
    label_id: int | None = None,
    model_id: int | None = None,
    force_retrain: bool = False,
    training_overrides: dict | None = None,
    **__,
) -> dict[str, Any]:
    """Train ML model (supports both label-based and model-based training)

    Args:
        user_id: User ID triggering training
        project_id: Project ID (optional, for label-based training)
        label_id: Label ID (for active learning workflow)
        model_id: Model ID (for direct ML model training)
        force_retrain: Force retraining even if no new data

    Returns:
        Success status and metrics
    """
    with flask_app.app_context():
        service = MLModelService(settings.WORK_PATH)

        # Determine which model to train
        if model_id is not None:
            # Direct model training (from ML UI)
            model = service.get_model(model_id)
            if not model:
                raise ValueError(f"Model {model_id} not found")
            label = None
        elif label_id is not None:
            # Label-based training (from Active Learning)
            label = get_label(label_id)
            if not label:
                raise ValueError(f"Label {label_id} not found")
            # Get or create MLModel for this label
            model = get_or_create_ml_model(label, user_id)
        else:
            raise ValueError("Either label_id or model_id must be provided")

        # Train new version
        version = service.train_model(
            model_id=model.id,
            user_id=user_id,
            force_retrain=force_retrain,
            training_overrides=training_overrides,
        )

        # If training from label, sync metrics back
        if label is not None:
            sync_label_from_version(label)

        # Convert metrics for return (include conformal_threshold for early-stop)
        metrics = []
        if version.metrics:
            for key, value in version.metrics.items():
                if isinstance(value, float):
                    metrics.append(f"{key}: {value:.4f}")
                else:
                    metrics.append(f"{key}: {value}")
        if version.conformal_threshold is not None:
            metrics.append(f"conformal_threshold: {version.conformal_threshold:.4f}")

        return {
            "success": True,
            "metrics": metrics,
            "version_id": version.id,
            "model_id": model.id,
        }


@app.task(bind=True, name="learner.add_label_value", track_progress=False)
def add_label_value(
    self,
    project_id: int,
    label_id: int,
    user_id: int,
    dataset_id: int,
    entry_id: str,
    value: str,
    **__,
) -> dict[str, Any]:
    """Record label submission (no-op in new system - data already in DB)

    In the old system, this wrote to submissions.jsonl.
    In the new system, the label is already in the database via add_entry_label(),
    and training will pick it up automatically.

    Args:
        project_id: Project ID
        label_id: Label ID
        user_id: User ID
        dataset_id: Dataset ID
        entry_id: Entry ID
        value: Label value

    Returns:
        Success status
    """
    # Label already added to database by add_entry_label() in active_learning.py
    # Just log for debugging
    composite_id = COMPOSITE_ID.format(dataset_id=dataset_id, entry_id=entry_id)
    print(f"[add_label_value] Label {label_id}: {composite_id} = {value}")

    # Training will be triggered automatically by submit_label_value() in active_learning.py
    # based on label.training_counter

    return {"success": True}


@app.task(bind=True, name="learner.export_predictions", track_progress=True)
def export_predictions(
    self,
    project_id: int,
    label_id: int,
    user_id: int,
    alpha: float = 0.95,
    **__,
) -> dict[str, Any]:
    """Export predictions for all entries in project datasets

    Args:
        project_id: Project ID
        label_id: Label ID
        user_id: User ID
        alpha: Confidence threshold (for conformal prediction)

    Returns:
        Success status and predictions dictionary
    """
    with flask_app.app_context():
        label = get_label(label_id)
        if not label:
            raise ValueError(f"Label {label_id} not found")

        project = get_project(project_id)
        if not project:
            raise ValueError(f"Project {project_id} not found")

        # Get or create MLModel
        model = get_or_create_ml_model(label, user_id)

        # Get all entries from project datasets
        all_entries = []
        for dataset in project.datasets:
            all_entries.extend(get_entries_by_dataset(dataset.id))

        print(f"Exporting predictions for {len(all_entries)} entries")

        # Get texts from entries
        texts_map = {}
        for entry in all_entries:
            composite_id = COMPOSITE_ID.format(dataset_id=entry.dataset_id, entry_id=entry.entry_id)

            # Extract text from entry using entry type system
            entry_type_instance = get_entry_type_instance(entry.type, entry.dataset_id)
            if entry_type_instance:
                df = entry_type_instance.extract_texts(entry.entry_id, dataset_id=entry.dataset_id)
                if not df.empty:
                    # Get label fields if specified
                    fields = []
                    if label.learner_parameters and "fields" in label.learner_parameters:
                        fields = label.learner_parameters["fields"]

                    # Extract text
                    text_parts = []
                    if fields:
                        for field in fields:
                            if field in df.columns:
                                text_parts.append(str(df[field].iloc[0]))
                    else:
                        # Use all text columns
                        for col in df.columns:
                            if col != "entry_id" and df[col].dtype == object:
                                text_parts.append(str(df[col].iloc[0]))

                    text = " ".join(text_parts) if text_parts else str(entry.entry_id)
                else:
                    text = str(entry.entry_id)
            else:
                text = str(entry.entry_id)

            texts_map[composite_id] = text

        # Make batch predictions
        service = MLModelService(settings.WORK_PATH)
        texts = list(texts_map.values())
        composite_ids = list(texts_map.keys())

        if not texts:
            return {"success": True, "predictions": {}}

        results = service.predict_batch(model.id, texts)

        # Convert results to old format
        # Old format: {composite_id: [predicted_class] or [class1, class2, ...]}
        predictions = {}
        for composite_id, result in zip(composite_ids, results, strict=False):
            if result.prediction_set:
                # Conformal prediction - return set
                predictions[composite_id] = result.prediction_set
            elif result.predicted_class:
                # Single prediction
                predictions[composite_id] = [result.predicted_class]
            else:
                # No prediction
                predictions[composite_id] = []

        # Update label cache with latest from version
        sync_label_from_version(label)

        return {"success": True, "predictions": predictions}
