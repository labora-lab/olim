"""
Artifact Manager for ML Model Storage

This module handles the storage and retrieval of ML model artifacts (pickle files).

Artifacts include:
- Trained model (model.pickle)
- Label encoder (encoder.pickle)
- Active learning policy (policy.pickle)
- Bandit explorer (bandit.pickle)
- Field configurations (fields.json)
"""

from __future__ import annotations

import json
import pickle
import shutil
from pathlib import Path
from typing import Any


class ArtifactManager:
    """Manager for ML model artifact storage

    Handles saving and loading model artifacts to/from the filesystem.
    Organizes artifacts in a structured directory hierarchy.
    """

    def __init__(self, base_path: Path | str) -> None:
        """Initialize ArtifactManager

        Args:
            base_path: Base directory for storing artifacts (usually WORK_PATH / "ml_models")
        """
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)

    def get_model_path(self, model_id: int, version: int) -> Path:
        """Get directory path for a specific model version

        Args:
            model_id: ID of the model
            version: Version number

        Returns:
            Path to the version directory

        Example:
            >>> manager = ArtifactManager("/work/ml_models")
            >>> path = manager.get_model_path(1, 2)
            >>> # Returns: /work/ml_models/model_1/v2/
        """
        return self.base_path / f"model_{model_id}" / f"v{version}"

    def save_artifacts(
        self,
        model_id: int,
        version: int,
        model: Any,
        encoder: Any,
        policy: Any | None = None,
        bandit: Any | None = None,
        fields: list[str] | None = None,
    ) -> Path:
        """Save all model artifacts to disk

        Args:
            model_id: ID of the model
            version: Version number
            model: Trained model instance (e.g. ConformalPredictor)
            encoder: Label encoder instance
            policy: Active learning policy (optional)
            bandit: Bandit explorer (optional)
            fields: List of field names used for training

        Returns:
            Path where artifacts were saved

        Raises:
            IOError: If artifact saving fails
        """
        version_path = self.get_model_path(model_id, version)
        version_path.mkdir(parents=True, exist_ok=True)

        try:
            # Save main model
            with open(version_path / "model.pickle", "wb") as f:
                pickle.dump(model, f)

            # Save label encoder
            with open(version_path / "encoder.pickle", "wb") as f:
                pickle.dump(encoder, f)

            # Save policy
            if policy is not None:
                with open(version_path / "policy.pickle", "wb") as f:
                    pickle.dump(policy, f)

            # Save bandit explorer
            if bandit is not None:
                with open(version_path / "bandit.pickle", "wb") as f:
                    pickle.dump(bandit, f)

            # Save field configuration
            if fields is not None:
                with open(version_path / "fields.json", "w") as f:
                    json.dump({"fields": fields}, f)

            return version_path

        except Exception as e:
            # Clean up on failure
            if version_path.exists():
                shutil.rmtree(version_path)
            raise OSError(f"Failed to save artifacts: {e}") from e

    def load_artifacts(
        self,
        model_id: int,
        version: int,
    ) -> dict[str, Any]:
        """Load all model artifacts from disk

        Args:
            model_id: ID of the model
            version: Version number

        Returns:
            Dictionary containing loaded artifacts:
            - model: Trained model instance
            - encoder: Label encoder
            - policy: Active learning policy (if exists)
            - bandit: Bandit explorer (if exists)
            - fields: List of field names (if exists)

        Raises:
            FileNotFoundError: If artifacts don't exist
            IOError: If loading fails
        """
        version_path = self.get_model_path(model_id, version)

        if not version_path.exists():
            raise FileNotFoundError(f"Artifacts not found at {version_path}")

        try:
            artifacts: dict[str, Any] = {}

            # Load main model
            with open(version_path / "model.pickle", "rb") as f:
                artifacts["model"] = pickle.load(f)

            # Load label encoder
            with open(version_path / "encoder.pickle", "rb") as f:
                artifacts["encoder"] = pickle.load(f)

            # Load policy (optional)
            policy_path = version_path / "policy.pickle"
            if policy_path.exists():
                with open(policy_path, "rb") as f:
                    artifacts["policy"] = pickle.load(f)
            else:
                artifacts["policy"] = None

            # Load bandit (optional)
            bandit_path = version_path / "bandit.pickle"
            if bandit_path.exists():
                with open(bandit_path, "rb") as f:
                    artifacts["bandit"] = pickle.load(f)
            else:
                artifacts["bandit"] = None

            # Load fields (optional)
            fields_path = version_path / "fields.json"
            if fields_path.exists():
                with open(fields_path) as f:
                    artifacts["fields"] = json.load(f).get("fields")
            else:
                artifacts["fields"] = None

            return artifacts

        except Exception as e:
            raise OSError(f"Failed to load artifacts: {e}") from e

    def migrate_from_label_path(
        self,
        label_path: Path | str,
        model_id: int,
        version: int,
    ) -> Path:
        """Migrate artifacts from old Label-based storage to new structure

        Args:
            label_path: Path to existing Label artifacts (e.g., /work/label_123/)
            model_id: ID of the new MLModel
            version: Version number for the new location

        Returns:
            Path where artifacts were migrated to

        Raises:
            FileNotFoundError: If source path doesn't exist
            IOError: If migration fails
        """
        label_path = Path(label_path)

        if not label_path.exists():
            raise FileNotFoundError(f"Source path {label_path} does not exist")

        version_path = self.get_model_path(model_id, version)
        version_path.mkdir(parents=True, exist_ok=True)

        try:
            # Copy all pickle and json files
            for file_pattern in ["*.pickle", "*.json"]:
                for src_file in label_path.glob(file_pattern):
                    dst_file = version_path / src_file.name
                    shutil.copy2(src_file, dst_file)

            return version_path

        except Exception as e:
            # Clean up on failure
            if version_path.exists():
                shutil.rmtree(version_path)
            raise OSError(f"Failed to migrate artifacts: {e}") from e

    def delete_artifacts(self, model_id: int, version: int | None = None) -> None:
        """Delete artifacts from disk

        Args:
            model_id: ID of the model
            version: Specific version to delete, or None to delete all versions

        Raises:
            FileNotFoundError: If artifacts don't exist
        """
        if version is not None:
            # Delete specific version
            version_path = self.get_model_path(model_id, version)
            if version_path.exists():
                shutil.rmtree(version_path)
        else:
            # Delete all versions of the model
            model_path = self.base_path / f"model_{model_id}"
            if model_path.exists():
                shutil.rmtree(model_path)

    def list_versions(self, model_id: int) -> list[int]:
        """List available versions for a model

        Args:
            model_id: ID of the model

        Returns:
            List of version numbers (sorted)
        """
        model_path = self.base_path / f"model_{model_id}"

        if not model_path.exists():
            return []

        versions = []
        for version_dir in model_path.glob("v*"):
            if version_dir.is_dir():
                try:
                    version_num = int(version_dir.name[1:])  # Remove 'v' prefix
                    versions.append(version_num)
                except ValueError:
                    continue

        return sorted(versions)

    def get_artifact_size(self, model_id: int, version: int) -> int:
        """Get total size of artifacts in bytes

        Args:
            model_id: ID of the model
            version: Version number

        Returns:
            Total size in bytes

        Raises:
            FileNotFoundError: If artifacts don't exist
        """
        version_path = self.get_model_path(model_id, version)

        if not version_path.exists():
            raise FileNotFoundError(f"Artifacts not found at {version_path}")

        total_size = 0
        for file_path in version_path.rglob("*"):
            if file_path.is_file():
                total_size += file_path.stat().st_size

        return total_size
