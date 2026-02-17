"""
ML Model Service - High-level facade for ML operations

This service combines all ML components and provides a simple,
unified interface for common operations.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from olim import db
from olim.ml.artifacts import ArtifactManager
from olim.ml.models import MLModel, MLModelPrediction, MLModelVersion, MLTrainingJob
from olim.ml.orchestrator import TrainingOrchestrator
from olim.ml.prediction import PredictionEngine, PredictionResult
from olim.ml.registry import ModelRegistry

if TYPE_CHECKING:
    from olim.database import Label


class MLModelService:
    """High-level service for ML model operations

    Provides a unified interface combining:
    - ModelRegistry (CRUD)
    - TrainingOrchestrator (training)
    - PredictionEngine (inference)
    - ArtifactManager (storage)
    """

    def __init__(self, work_path: Path | str) -> None:
        """Initialize ML Model Service

        Args:
            work_path: Base path for model artifacts (e.g., WORK_PATH)
        """
        self.work_path = Path(work_path)
        self.registry = ModelRegistry()
        self.orchestrator = TrainingOrchestrator(self.work_path)
        self.prediction_engine = PredictionEngine(self.work_path)
        self.artifact_manager = ArtifactManager(self.work_path / "ml_models")

    def create_model_for_label(
        self,
        label: Label,
        user_id: int,
        algorithm: str = "TfidfXGBoostClassifier",
    ) -> MLModel:
        """Create ML model for a label (backward compatibility)

        Args:
            label: Label instance to create model for
            user_id: ID of user creating the model
            algorithm: Algorithm to use

        Returns:
            Created MLModel instance
        """
        # Extract configuration from label.learner_parameters
        learner_params = label.learner_parameters or {}

        model_config = learner_params.get("model_config", {})
        training_config = learner_params.get("training_config", {})
        policy_type = learner_params.get("policy_type")
        subsample_config = learner_params.get("subsample_size")

        # Create model
        model = self.registry.create_model(
            name=f"{label.name} Model",
            project_id=label.project_id,
            created_by=user_id,
            algorithm=algorithm,
            model_config=model_config,
            training_config=training_config,
            policy_type=policy_type,
            subsample_config=subsample_config,
            label_id=label.id,
            description=f"ML model for label: {label.name}",
        )

        # Link model to label
        label.ml_model_id = model.id
        db.session.commit()

        return model

    def get_model(self, model_id: int) -> MLModel | None:
        """Get model by ID

        Args:
            model_id: ID of the model

        Returns:
            MLModel instance or None
        """
        return self.registry.get_model(model_id)

    def get_model_by_label(self, label_id: int) -> MLModel | None:
        """Get model associated with a label

        Args:
            label_id: ID of the label

        Returns:
            MLModel instance or None
        """
        models = self.registry.list_models(label_id=label_id, limit=1)
        return models[0] if models else None

    def list_models(
        self,
        project_id: int | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[MLModel]:
        """List models with filters

        Args:
            project_id: Filter by project
            status: Filter by status
            limit: Maximum results

        Returns:
            List of MLModel instances
        """
        return self.registry.list_models(project_id=project_id, status=status, limit=limit)

    def update_model(self, model_id: int, **kwargs: dict) -> MLModel:
        """Update model configuration

        Args:
            model_id: ID of model to update
            **kwargs: Fields to update

        Returns:
            Updated MLModel instance
        """
        return self.registry.update_model(model_id, **kwargs)

    def train_model(
        self,
        model_id: int,
        user_id: int,
        force_retrain: bool = False,
    ) -> MLModelVersion:
        """Train a new version of the model

        Args:
            model_id: ID of model to train
            user_id: ID of user triggering training
            force_retrain: Force retraining even if no new data

        Returns:
            Created MLModelVersion instance

        Raises:
            ValueError: If model not found
            RuntimeError: If training fails
        """
        return self.orchestrator.train_new_version(
            model_id=model_id, user_id=user_id, force_retrain=force_retrain
        )

    def get_training_job(self, job_id: str) -> MLTrainingJob | None:
        """Get training job by ID

        Args:
            job_id: Training job ID (Celery task ID)

        Returns:
            MLTrainingJob instance or None
        """
        return db.session.query(MLTrainingJob).filter_by(id=job_id).first()

    def list_training_jobs(
        self, model_id: int | None = None, limit: int = 50
    ) -> list[MLTrainingJob]:
        """List training jobs

        Args:
            model_id: Filter by model ID
            limit: Maximum results

        Returns:
            List of MLTrainingJob instances
        """
        query = db.session.query(MLTrainingJob)

        if model_id is not None:
            query = query.filter_by(model_id=model_id)

        return query.order_by(MLTrainingJob.created.desc()).limit(limit).all()

    def get_version(self, version_id: int) -> MLModelVersion | None:
        """Get model version by ID

        Args:
            version_id: Version ID

        Returns:
            MLModelVersion instance or None
        """
        return db.session.query(MLModelVersion).filter_by(id=version_id).first()

    def get_active_version(self, model_id: int) -> MLModelVersion | None:
        """Get active version of a model

        Args:
            model_id: Model ID

        Returns:
            Active MLModelVersion or None
        """
        return self.registry.get_active_version(model_id)

    def list_versions(self, model_id: int, limit: int = 20) -> list[MLModelVersion]:
        """List versions of a model

        Args:
            model_id: Model ID
            limit: Maximum results

        Returns:
            List of MLModelVersion instances
        """
        return self.registry.list_versions(model_id, limit=limit)

    def activate_version(self, version_id: int) -> MLModelVersion:
        """Activate a specific version

        Args:
            version_id: Version ID to activate

        Returns:
            Activated MLModelVersion instance
        """
        return self.registry.activate_version(version_id)

    def get_model_metrics(self, model_id: int) -> dict | None:
        """Get metrics from active version

        Args:
            model_id: Model ID

        Returns:
            Metrics dictionary or None
        """
        version = self.get_active_version(model_id)
        return version.metrics if version else None

    def predict(
        self,
        model_id: int,
        text: str,
        version_id: int | None = None,
    ) -> PredictionResult:
        """Make a single prediction

        Args:
            model_id: Model ID
            text: Input text
            version_id: Specific version (None = active)

        Returns:
            PredictionResult instance
        """
        return self.prediction_engine.predict_single(model_id, text, version_id)

    def predict_batch(
        self,
        model_id: int,
        texts: list[str],
        version_id: int | None = None,
    ) -> list[PredictionResult]:
        """Make batch predictions

        Args:
            model_id: Model ID
            texts: List of input texts
            version_id: Specific version (None = active)

        Returns:
            List of PredictionResult instances
        """
        return self.prediction_engine.predict_batch(model_id, texts, version_id)

    def store_prediction(
        self,
        model_id: int,
        version_id: int,
        input_text: str,
        result: PredictionResult,
        entry_id: int | None = None,
        external_request_id: str | None = None,
    ) -> MLModelPrediction:
        """Store prediction in database for audit trail

        Args:
            model_id: Model ID
            version_id: Version ID used
            input_text: Input text
            result: PredictionResult instance
            entry_id: Optional entry ID
            external_request_id: Optional external request ID

        Returns:
            Created MLModelPrediction instance
        """
        prediction = MLModelPrediction(
            model_id=model_id,
            version_id=version_id,
            input_text=input_text,
            predicted_class=result.predicted_class,
            prediction_set=result.prediction_set,
            confidence=result.confidence,
            class_probabilities=result.probabilities,
            predicted_at=datetime.now(),
            external_request_id=external_request_id,
            entry_id=entry_id,
        )

        db.session.add(prediction)
        db.session.commit()

        return prediction

    def get_next_entries(self, model_id: int, n: int = 10) -> list[int]:
        """Get next entries for active learning

        Args:
            model_id: Model ID
            n: Number of entries to retrieve

        Returns:
            List of entry IDs to annotate
        """
        return self.orchestrator.get_next_al_entries(model_id, n)

    def get_artifact_info(self, model_id: int, version: int) -> dict:
        """Get artifact storage information

        Args:
            model_id: Model ID
            version: Version number

        Returns:
            Dictionary with path and size information
        """
        path = self.artifact_manager.get_model_path(model_id, version)
        size = self.artifact_manager.get_artifact_size(model_id, version)

        return {
            "path": str(path),
            "size_bytes": size,
            "size_mb": round(size / (1024 * 1024), 2),
            "exists": path.exists(),
        }

    def clear_prediction_cache(
        self, version_id: int | None = None
    ) -> dict[str, int | list[int] | dict[int, int]]:
        """Clear prediction cache

        Args:
            version_id: Specific version to clear, or None for all

        Returns:
            Cache statistics after clearing
        """
        self.prediction_engine.clear_cache(version_id)
        return self.prediction_engine.get_cache_stats()

    def get_cache_stats(self) -> dict[str, int | list[int] | dict[int, int]]:
        """Get prediction cache statistics

        Returns:
            Dictionary with cache statistics
        """
        return self.prediction_engine.get_cache_stats()
