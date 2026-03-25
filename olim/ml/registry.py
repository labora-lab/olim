"""
Model Registry for ML Models Management

This module provides CRUD operations for ML models and their versions.

The ModelRegistry is responsible for:
- Creating and managing ML model entries
- Managing model versions
- Activating/deactivating model versions
- Querying models with filters
"""

from __future__ import annotations

import re
from datetime import datetime

from sqlalchemy import and_, desc

from olim import db

from .models import MLModel, MLModelVersion


def _slugify(text: str) -> str:
    """Convert text to URL-friendly slug

    Args:
        text: Text to slugify

    Returns:
        Slugified text (lowercase, alphanumeric with hyphens)
    """
    # Convert to lowercase
    text = text.lower()
    # Replace spaces and underscores with hyphens
    text = re.sub(r"[\s_]+", "-", text)
    # Remove non-alphanumeric characters except hyphens
    text = re.sub(r"[^a-z0-9-]", "", text)
    # Remove multiple consecutive hyphens
    text = re.sub(r"-+", "-", text)
    # Strip leading/trailing hyphens
    return text.strip("-")


class ModelRegistry:
    """Registry for managing ML models and their versions

    Provides a centralized interface for CRUD operations on ML models
    and their versions, including version management and querying.
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
        subsample_config: dict | None = None,
        label_id: int | None = None,
        description: str | None = None,
    ) -> MLModel:
        """Create a new ML model

        Args:
            name: Human-readable model name
            project_id: ID of the associated project
            created_by: ID of the user creating the model
            algorithm: Model algorithm name (default: TfidfXGBoostClassifier)
            model_type: Type of model (default: classification)
            model_config: Model configuration dict
            training_config: Training configuration dict
            policy_type: Active learning policy type
            subsample_config: Subsampling configuration
            label_id: Optional link to Label for backward compatibility
            description: Optional model description

        Returns:
            Created MLModel instance

        Example:
            >>> registry = ModelRegistry()
            >>> model = registry.create_model(
            ...     name="Patient Classification",
            ...     project_id=1,
            ...     created_by=1,
            ...     algorithm="TfidfXGBoostClassifier",
            ... )
        """
        from olim.ml.models import MLModel

        # Generate unique slug from name
        base_slug = _slugify(name)
        slug = base_slug
        counter = 1

        # Ensure slug is unique
        while db.session.query(MLModel).filter_by(slug=slug).first() is not None:
            slug = f"{base_slug}-{counter}"
            counter += 1

        model = MLModel(
            slug=slug,
            name=name,
            description=description,
            project_id=project_id,
            label_id=label_id,
            model_type=model_type,
            algorithm=algorithm,
            model_config=model_config or {},
            training_config=training_config or {},
            policy_type=policy_type,
            subsample_config=subsample_config,
            status="draft",
            created=datetime.now(),
            created_by=created_by,
            is_deleted=False,
        )

        db.session.add(model)
        db.session.commit()

        return model

    @staticmethod
    def get_model(model_id: int) -> MLModel | None:
        """Get a model by ID

        Args:
            model_id: ID of the model to retrieve

        Returns:
            MLModel instance or None if not found
        """
        from olim.ml.models import MLModel

        return db.session.query(MLModel).filter_by(id=model_id, is_deleted=False).first()

    @staticmethod
    def get_model_by_slug(slug: str) -> MLModel | None:
        """Get a model by slug

        Args:
            slug: Slug of the model to retrieve

        Returns:
            MLModel instance or None if not found
        """
        from olim.ml.models import MLModel

        return db.session.query(MLModel).filter_by(slug=slug, is_deleted=False).first()

    @staticmethod
    def get_active_version(model_id: int) -> MLModelVersion | None:
        """Get the currently active version of a model

        Args:
            model_id: ID of the model

        Returns:
            Active MLModelVersion or None if no active version
        """
        from olim.ml.models import MLModelVersion

        return (
            db.session.query(MLModelVersion)
            .filter_by(model_id=model_id, is_active=True, is_deleted=False)
            .first()
        )

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
        """Create a new model version

        Args:
            model_id: ID of the parent model
            artifact_path: Path to stored model artifacts
            n_train_samples: Number of training samples
            n_val_samples: Number of validation samples
            metrics: Training/evaluation metrics dict
            created_by: ID of the user creating the version
            trained_at: Training completion timestamp
            training_duration: Time taken to train (seconds)
            class_distribution: Distribution of classes
            conformal_threshold: Threshold for conformal prediction
            cache_entries: Active learning cache entries
            auto_activate: Whether to activate this version automatically

        Returns:
            Created MLModelVersion instance
        """
        from olim.ml.models import MLModel, MLModelVersion

        # Get next version number
        last_version = (
            db.session.query(MLModelVersion)
            .filter_by(model_id=model_id)
            .order_by(desc(MLModelVersion.version))
            .first()
        )

        version_number = 1 if last_version is None else last_version.version + 1

        version = MLModelVersion(
            model_id=model_id,
            version=version_number,
            artifact_path=artifact_path,
            trained_at=trained_at or datetime.now(),
            training_duration=training_duration,
            n_train_samples=n_train_samples,
            n_val_samples=n_val_samples,
            class_distribution=class_distribution,
            metrics=metrics,
            conformal_threshold=conformal_threshold,
            cache_entries=cache_entries,
            is_active=False,  # Will be activated below if auto_activate=True
            created=datetime.now(),
            created_by=created_by,
            is_deleted=False,
        )

        db.session.add(version)
        db.session.flush()  # Get version.id before potential activation

        # Auto-activate if requested
        if auto_activate:
            ModelRegistry.activate_version(version.id)

        # Update model status to 'active' if first version
        model = db.session.query(MLModel).filter_by(id=model_id).first()
        if model and version_number == 1:
            model.status = "active"

        db.session.commit()

        return version

    @staticmethod
    def activate_version(version_id: int) -> MLModelVersion:
        """Activate a specific model version

        Deactivates all other versions of the same model.

        Args:
            version_id: ID of the version to activate

        Returns:
            Activated MLModelVersion instance

        Raises:
            ValueError: If version not found
        """
        from olim.ml.models import MLModelVersion

        version = db.session.query(MLModelVersion).filter_by(id=version_id).first()

        if version is None:
            raise ValueError(f"Version {version_id} not found")

        # Deactivate all other versions of the same model
        db.session.query(MLModelVersion).filter(
            and_(
                MLModelVersion.model_id == version.model_id,
                MLModelVersion.id != version_id,
            )
        ).update({"is_active": False})

        # Activate this version
        version.is_active = True
        db.session.commit()

        return version

    @staticmethod
    def list_models(
        *,
        project_id: int | None = None,
        status: str | None = None,
        label_id: int | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[MLModel]:
        """List models with optional filters

        Args:
            project_id: Filter by project
            status: Filter by status (draft, training, active, archived)
            label_id: Filter by associated label
            limit: Maximum number of results
            offset: Number of results to skip

        Returns:
            List of MLModel instances
        """
        from olim.ml.models import MLModel

        query = db.session.query(MLModel).filter_by(is_deleted=False)

        if project_id is not None:
            query = query.filter_by(project_id=project_id)

        if status is not None:
            query = query.filter_by(status=status)

        if label_id is not None:
            query = query.filter_by(label_id=label_id)

        return query.order_by(desc(MLModel.created)).limit(limit).offset(offset).all()

    @staticmethod
    def list_versions(
        model_id: int,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[MLModelVersion]:
        """List versions of a model

        Args:
            model_id: ID of the model
            limit: Maximum number of results
            offset: Number of results to skip

        Returns:
            List of MLModelVersion instances ordered by version desc
        """
        from olim.ml.models import MLModelVersion

        return (
            db.session.query(MLModelVersion)
            .filter_by(model_id=model_id, is_deleted=False)
            .order_by(desc(MLModelVersion.version))
            .limit(limit)
            .offset(offset)
            .all()
        )

    @staticmethod
    def update_model(
        model_id: int,
        **kwargs: dict,
    ) -> MLModel:
        """Update model fields

        Args:
            model_id: ID of the model to update
            **kwargs: Fields to update (name, description, model_config, etc.)

        Returns:
            Updated MLModel instance

        Raises:
            ValueError: If model not found
        """
        from olim.ml.models import MLModel

        model = db.session.query(MLModel).filter_by(id=model_id, is_deleted=False).first()

        if model is None:
            raise ValueError(f"Model {model_id} not found")

        # Update allowed fields
        allowed_fields = {
            "name",
            "description",
            "model_config",
            "training_config",
            "policy_type",
            "subsample_config",
            "status",
        }

        for key, value in kwargs.items():
            if key in allowed_fields:
                setattr(model, key, value)

        db.session.commit()

        return model

    @staticmethod
    def delete_model(model_id: int, deleted_by: int) -> None:
        """Soft delete a model

        Args:
            model_id: ID of the model to delete
            deleted_by: ID of the user deleting the model

        Raises:
            ValueError: If model not found
        """
        from olim.ml.models import MLModel

        model = db.session.query(MLModel).filter_by(id=model_id, is_deleted=False).first()

        if model is None:
            raise ValueError(f"Model {model_id} not found")

        model.is_deleted = True
        model.deleted = datetime.now()
        model.deleted_by = deleted_by

        db.session.commit()
