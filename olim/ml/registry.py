"""
Model Registry for ML Models Management

This module provides CRUD operations for ML models and their versions.
All database operations are delegated to olim/database.py.
"""

from __future__ import annotations

from datetime import datetime

from olim.database import (
    activate_ml_version,
    delete_ml_model,
    get_active_ml_version,
    get_ml_model,
    get_ml_model_by_slug,
    get_ml_models,
    get_ml_version,
    get_ml_versions,
    new_ml_model,
    new_ml_version,
    update_ml_model,
)

from .models import MLModel, MLModelVersion


class ModelRegistry:
    """Registry for managing ML models and their versions.

    Thin wrapper — all SQL lives in olim/database.py.
    """

    @staticmethod
    def create_model(
        *,
        name: str,
        project_id: int,
        created_by: int,
        algorithm: str = "TfidfXGBoostClassifier",
        model_type: str = "classification",
        model_config: dict | None = None,
        training_config: dict | None = None,
        policy_type: str | None = None,
        subsample_config: dict | list | None = None,
        label_id: int | None = None,
        description: str | None = None,
    ) -> MLModel:
        return new_ml_model(
            name=name,
            project_id=project_id,
            created_by=created_by,
            algorithm=algorithm,
            model_type=model_type,
            model_config=model_config,
            training_config=training_config,
            policy_type=policy_type,
            subsample_config=subsample_config,
            label_id=label_id,
            description=description,
        )

    @staticmethod
    def get_model(model_id: int) -> MLModel | None:
        return get_ml_model(model_id)

    @staticmethod
    def get_model_by_slug(slug: str) -> MLModel | None:
        return get_ml_model_by_slug(slug)

    @staticmethod
    def get_active_version(model_id: int) -> MLModelVersion | None:
        return get_active_ml_version(model_id)

    @staticmethod
    def create_version(
        *,
        model_id: int,
        artifact_path: str,
        n_train_samples: int,
        n_val_samples: int,
        metrics: dict,
        created_by: int,
        trained_at: datetime | None = None,
        training_duration: float | None = None,
        class_distribution: dict | None = None,
        conformal_threshold: float | None = None,
        cache_entries: list | None = None,
        auto_activate: bool = True,
    ) -> MLModelVersion:
        return new_ml_version(
            model_id=model_id,
            artifact_path=artifact_path,
            n_train_samples=n_train_samples,
            n_val_samples=n_val_samples,
            metrics=metrics,
            created_by=created_by,
            trained_at=trained_at,
            training_duration=training_duration,
            class_distribution=class_distribution,
            conformal_threshold=conformal_threshold,
            cache_entries=cache_entries,
            auto_activate=auto_activate,
        )

    @staticmethod
    def activate_version(version_id: int) -> MLModelVersion:
        return activate_ml_version(version_id)

    @staticmethod
    def list_models(
        *,
        project_id: int | None = None,
        status: str | None = None,
        label_id: int | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[MLModel]:
        return get_ml_models(
            project_id=project_id,
            status=status,
            label_id=label_id,
            limit=limit,
            offset=offset,
        )

    @staticmethod
    def list_versions(
        model_id: int,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[MLModelVersion]:
        return get_ml_versions(model_id, limit=limit, offset=offset)

    @staticmethod
    def update_model(model_id: int, **kwargs: dict) -> MLModel:
        return update_ml_model(model_id, **kwargs)

    @staticmethod
    def delete_model(model_id: int, deleted_by: int) -> None:
        delete_ml_model(model_id, deleted_by)

    @staticmethod
    def get_version(version_id: int) -> MLModelVersion | None:
        return get_ml_version(version_id)
