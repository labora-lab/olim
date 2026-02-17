"""
Training Orchestrator for ML Models

This module orchestrates the complete training lifecycle:
1. Load model configuration
2. Prepare training data
3. Train the model using ActiveLearningBackend
4. Save artifacts via ArtifactManager
5. Create and activate new MLModelVersion
6. Update model metrics
"""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from olim import db
from olim.learner.public_api import AVAILABLE_MODELS, ActiveLearningBackend
from olim.ml.artifacts import ArtifactManager
from olim.ml.registry import ModelRegistry

if TYPE_CHECKING:
    from olim.database import Entry, Label
    from olim.ml.models import MLModel, MLModelVersion


class TrainingOrchestrator:
    """Orchestrator for ML model training lifecycle

    Manages the complete training process from data preparation to
    artifact storage and version management.
    """

    def __init__(self, work_path: Path | str) -> None:
        """Initialize TrainingOrchestrator

        Args:
            work_path: Base path for storing artifacts (e.g., WORK_PATH)
        """
        self.work_path = Path(work_path)
        self.artifact_manager = ArtifactManager(self.work_path / "ml_models")
        self.registry = ModelRegistry()

    def train_new_version(
        self,
        model_id: int,
        user_id: int,
        force_retrain: bool = False,
    ) -> MLModelVersion:
        """Train a new version of the model

        Args:
            model_id: ID of the MLModel to train
            user_id: ID of the user triggering training
            force_retrain: Force retraining even if no new data

        Returns:
            Created MLModelVersion instance

        Raises:
            ValueError: If model not found or invalid configuration
            RuntimeError: If training fails
        """
        # Get model from registry
        model = self.registry.get_model(model_id)
        if model is None:
            raise ValueError(f"Model {model_id} not found")

        # Update model status to 'training'
        model.status = "training"
        db.session.commit()

        start_time = time.time()

        try:
            # Prepare training data
            train_data, val_data, fields = self._prepare_training_data(model)

            if not train_data:
                raise ValueError("No training data available")

            # Initialize ActiveLearningBackend
            learner = self._initialize_learner(model, train_data, val_data, fields)

            # Train the model
            learner.train()

            # Calculate training duration
            training_duration = time.time() - start_time

            # Get next version number
            last_version = self.registry.get_active_version(model_id)
            version_number = 1 if last_version is None else last_version.version + 1

            # Save artifacts
            artifact_path = self.artifact_manager.save_artifacts(
                model_id=model_id,
                version=version_number,
                learner=learner,
                fields=fields,
            )

            # Extract metrics
            metrics = self._extract_metrics(learner)

            # Get class distribution
            class_distribution = self._get_class_distribution(train_data)

            # Get conformal threshold if available
            conformal_threshold = None
            if hasattr(learner, "_policy") and learner._policy is not None:
                if hasattr(learner._policy, "threshold"):
                    conformal_threshold = float(learner._policy.threshold)

            # Get cache entries for active learning
            cache_entries = learner._cached_subsample if learner._cached_subsample else None

            # Create new version
            version = self.registry.create_version(
                model_id=model_id,
                artifact_path=str(artifact_path),
                n_train_samples=len(train_data),
                n_val_samples=len(val_data),
                metrics=metrics,
                created_by=user_id,
                trained_at=datetime.now(),
                training_duration=training_duration,
                class_distribution=class_distribution,
                conformal_threshold=conformal_threshold,
                cache_entries=cache_entries,
                auto_activate=True,
            )

            # Update model status to 'active'
            model.status = "active"
            db.session.commit()

            return version

        except Exception as e:
            # Rollback and update status on failure
            model.status = "draft"
            db.session.commit()
            raise RuntimeError(f"Training failed: {e}") from e

    def _prepare_training_data(
        self, model: MLModel
    ) -> tuple[dict[int, tuple[str, int]], dict[int, tuple[str, int]], list[str]]:
        """Prepare training and validation data from Label

        Args:
            model: MLModel instance

        Returns:
            Tuple of (train_data, val_data, fields)
        """
        # If model is linked to a label, use label data
        if model.label_id is not None:
            from olim.database import Label, LabelEntry

            label = db.session.query(Label).filter_by(id=model.label_id).first()

            if label is None:
                raise ValueError(f"Label {model.label_id} not found")

            # Get label entries with values
            label_entries = (
                db.session.query(LabelEntry)
                .filter(LabelEntry.label_id == label.id, LabelEntry.value.isnot(None))
                .all()
            )

            if not label_entries:
                raise ValueError(f"No labeled data found for label {label.id}")

            # Get fields from label settings or model config
            fields = self._get_fields_from_label(label)

            # Build dataset
            train_data = {}
            val_data = {}

            # Get label value encoder mapping
            label_values = sorted({le.value for le in label_entries if le.value is not None})
            value_to_idx = {val: idx for idx, val in enumerate(label_values)}

            for label_entry in label_entries:
                entry = label_entry.entry

                # Get entry text based on fields
                text = self._extract_entry_text(entry, fields)

                # Encode label value
                label_idx = value_to_idx[label_entry.value]

                # Add to train_data (80/20 split can be handled by ActiveLearningBackend)
                train_data[entry.id] = (text, label_idx)

            # ActiveLearningBackend will handle train/val split internally
            # For now, return empty val_data
            return train_data, val_data, fields

        else:
            # Model not linked to label - would need custom data loading logic
            raise ValueError(
                "Model is not linked to a label. Custom data loading not yet implemented."
            )

    def _get_fields_from_label(self, label: Label) -> list[str]:
        """Extract fields from label configuration

        Args:
            label: Label instance

        Returns:
            List of field names to use for training
        """
        # Check label learner_parameters
        if label.learner_parameters and "fields" in label.learner_parameters:
            return label.learner_parameters["fields"]

        # Default to all text fields from entry type
        # This is a simplified version - real implementation would inspect entry schema
        return ["text"]

    def _extract_entry_text(self, entry: Entry, fields: list[str]) -> str:
        """Extract text from entry based on fields

        Args:
            entry: Entry instance
            fields: List of field names to extract

        Returns:
            Concatenated text from specified fields
        """
        from olim.entry_types.registry import get_entry_type_instance

        # Get entry type instance
        entry_type_instance = get_entry_type_instance(entry.type, entry.dataset_id)

        if entry_type_instance is None:
            # Fallback to entry_id if entry type not found
            return str(entry.entry_id)

        # Extract texts using entry type system
        df = entry_type_instance.extract_texts(entry.entry_id, dataset_id=entry.dataset_id)

        if df.empty:
            return str(entry.entry_id)

        # Concatenate specified fields
        text_parts = []
        for field in fields:
            if field in df.columns:
                text_parts.append(str(df[field].iloc[0]))

        # If no fields found, use all text columns
        if not text_parts:
            for col in df.columns:
                if col != "entry_id" and df[col].dtype == object:
                    text_parts.append(str(df[col].iloc[0]))

        return " ".join(text_parts) if text_parts else str(entry.entry_id)

    def _initialize_learner(
        self,
        model: MLModel,
        train_data: dict,
        val_data: dict,
        fields: list[str],
    ) -> ActiveLearningBackend:
        """Initialize ActiveLearningBackend with model configuration

        Args:
            model: MLModel instance
            train_data: Training data dictionary
            val_data: Validation data dictionary
            fields: List of field names

        Returns:
            Initialized ActiveLearningBackend instance

        Raises:
            ValueError: If algorithm not found or initialization fails
        """
        # Get model class
        model_class = AVAILABLE_MODELS.get(model.algorithm)

        if model_class is None:
            raise ValueError(
                f"Algorithm '{model.algorithm}' not found. "
                f"Available: {list(AVAILABLE_MODELS.keys())}"
            )

        # Get label values (assumes they are keys in train_data values)
        label_indices = {data[1] for data in train_data.values()}
        label_values = [f"class_{i}" for i in sorted(label_indices)]

        # Get training configuration
        training_config = model.training_config or {}

        # Extract specific configs
        n_kickstart = training_config.get("n_kickstart", 10)
        subsample_size = model.subsample_config or [1000, 100, 10]
        recall_frequency = training_config.get("recall_frequency", 5)

        # Initialize learner
        learner = ActiveLearningBackend(
            label_values=label_values,
            model_class=model_class,
            n_kickstart=n_kickstart,
            subsample_size=subsample_size,
            recall_frequency=recall_frequency,
        )

        # Set original dataset (all unlabeled initially)
        original_dataset = {entry_id: text for entry_id, (text, _) in train_data.items()}
        learner._original_dataset = original_dataset

        # Add labeled data
        for entry_id, (_text, label_idx) in train_data.items():
            learner.add_labeled_value(entry_id, label_values[label_idx])

        return learner

    def _extract_metrics(self, learner: ActiveLearningBackend) -> dict:
        """Extract training metrics from learner

        Args:
            learner: Trained ActiveLearningBackend instance

        Returns:
            Dictionary of metrics
        """
        metrics = {}

        # Get metrics from learner if available
        if hasattr(learner, "metrics") and learner.metrics:
            metrics = learner.metrics

        # Add model-specific metrics if available
        if hasattr(learner, "_model") and hasattr(learner._model, "get_metrics"):
            model_metrics = learner._model.get_metrics()
            if model_metrics:
                metrics.update(model_metrics)

        return metrics

    def _get_class_distribution(self, train_data: dict) -> dict:
        """Get class distribution from training data

        Args:
            train_data: Training data dictionary

        Returns:
            Dictionary mapping class indices to counts
        """
        distribution: dict[int, int] = {}

        for _, label_idx in train_data.values():
            distribution[label_idx] = distribution.get(label_idx, 0) + 1

        return {str(k): v for k, v in distribution.items()}

    def get_next_al_entries(
        self,
        model_id: int,
        n: int = 10,
    ) -> list[int]:
        """Get next entries for active learning annotation

        Args:
            model_id: ID of the MLModel
            n: Number of entries to retrieve

        Returns:
            List of entry IDs to annotate next

        Raises:
            ValueError: If model or active version not found
        """
        # Get active version
        version = self.registry.get_active_version(model_id)

        if version is None:
            raise ValueError(f"No active version found for model {model_id}")

        # Load cached entries from version
        if version.cache_entries:
            # Return first n entries from cache
            return version.cache_entries[:n]

        # If no cache, load artifacts and regenerate queue
        model = self.registry.get_model(model_id)
        if model is None:
            raise ValueError(f"Model {model_id} not found")

        try:
            # Load artifacts
            artifacts = self.artifact_manager.load_artifacts(model_id, version.version)

            # Reconstruct learner state
            learner = ActiveLearningBackend(
                label_values=list(artifacts["encoder"].classes_),
                model_class=type(artifacts["model"]),
                n_kickstart=model.training_config.get("n_kickstart", 10),
                subsample_size=model.subsample_config or [1000, 100, 10],
                recall_frequency=model.training_config.get("recall_frequency", 5),
            )

            # Restore model and encoder
            learner._model = artifacts["model"]
            learner._label_value_encoder = artifacts["encoder"]
            learner._policy = artifacts.get("policy")
            learner._bandit_explorer = artifacts.get("bandit")

            # Get unlabeled entries from the dataset
            # This would require access to the original dataset
            # For now, return empty list as it needs more context from Label
            # The cache should be populated during training and stored in version.cache_entries

            return []

        except Exception:
            # If artifact loading fails, return empty list
            # Cache should be populated during next training
            return []
