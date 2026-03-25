"""
REST API for ML Model Predictions

Provides JSON endpoints for model prediction with slug-based routing.
Supports version selection (defaults to active version).
"""

from typing import Any

from flask import Blueprint, Response, jsonify, request
from sqlalchemy import select

from olim import db
from olim.ml.models import MLModel
from olim.ml.services import MLModelService
from olim.settings import WORK_PATH

api = Blueprint("api", __name__, url_prefix="/api/v1")


def get_model_by_slug(slug: str) -> MLModel | None:
    """Get model by slug"""
    stmt = select(MLModel).where(MLModel.slug == slug, MLModel.is_deleted.is_(False))
    return db.session.execute(stmt).scalar_one_or_none()


def error_response(message: str, status_code: int = 400) -> tuple[Response, int]:
    """Create error response"""
    return jsonify({"error": message, "status": "error"}), status_code


def success_response(data: dict[str, Any], status_code: int = 200) -> tuple[Response, int]:
    """Create success response"""
    return jsonify({"data": data, "status": "success"}), status_code


@api.route("/models/<slug>", methods=["GET"])
def get_model_info(slug: str) -> tuple[Response, int]:
    """
    Get model information by slug

    Returns:
        {
            "status": "success",
            "data": {
                "slug": "model-slug",
                "name": "Model Name",
                "algorithm": "TfidfXGBoostClassifier",
                "status": "active",
                "active_version": 3,
                "created": "2024-01-15T10:30:00"
            }
        }
    """
    model = get_model_by_slug(slug)
    if not model:
        return error_response(f"Model with slug '{slug}' not found", 404)

    service = MLModelService(WORK_PATH)
    active_version = service.get_active_version(model.id)

    return success_response(
        {
            "slug": model.slug,
            "name": model.name,
            "algorithm": model.algorithm,
            "status": model.status,
            "active_version": active_version.version if active_version else None,
            "created": model.created.isoformat(),
        }
    )


@api.route("/models/<slug>/predict", methods=["POST"])
def predict_single(slug: str) -> tuple[Response, int]:
    """
    Make a single prediction

    Request Body:
        {
            "text": "Input text to classify",
            "version": 2  // optional, defaults to active version
        }

    Returns:
        {
            "status": "success",
            "data": {
                "predicted_class": "sim",
                "prediction_set": ["sim"],
                "confidence": 0.95,
                "probabilities": {"sim": 0.95, "não": 0.05},
                "model_slug": "model-slug",
                "model_version": 2
            }
        }
    """
    # Validate request
    if not request.is_json:
        return error_response("Content-Type must be application/json", 400)

    data = request.get_json()
    if not data or "text" not in data:
        return error_response("Missing 'text' field in request body", 400)

    text = data["text"]
    if not text or not isinstance(text, str):
        return error_response("'text' must be a non-empty string", 400)

    if len(text) > 10000:
        return error_response("'text' exceeds maximum length of 10000 characters", 400)

    version = data.get("version")

    # Get model
    model = get_model_by_slug(slug)
    if not model:
        return error_response(f"Model with slug '{slug}' not found", 404)

    service = MLModelService(WORK_PATH)

    # Get version to use
    if version is None:
        model_version = service.get_active_version(model.id)
        if not model_version:
            return error_response("Model has no active version. Train the model first.", 400)
        version_id = model_version.id
        version_number = model_version.version
    else:
        # Find specific version
        if not isinstance(version, int) or version < 1:
            return error_response("'version' must be a positive integer", 400)

        versions = service.list_versions(model.id, limit=1000)
        model_version = next((v for v in versions if v.version == version), None)
        if not model_version:
            return error_response(f"Version {version} not found for model '{slug}'", 404)
        version_id = model_version.id
        version_number = version

    # Make prediction
    try:
        result = service.predict(model.id, text, version_id=version_id)

        return success_response(
            {
                "predicted_class": result.predicted_class,
                "prediction_set": result.prediction_set or [],
                "confidence": result.confidence,
                "probabilities": result.probabilities,
                "model_slug": slug,
                "model_version": version_number,
            }
        )
    except Exception as e:
        return error_response(f"Prediction failed: {e!s}", 500)


@api.route("/models/<slug>/predict/batch", methods=["POST"])
def predict_batch(slug: str) -> tuple[Response, int]:
    """
    Make batch predictions

    Request Body:
        {
            "texts": ["Text 1", "Text 2", "Text 3"],
            "version": 2  // optional, defaults to active version
        }

    Returns:
        {
            "status": "success",
            "data": {
                "predictions": [
                    {
                        "predicted_class": "sim",
                        "prediction_set": ["sim"],
                        "confidence": 0.95,
                        "probabilities": {"sim": 0.95, "não": 0.05},
                        "model_slug": "model-slug",
                        "model_version": 2
                    },
                    ...
                ],
                "total": 3
            }
        }
    """
    # Validate request
    if not request.is_json:
        return error_response("Content-Type must be application/json", 400)

    data = request.get_json()
    if not data or "texts" not in data:
        return error_response("Missing 'texts' field in request body", 400)

    texts = data["texts"]
    if not isinstance(texts, list):
        return error_response("'texts' must be a list", 400)

    if not texts:
        return error_response("'texts' list cannot be empty", 400)

    if len(texts) > 1000:
        return error_response("'texts' list exceeds maximum of 1000 items", 400)

    # Validate each text
    for i, text in enumerate(texts):
        if not isinstance(text, str) or not text:
            return error_response(f"Item at index {i} must be a non-empty string", 400)
        if len(text) > 10000:
            return error_response(f"Item at index {i} exceeds maximum length of 10000 chars", 400)

    version = data.get("version")

    # Get model
    model = get_model_by_slug(slug)
    if not model:
        return error_response(f"Model with slug '{slug}' not found", 404)

    service = MLModelService(WORK_PATH)

    # Get version to use
    if version is None:
        model_version = service.get_active_version(model.id)
        if not model_version:
            return error_response("Model has no active version. Train the model first.", 400)
        version_id = model_version.id
        version_number = model_version.version
    else:
        # Find specific version
        if not isinstance(version, int) or version < 1:
            return error_response("'version' must be a positive integer", 400)

        versions = service.list_versions(model.id, limit=1000)
        model_version = next((v for v in versions if v.version == version), None)
        if not model_version:
            return error_response(f"Version {version} not found for model '{slug}'", 404)
        version_id = model_version.id
        version_number = version

    # Make predictions
    try:
        results = service.predict_batch(model.id, texts, version_id=version_id)

        predictions = [
            {
                "predicted_class": result.predicted_class,
                "prediction_set": result.prediction_set or [],
                "confidence": result.confidence,
                "probabilities": result.probabilities,
                "model_slug": slug,
                "model_version": version_number,
            }
            for result in results
        ]

        return success_response({"predictions": predictions, "total": len(predictions)})
    except Exception as e:
        return error_response(f"Batch prediction failed: {e!s}", 500)


@api.route("/health", methods=["GET"])
def health_check() -> tuple[Response, int]:
    """
    API health check

    Returns:
        {
            "status": "success",
            "data": {
                "service": "olim-ml-api",
                "version": "1.0.0"
            }
        }
    """
    return success_response({"service": "olim-ml-api", "version": "1.0.0"})
