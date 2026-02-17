"""
Database models for ML Models Management System

This module defines the core database models for the ML models management system:
- MLModel: Central model registry
- MLModelVersion: Version tracking with artifacts
- MLModelPrediction: Prediction audit trail
- MLTrainingJob: Training job tracking
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Mapped

from olim import db
from olim.database import CreationControl, Entry, Label, Project


class MLModel(db.Model, CreationControl):
    """Central model registry

    Stores ML model configurations and metadata. Each model can have multiple
    versions and is associated with a project. Models can optionally be linked
    to a Label for backward compatibility with the active learning system.

    Attributes:
        id: Primary key
        slug: User-friendly URL-safe identifier
        name: Human-readable model name
        description: Optional detailed description
        project_id: Associated project
        label_id: Optional link to Label table for backward compatibility
        model_type: Type of model ("classification", "regression")
        algorithm: Algorithm name (e.g., "TfidfXGBoostClassifier")
        model_config: JSON configuration for model initialization
        training_config: JSON configuration for training parameters
        policy_type: Active learning policy type (e.g., "ConformalUnsertantyPolicy")
        subsample_config: JSON configuration for subsampling in active learning
        status: Current model status ("draft", "training", "active", "archived")
    """

    __tablename__ = "ml_models"

    # Identity
    id: Mapped[int] = db.mapped_column(primary_key=True)
    slug: Mapped[str] = db.mapped_column(unique=True, nullable=False, index=True)
    name: Mapped[str] = db.mapped_column(nullable=False)
    description: Mapped[str | None] = db.mapped_column(db.Text, nullable=True)

    # Project association
    project_id: Mapped[int] = db.mapped_column(db.ForeignKey("projects.id"), nullable=False)
    label_id: Mapped[int | None] = db.mapped_column(
        db.ForeignKey("labels.id"), nullable=True, index=True
    )

    # Model type and algorithm
    model_type: Mapped[str] = db.mapped_column(
        nullable=False, default="classification"
    )  # "classification", "regression"
    algorithm: Mapped[str] = db.mapped_column(
        nullable=False, default="TfidfXGBoostClassifier"
    )  # Model class name

    # Configuration (JSON)
    model_config: Mapped[dict] = db.mapped_column(db.JSON, nullable=False, default=dict)
    training_config: Mapped[dict] = db.mapped_column(db.JSON, nullable=False, default=dict)

    # Active Learning specific
    policy_type: Mapped[str | None] = db.mapped_column(
        nullable=True
    )  # "ConformalUnsertantyPolicy", etc.
    subsample_config: Mapped[dict | None] = db.mapped_column(db.JSON, nullable=True)

    # Status
    status: Mapped[str] = db.mapped_column(
        nullable=False, default="draft", index=True
    )  # "draft", "training", "active", "archived"

    # Relationships
    versions: Mapped[list[MLModelVersion]] = db.relationship(
        back_populates="model", cascade="all, delete-orphan", lazy="dynamic"
    )
    predictions: Mapped[list[MLModelPrediction]] = db.relationship(
        back_populates="model", lazy="dynamic"
    )
    training_jobs: Mapped[list[MLTrainingJob]] = db.relationship(
        back_populates="model", lazy="dynamic"
    )

    # Foreign key relationships
    project: Mapped[Project] = db.relationship(  # type: ignore
        foreign_keys=[project_id], viewonly=True
    )
    label: Mapped[Label] = db.relationship(  # type: ignore
        foreign_keys=[label_id], viewonly=True
    )

    def __repr__(self) -> str:
        return f"<MLModel {self.slug} ({self.algorithm})>"

    def get_active_version(self) -> MLModelVersion | None:
        """Get the currently active version of this model"""
        return self.versions.filter_by(is_active=True).first()

    def to_dict(self) -> dict:
        """Convert model to dictionary representation"""
        active_version = self.get_active_version()
        return {
            "id": self.id,
            "slug": self.slug,
            "name": self.name,
            "description": self.description,
            "project_id": self.project_id,
            "label_id": self.label_id,
            "model_type": self.model_type,
            "algorithm": self.algorithm,
            "model_config": self.model_config,
            "training_config": self.training_config,
            "policy_type": self.policy_type,
            "subsample_config": self.subsample_config,
            "status": self.status,
            "active_version": active_version.version if active_version else None,
            "created": self.created.isoformat() if self.created else None,
            "created_by": self.created_by,
        }


class MLModelVersion(db.Model, CreationControl):
    """Version tracking with artifacts

    Each time a model is trained, a new version is created. Versions store
    training metadata, metrics, and references to artifact files. Only one
    version per model can be active at a time.

    Attributes:
        id: Primary key
        model_id: Foreign key to MLModel
        version: Version number (auto-incremented per model)
        artifact_path: Path to stored model artifacts (relative to WORK_PATH)
        trained_at: Timestamp when training completed
        training_duration: Time taken to train in seconds
        n_train_samples: Number of training samples used
        n_val_samples: Number of validation samples used
        class_distribution: JSON with class distribution stats
        metrics: JSON with evaluation metrics (accuracy, precision, etc.)
        conformal_threshold: Threshold for conformal prediction
        cache_entries: JSON with cached active learning entries
        is_active: Whether this is the currently active version
    """

    __tablename__ = "ml_model_versions"
    __table_args__ = (
        db.UniqueConstraint("model_id", "version", name="uq_model_version"),
        db.Index("ix_ml_model_versions_active", "model_id", "is_active"),
        db.Index("ix_ml_model_versions_trained", "trained_at"),
    )

    # Identity
    id: Mapped[int] = db.mapped_column(primary_key=True)
    model_id: Mapped[int] = db.mapped_column(db.ForeignKey("ml_models.id"), nullable=False)
    version: Mapped[int] = db.mapped_column(nullable=False)

    # Artifact storage (path relative to WORK_PATH)
    artifact_path: Mapped[str] = db.mapped_column(nullable=False)

    # Training metadata
    trained_at: Mapped[datetime] = db.mapped_column(nullable=False)
    training_duration: Mapped[float | None] = db.mapped_column(nullable=True)

    # Dataset statistics
    n_train_samples: Mapped[int] = db.mapped_column(nullable=False)
    n_val_samples: Mapped[int] = db.mapped_column(nullable=False)
    class_distribution: Mapped[dict | None] = db.mapped_column(db.JSON, nullable=True)

    # Metrics (accuracy, precision, recall, etc.)
    metrics: Mapped[dict] = db.mapped_column(db.JSON, nullable=False, default=dict)

    # Conformal prediction
    conformal_threshold: Mapped[float | None] = db.mapped_column(nullable=True)

    # Active Learning cache
    cache_entries: Mapped[list | None] = db.mapped_column(db.JSON, nullable=True)

    # Status
    is_active: Mapped[bool] = db.mapped_column(default=False, nullable=False)

    # Relationships
    model: Mapped[MLModel] = db.relationship(back_populates="versions")
    predictions: Mapped[list[MLModelPrediction]] = db.relationship(
        back_populates="version", lazy="dynamic"
    )

    def __repr__(self) -> str:
        return f"<MLModelVersion {self.model_id}:v{self.version}>"

    def to_dict(self) -> dict:
        """Convert version to dictionary representation"""
        return {
            "id": self.id,
            "model_id": self.model_id,
            "version": self.version,
            "artifact_path": self.artifact_path,
            "trained_at": self.trained_at.isoformat() if self.trained_at else None,
            "training_duration": self.training_duration,
            "n_train_samples": self.n_train_samples,
            "n_val_samples": self.n_val_samples,
            "class_distribution": self.class_distribution,
            "metrics": self.metrics,
            "conformal_threshold": self.conformal_threshold,
            "is_active": self.is_active,
            "created": self.created.isoformat() if self.created else None,
            "created_by": self.created_by,
        }


class MLModelPrediction(db.Model):
    """Prediction audit trail

    Records all predictions made by ML models for audit and analysis purposes.
    Can be linked to Entry records for tracking predictions within the annotation
    workflow.

    Attributes:
        id: Primary key
        model_id: Foreign key to MLModel
        version_id: Foreign key to MLModelVersion
        input_text: The input text that was predicted
        predicted_class: The predicted class label
        prediction_set: List of possible classes (conformal prediction)
        confidence: Confidence score for the prediction
        class_probabilities: JSON with probabilities for each class
        predicted_at: Timestamp when prediction was made
        external_request_id: Optional external request identifier for tracking
        entry_id: Optional link to Entry record
    """

    __tablename__ = "ml_model_predictions"
    __table_args__ = (
        db.Index("ix_ml_predictions_model_version", "model_id", "version_id"),
        db.Index("ix_ml_predictions_predicted_at", "predicted_at"),
        db.Index("ix_ml_predictions_entry", "entry_id"),
    )

    # Identity
    id: Mapped[int] = db.mapped_column(primary_key=True)
    model_id: Mapped[int] = db.mapped_column(db.ForeignKey("ml_models.id"), nullable=False)
    version_id: Mapped[int] = db.mapped_column(
        db.ForeignKey("ml_model_versions.id"), nullable=False
    )

    # Input/Output
    input_text: Mapped[str] = db.mapped_column(db.Text, nullable=False)
    predicted_class: Mapped[str | None] = db.mapped_column(nullable=True)
    prediction_set: Mapped[list | None] = db.mapped_column(db.JSON, nullable=True)
    confidence: Mapped[float | None] = db.mapped_column(nullable=True)
    class_probabilities: Mapped[dict | None] = db.mapped_column(db.JSON, nullable=True)

    # Metadata
    predicted_at: Mapped[datetime] = db.mapped_column(nullable=False)
    external_request_id: Mapped[str | None] = db.mapped_column(nullable=True, index=True)
    entry_id: Mapped[int | None] = db.mapped_column(db.ForeignKey("entries.id"), nullable=True)

    # Relationships
    model: Mapped[MLModel] = db.relationship(back_populates="predictions")
    version: Mapped[MLModelVersion] = db.relationship(back_populates="predictions")
    entry: Mapped[Entry] = db.relationship(foreign_keys=[entry_id], viewonly=True)  # type: ignore

    def __repr__(self) -> str:
        return f"<MLModelPrediction {self.id} -> {self.predicted_class}>"

    def to_dict(self) -> dict:
        """Convert prediction to dictionary representation"""
        return {
            "id": self.id,
            "model_id": self.model_id,
            "version_id": self.version_id,
            "input_text": self.input_text,
            "predicted_class": self.predicted_class,
            "prediction_set": self.prediction_set,
            "confidence": self.confidence,
            "class_probabilities": self.class_probabilities,
            "predicted_at": self.predicted_at.isoformat() if self.predicted_at else None,
            "external_request_id": self.external_request_id,
            "entry_id": self.entry_id,
        }


class MLTrainingJob(db.Model, CreationControl):
    """Training job tracking

    Tracks the status and progress of model training jobs. Uses Celery task IDs
    as primary keys for easy integration with the existing task tracking system.

    Attributes:
        id: Celery task ID (primary key)
        model_id: Foreign key to MLModel
        status: Job status ("queued", "running", "completed", "failed")
        started_at: Timestamp when training started
        completed_at: Timestamp when training completed
        version_id: Foreign key to created MLModelVersion (set on completion)
        error_message: Error details if training failed
        config_snapshot: JSON snapshot of configuration used for this training run
    """

    __tablename__ = "ml_training_jobs"
    __table_args__ = (
        db.Index("ix_ml_training_jobs_model", "model_id"),
        db.Index("ix_ml_training_jobs_status", "status"),
    )

    # Identity (using Celery task ID)
    id: Mapped[str] = db.mapped_column(db.String(36), primary_key=True)
    model_id: Mapped[int] = db.mapped_column(db.ForeignKey("ml_models.id"), nullable=False)

    # Status tracking
    status: Mapped[str] = db.mapped_column(
        nullable=False, default="queued"
    )  # "queued", "running", "completed", "failed"
    started_at: Mapped[datetime | None] = db.mapped_column(nullable=True)
    completed_at: Mapped[datetime | None] = db.mapped_column(nullable=True)

    # Results
    version_id: Mapped[int | None] = db.mapped_column(
        db.ForeignKey("ml_model_versions.id"), nullable=True
    )
    error_message: Mapped[str | None] = db.mapped_column(db.Text, nullable=True)

    # Configuration snapshot (for reproducibility)
    config_snapshot: Mapped[dict] = db.mapped_column(db.JSON, nullable=False, default=dict)

    # Relationships
    model: Mapped[MLModel] = db.relationship(back_populates="training_jobs")
    version: Mapped[MLModelVersion] = db.relationship(  # type: ignore
        foreign_keys=[version_id], viewonly=True
    )

    def __repr__(self) -> str:
        return f"<MLTrainingJob {self.id} ({self.status})>"

    def to_dict(self) -> dict:
        """Convert training job to dictionary representation"""
        return {
            "id": self.id,
            "model_id": self.model_id,
            "status": self.status,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "version_id": self.version_id,
            "error_message": self.error_message,
            "config_snapshot": self.config_snapshot,
            "created": self.created.isoformat() if self.created else None,
            "created_by": self.created_by,
        }
