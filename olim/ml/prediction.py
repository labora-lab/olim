"""Prediction Engine with Caching

This module provides a thread-safe prediction engine with in-memory caching.
The cache stores loaded model artifacts to avoid repeated disk I/O.
"""

from __future__ import annotations

from pathlib import Path
from threading import Lock

from olim.database import get_ml_version
from olim.ml.artifacts import ArtifactManager
from olim.ml.registry import ModelRegistry


class PredictionResult:
    """Container for prediction results"""

    def __init__(
        self,
        predicted_class: str | None = None,
        prediction_set: list[str] | None = None,
        confidence: float | None = None,
        probabilities: dict[str, float] | None = None,
    ) -> None:
        self.predicted_class = predicted_class
        self.prediction_set = prediction_set or []
        self.confidence = confidence
        self.probabilities = probabilities or {}

    def to_dict(self) -> dict[str, str | list[str] | float | dict[str, float] | None]:
        """Convert to dictionary representation"""
        return {
            "predicted_class": self.predicted_class,
            "prediction_set": self.prediction_set,
            "confidence": self.confidence,
            "probabilities": self.probabilities,
        }


class PredictionEngine:
    """Thread-safe prediction engine with artifact caching

    Maintains an in-memory cache of loaded model artifacts to improve
    prediction performance. Cache is thread-safe for concurrent requests.
    """

    def __init__(self, work_path: Path | str, cache_size: int = 10) -> None:
        """Initialize PredictionEngine

        Args:
            work_path: Base path for model artifacts
            cache_size: Maximum number of versions to cache (default: 10)
        """
        work_path_obj = Path(work_path) if isinstance(work_path, str) else work_path
        self.artifact_manager = ArtifactManager(work_path_obj / "ml_models")
        self.registry = ModelRegistry()
        self.cache_size = cache_size

        # Cache structure: {version_id: artifacts_dict}
        self._cache: dict[int, dict] = {}
        self._cache_lock = Lock()

        # LRU tracking: {version_id: access_count}
        self._access_counts: dict[int, int] = {}

    def predict_single(
        self,
        model_id: int,
        text: str,
        version_id: int | None = None,
    ) -> PredictionResult:
        """Make a single prediction

        Args:
            model_id: ID of the model to use
            text: Input text to predict
            version_id: Specific version to use (None = active version)

        Returns:
            PredictionResult instance

        Raises:
            ValueError: If model or version not found
            RuntimeError: If prediction fails
        """
        # Get version to use
        if version_id is None:
            version = self.registry.get_active_version(model_id)
            if version is None:
                raise ValueError(f"No active version found for model {model_id}")
            version_id = version.id
            version_number = version.version
        else:
            # Verify version exists
            version = get_ml_version(version_id)
            if version is None:
                raise ValueError(f"Version {version_id} not found")
            version_number = version.version

        # Load artifacts (with caching) - version_id is guaranteed to be int here
        assert version_id is not None  # Type narrowing for mypy/pyright
        artifacts = self._get_cached_artifacts(version_id, model_id, version_number)

        try:
            # Extract components
            model = artifacts["model"]
            encoder = artifacts["encoder"]
            policy = artifacts.get("policy")

            # Make prediction
            # Assuming model has a predict method that returns probabilities
            if hasattr(model, "predict_proba"):
                proba = model.predict_proba([text])[0]
                predicted_class_idx = proba.argmax()
                confidence = float(proba[predicted_class_idx])

                # Get class labels
                classes = encoder.classes_

                # Build probabilities dict
                probabilities = {classes[i]: float(proba[i]) for i in range(len(classes))}

                predicted_class = classes[predicted_class_idx]

                # Get prediction set from conformal policy if available
                prediction_set = []
                if policy is not None and hasattr(policy, "get_prediction_set"):
                    prediction_set = policy.get_prediction_set(proba)
                else:
                    # Default: just the predicted class
                    prediction_set = [predicted_class]

                return PredictionResult(
                    predicted_class=predicted_class,
                    prediction_set=prediction_set,
                    confidence=confidence,
                    probabilities=probabilities,
                )

            elif hasattr(model, "predict"):
                # Simpler prediction without probabilities
                predicted_idx = model.predict([text])[0]
                classes = encoder.classes_
                predicted_class = classes[predicted_idx]

                return PredictionResult(
                    predicted_class=predicted_class,
                    prediction_set=[predicted_class],
                    confidence=None,
                    probabilities={},
                )

            else:
                raise RuntimeError("Model does not have predict or predict_proba method")

        except Exception as e:
            raise RuntimeError(f"Prediction failed: {e}") from e

    def predict_batch(
        self,
        model_id: int,
        texts: list[str],
        version_id: int | None = None,
    ) -> list[PredictionResult]:
        """Make batch predictions

        Args:
            model_id: ID of the model to use
            texts: List of input texts
            version_id: Specific version to use (None = active version)

        Returns:
            List of PredictionResult instances

        Raises:
            ValueError: If model or version not found
            RuntimeError: If prediction fails
        """
        # For now, use single prediction in a loop
        # TODO: Optimize with true batch prediction
        return [self.predict_single(model_id, text, version_id) for text in texts]

    def _get_cached_artifacts(self, version_id: int, model_id: int, version_number: int) -> dict:
        """Get artifacts from cache or load from disk

        Args:
            version_id: ID of the version
            model_id: ID of the model
            version_number: Version number

        Returns:
            Dictionary of artifacts

        Raises:
            FileNotFoundError: If artifacts not found
        """
        with self._cache_lock:
            # Check if in cache
            if version_id in self._cache:
                # Update access count
                self._access_counts[version_id] = self._access_counts.get(version_id, 0) + 1
                return self._cache[version_id]

            # Load from disk
            artifacts = self.artifact_manager.load_artifacts(model_id, version_number)

            # Add to cache
            self._cache[version_id] = artifacts
            self._access_counts[version_id] = 1

            # Evict if cache is full
            if len(self._cache) > self.cache_size:
                self._evict_least_used()

            return artifacts

    def _evict_least_used(self) -> None:
        """Evict least recently used version from cache

        Must be called within _cache_lock context.
        """
        if not self._cache:
            return

        # Find version with lowest access count
        least_used_version_id = min(self._access_counts, key=self._access_counts.get)  # type: ignore

        # Remove from cache
        del self._cache[least_used_version_id]
        del self._access_counts[least_used_version_id]

    def clear_cache(self, version_id: int | None = None) -> None:
        """Clear prediction cache

        Args:
            version_id: Specific version to clear, or None to clear all
        """
        with self._cache_lock:
            if version_id is not None:
                self._cache.pop(version_id, None)
                self._access_counts.pop(version_id, None)
            else:
                self._cache.clear()
                self._access_counts.clear()

    def get_cache_stats(self) -> dict[str, int | list[int] | dict[int, int]]:
        """Get cache statistics

        Returns:
            Dictionary with cache size and access counts
        """
        with self._cache_lock:
            return {
                "cache_size": len(self._cache),
                "max_cache_size": self.cache_size,
                "cached_versions": list(self._cache.keys()),
                "access_counts": dict(self._access_counts),
            }
