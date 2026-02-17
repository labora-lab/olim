"""
Celery tasks for ML model training

This module provides async tasks for ML model operations using Celery.
"""

from __future__ import annotations

from datetime import datetime

from celery import Task

from olim.celery_app import app
from olim.ml.services import MLModelService
from olim.settings import WORK_PATH


@app.task(bind=True, name="ml.train_model", track_progress=True)
def train_ml_model(self: Task, model_id: int, user_id: int, force_retrain: bool = False) -> dict:
    """Train ML model asynchronously

    Args:
        model_id: ID of model to train
        user_id: ID of user who triggered training
        force_retrain: Force retraining even if no new data

    Returns:
        Dictionary with version_id, version_number, metrics, model_id, config

    Raises:
        ValueError: If model not found
        RuntimeError: If training fails
    """
    # Initialize service
    service = MLModelService(WORK_PATH)

    # Train model
    version = service.train_model(model_id=model_id, user_id=user_id, force_retrain=force_retrain)

    # Return ML-specific metadata
    # This will be stored in CeleryTask.result by celery_app.py signals
    return {
        "model_id": model_id,
        "version_id": version.id,
        "version_number": version.version,
        "metrics": version.metrics,
        "n_train_samples": version.n_train_samples,
        "n_val_samples": version.n_val_samples,
        "config_snapshot": {
            "force_retrain": force_retrain,
            "user_id": user_id,
        },
    }


@app.task(name="ml.batch_predict", track_progress=True)
def batch_predict(model_id: int, texts: list[str], version_id: int | None = None) -> list[dict]:
    """Make batch predictions asynchronously

    Args:
        model_id: ID of model to use
        texts: List of input texts
        version_id: Specific version to use (None = active)

    Returns:
        List of prediction result dictionaries

    Raises:
        ValueError: If model or version not found
        RuntimeError: If prediction fails
    """
    service = MLModelService(WORK_PATH)

    # Make predictions
    results = service.predict_batch(model_id, texts, version_id)

    # Convert to dictionaries
    return [result.to_dict() for result in results]


@app.task(name="ml.cleanup_old_versions", track_progress=True)
def cleanup_old_versions(model_id: int, keep_last_n: int = 5) -> dict:
    """Clean up old model versions (keep last N)

    Args:
        model_id: ID of model
        keep_last_n: Number of recent versions to keep

    Returns:
        Dictionary with cleanup statistics
    """

    service = MLModelService(WORK_PATH)

    # Get all versions ordered by version number
    versions = service.list_versions(model_id, limit=1000)

    if len(versions) <= keep_last_n:
        return {
            "deleted_count": 0,
            "kept_count": len(versions),
            "message": "No cleanup needed",
        }

    # Keep last N versions
    versions_to_keep = versions[:keep_last_n]
    versions_to_delete = versions[keep_last_n:]

    deleted_count = 0

    for version in versions_to_delete:
        # Don't delete active version
        if version.is_active:
            continue

        try:
            # Delete artifacts from disk
            service.artifact_manager.delete_artifacts(model_id, version.version)

            # Soft delete version record
            version.is_deleted = True
            version.deleted = datetime.now()
            deleted_count += 1

        except Exception:
            # Continue on error
            continue

    from olim import db

    db.session.commit()

    return {
        "deleted_count": deleted_count,
        "kept_count": len(versions_to_keep),
        "message": f"Cleaned up {deleted_count} old versions",
    }


@app.task(name="ml.clear_prediction_cache", track_progress=True)
def clear_prediction_cache(version_id: int | None = None) -> dict:
    """Clear prediction cache

    Args:
        version_id: Specific version to clear (None = all)

    Returns:
        Cache statistics after clearing
    """
    service = MLModelService(WORK_PATH)
    return service.clear_prediction_cache(version_id)
