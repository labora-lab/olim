"""
REST API for OLIM

Provides JSON endpoints for:
- API key generation and management
- Dataset listing and bulk entry ingestion
- ML model predictions by raw text or entry ID
"""

from __future__ import annotations

import secrets
from typing import Any, cast

from flask import Blueprint, Response, jsonify, request, session
from sqlalchemy import select
from werkzeug.security import check_password_hash

from olim import db
from olim.database import (
    Dataset,
    Entry,
    check_entries_exist,
    get_dataset,
    get_datasets,
    get_user,
    link_dataset_to_project,
    new_dataset,
    register_entries,
    update_user,
)
from olim.entry_types.registry import get_entry_type_instance
from olim.ml.models import MLModel
from olim.ml.services import MLModelService
from olim.settings import ES_INDEX, WORK_PATH
from olim.tasks.upload_data import store_texts_al, upload_to_elasticsearch
from olim.utils.es import create_index

api = Blueprint("api", __name__, url_prefix="/api/v1")


# ---------------------------------------------------------------------------
# Response helpers
# ---------------------------------------------------------------------------


def error_response(message: str, status_code: int = 400) -> tuple[Response, int]:
    """Create error response"""
    return jsonify({"error": message, "status": "error"}), status_code


def success_response(data: dict[str, Any], status_code: int = 200) -> tuple[Response, int]:
    """Create success response"""
    return jsonify({"data": data, "status": "success"}), status_code


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get_model_by_slug(slug: str) -> MLModel | None:
    """Get model by slug"""
    stmt = select(MLModel).where(MLModel.slug == slug, MLModel.is_deleted.is_(False))
    return db.session.execute(stmt).scalar_one_or_none()


def _resolve_version(
    service: MLModelService,
    model_id: int,
    model_slug: str,
    version: int | None,
) -> tuple[int, int] | tuple[Response, int]:
    """Resolve model version to (version_id, version_number).

    Args:
        service: Active MLModelService instance
        model_id: Internal model ID
        model_slug: Slug used in error messages
        version: Requested version number, or None to use the active version

    Returns:
        (version_id, version_number) on success, or an error_response tuple
    """
    if version is None:
        model_version = service.get_active_version(model_id)
        if not model_version:
            return error_response("Model has no active version. Train the model first.", 400)
        return model_version.id, model_version.version
    if not isinstance(version, int) or version < 1:
        return error_response("'version' must be a positive integer", 400)
    versions = service.list_versions(model_id, limit=1000)
    model_version = next((v for v in versions if v.version == version), None)
    if not model_version:
        return error_response(f"Version {version} not found for model '{model_slug}'", 404)
    return model_version.id, model_version.version


def _do_ingest(entries: list[dict[str, Any]], dataset_id: int) -> tuple[Response, int]:
    """Run the full ingest pipeline for a list of raw entry dicts.

    Skips duplicate IDs (within request and already in DB). Returns
    a summary with counts of ingested and skipped entries.

    Args:
        entries: List of dicts with keys: id (str), text (str), metadata (dict, optional)
        dataset_id: Target dataset ID

    Returns:
        success_response with ingest summary, or error_response on failure
    """
    index_name = ES_INDEX.format(dataset_id=dataset_id)

    # Validate and deduplicate within request
    seen_in_request: set[str] = set()
    clean_entries: list[dict[str, Any]] = []
    warnings: list[str] = []

    for i, entry in enumerate(entries):
        if not isinstance(entry.get("id"), str) or not entry["id"]:
            return error_response(f"Entry at index {i} missing valid 'id' field", 400)
        if not isinstance(entry.get("text"), str):
            return error_response(f"Entry at index {i} missing valid 'text' field", 400)
        eid = entry["id"]
        if eid in seen_in_request:
            warnings.append(f"Duplicate entry ID '{eid}' in request — skipped")
            continue
        seen_in_request.add(eid)
        clean_entries.append(entry)

    # Skip entries already in DB
    all_ids = [e["id"] for e in clean_entries]
    existing_ids, _ = check_entries_exist(all_ids, dataset_id)
    existing_set = set(existing_ids)
    for eid in existing_set:
        warnings.append(f"Entry ID '{eid}' already exists in dataset — skipped")

    new_entries = [e for e in clean_entries if e["id"] not in existing_set]
    skipped = len(entries) - len(new_entries)

    if not new_entries:
        return success_response(
            {"ingested": 0, "skipped": skipped, "warnings": warnings, "dataset_id": dataset_id}
        )

    ids = [e["id"] for e in new_entries]
    texts = {e["id"]: e["text"] for e in new_entries}
    metadata: dict[str, dict[str, Any]] = {e["id"]: e.get("metadata") or {} for e in new_entries}

    try:
        upload_to_elasticsearch(ids, texts, metadata, index_name)
    except Exception as e:
        return error_response(f"Elasticsearch ingest failed: {e!s}", 500)

    try:
        register_entries(ids, "single_text", dataset_id)
    except Exception as e:
        return error_response(f"Database registration failed: {e!s}", 500)

    try:
        store_texts_al(texts, dataset_id)
    except Exception as e:
        return error_response(f"JSONL storage failed: {e!s}", 500)

    return success_response(
        {
            "ingested": len(new_entries),
            "skipped": skipped,
            "warnings": warnings,
            "dataset_id": dataset_id,
        },
        201,
    )


# ---------------------------------------------------------------------------
# Auth endpoints
# ---------------------------------------------------------------------------


@api.route("/auth/key", methods=["POST"])
def generate_api_key() -> tuple[Response, int]:
    """Generate or regenerate API key for a user.

    Request Body:
        {"username": "user", "password": "pass"}

    Returns:
        {"status": "success", "data": {"api_key": "..."}}
    """
    if not request.is_json:
        return error_response("Content-Type must be application/json", 400)

    data = request.get_json()
    if not data or "username" not in data or "password" not in data:
        return error_response("Missing 'username' or 'password' field", 400)

    user = get_user(data["username"], by="username")
    if user is None or not check_password_hash(user.password, data["password"]):
        return error_response("Invalid credentials", 401)

    new_key = secrets.token_hex(32)
    update_user(user.id, api_key=new_key)

    return success_response({"api_key": new_key})


# ---------------------------------------------------------------------------
# Dataset endpoints
# ---------------------------------------------------------------------------


@api.route("/datasets", methods=["GET"])
def list_datasets() -> tuple[Response, int]:
    """List all datasets.

    Returns:
        {
            "status": "success",
            "data": {
                "datasets": [{"id": 1, "name": "...", "created": "..."}],
                "total": 1
            }
        }
    """
    datasets = get_datasets()
    return success_response(
        {
            "datasets": [
                {"id": ds.id, "name": ds.name, "created": ds.created.isoformat()} for ds in datasets
            ],
            "total": len(datasets),
        }
    )


@api.route("/datasets", methods=["POST"])
def create_dataset_and_ingest() -> tuple[Response, int]:
    """Create a new dataset and ingest entries.

    Request Body:
        {
            "name": "My Dataset",
            "entries": [{"id": "e1", "text": "...", "metadata": {"col": "val"}}],
            "projects": [1, 2]
        }

    Returns:
        {"status": "success", "data": {"ingested": 5, "skipped": 0, "dataset_id": 3, ...}}
    """
    if not request.is_json:
        return error_response("Content-Type must be application/json", 400)

    data = request.get_json()
    if not data or "name" not in data:
        return error_response("Missing 'name' field", 400)

    entries = data.get("entries")
    if not entries or not isinstance(entries, list):
        return error_response("Missing or invalid 'entries' field", 400)

    if len(entries) > 1000:
        return error_response("Maximum 1000 entries per request", 400)

    user_id: int = session["user_id"]
    dataset: Dataset = new_dataset(data["name"], user_id)

    index_name = ES_INDEX.format(dataset_id=dataset.id)
    try:
        create_index(index_name)
    except Exception as e:
        return error_response(f"Failed to create search index: {e!s}", 500)

    for project_id in data.get("projects") or []:
        if isinstance(project_id, int):
            link_dataset_to_project(dataset.id, project_id, user_id)

    return _do_ingest(entries, dataset.id)


@api.route("/datasets/<int:dataset_id>/entries", methods=["POST"])
def ingest_entries(dataset_id: int) -> tuple[Response, int]:
    """Ingest entries into an existing dataset.

    Request Body:
        {
            "entries": [{"id": "e1", "text": "...", "metadata": {"col": "val"}}]
        }

    Max 1000 entries per request.

    Returns:
        {"status": "success", "data": {"ingested": 5, "skipped": 0, "dataset_id": 3, ...}}
    """
    if not request.is_json:
        return error_response("Content-Type must be application/json", 400)

    if get_dataset(dataset_id) is None:
        return error_response(f"Dataset {dataset_id} not found", 404)

    data = request.get_json()
    entries = data.get("entries") if data else None
    if not entries or not isinstance(entries, list):
        return error_response("Missing or invalid 'entries' field", 400)

    if len(entries) > 1000:
        return error_response("Maximum 1000 entries per request", 400)

    return _do_ingest(entries, dataset_id)


# ---------------------------------------------------------------------------
# Model prediction endpoints
# ---------------------------------------------------------------------------


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
    model = _get_model_by_slug(slug)
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

    model = _get_model_by_slug(slug)
    if not model:
        return error_response(f"Model with slug '{slug}' not found", 404)

    service = MLModelService(WORK_PATH)
    version_result = _resolve_version(service, model.id, slug, data.get("version"))
    if isinstance(version_result[0], Response):
        return version_result  # type: ignore[return-value]
    version_id, version_number = cast(tuple[int, int], version_result)

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
                "predictions": [...],
                "total": 3
            }
        }
    """
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

    for i, text in enumerate(texts):
        if not isinstance(text, str) or not text:
            return error_response(f"Item at index {i} must be a non-empty string", 400)
        if len(text) > 10000:
            return error_response(f"Item at index {i} exceeds maximum length of 10000 chars", 400)

    model = _get_model_by_slug(slug)
    if not model:
        return error_response(f"Model with slug '{slug}' not found", 404)

    service = MLModelService(WORK_PATH)
    version_result = _resolve_version(service, model.id, slug, data.get("version"))
    if isinstance(version_result[0], Response):
        return version_result  # type: ignore[return-value]
    version_id, version_number = cast(tuple[int, int], version_result)

    try:
        results = service.predict_batch(model.id, texts, version_id=version_id)
        predictions = [
            {
                "predicted_class": r.predicted_class,
                "prediction_set": r.prediction_set or [],
                "confidence": r.confidence,
                "probabilities": r.probabilities,
                "model_slug": slug,
                "model_version": version_number,
            }
            for r in results
        ]
        return success_response({"predictions": predictions, "total": len(predictions)})
    except Exception as e:
        return error_response(f"Batch prediction failed: {e!s}", 500)


@api.route("/models/<slug>/predict/entries", methods=["POST"])
def predict_entries(slug: str) -> tuple[Response, int]:
    """
    Predict for entries retrieved by ID from the database.

    Request Body:
        {
            "entries": [{"entry_id": "e1", "dataset_id": 5}],
            "version": 2  // optional, defaults to active version
        }

    Returns:
        {
            "status": "success",
            "data": {
                "predictions": [...],
                "errors": [...],
                "total_requested": 3,
                "total_predicted": 2
            }
        }
    """
    if not request.is_json:
        return error_response("Content-Type must be application/json", 400)

    data = request.get_json()
    if not data or "entries" not in data:
        return error_response("Missing 'entries' field in request body", 400)

    entry_refs = data["entries"]
    if not isinstance(entry_refs, list) or not entry_refs:
        return error_response("'entries' must be a non-empty list", 400)

    if len(entry_refs) > 1000:
        return error_response("Maximum 1000 entries per request", 400)

    model = _get_model_by_slug(slug)
    if not model:
        return error_response(f"Model with slug '{slug}' not found", 404)

    service = MLModelService(WORK_PATH)
    version_result = _resolve_version(service, model.id, slug, data.get("version"))
    if isinstance(version_result[0], Response):
        return version_result  # type: ignore[return-value]
    version_id, version_number = cast(tuple[int, int], version_result)

    predictions: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for ref in entry_refs:
        entry_id = ref.get("entry_id")
        dataset_id = ref.get("dataset_id")

        if not entry_id or not isinstance(dataset_id, int):
            errors.append({"entry_id": entry_id, "error": "Missing entry_id or dataset_id"})
            continue

        entry: Entry | None = db.session.execute(
            db.select(Entry).filter_by(entry_id=str(entry_id), dataset_id=dataset_id)
        ).scalar_one_or_none()

        if entry is None:
            errors.append({"entry_id": entry_id, "error": "Entry not found"})
            continue

        entry_type_instance = get_entry_type_instance(entry.type)
        if entry_type_instance is None:
            errors.append({"entry_id": entry_id, "error": f"Unknown entry type '{entry.type}'"})
            continue

        try:
            df = entry_type_instance.extract_texts(str(entry_id), dataset_id=dataset_id)
            text = df["text"].iloc[0]
        except Exception as e:
            errors.append({"entry_id": entry_id, "error": f"Text extraction failed: {e!s}"})
            continue

        try:
            result = service.predict(model.id, text, version_id=version_id)
            predictions.append(
                {
                    "entry_id": entry_id,
                    "dataset_id": dataset_id,
                    "predicted_class": result.predicted_class,
                    "prediction_set": result.prediction_set or [],
                    "confidence": result.confidence,
                    "probabilities": result.probabilities,
                    "model_slug": slug,
                    "model_version": version_number,
                }
            )
        except Exception as e:
            errors.append({"entry_id": entry_id, "error": f"Prediction failed: {e!s}"})

    return success_response(
        {
            "predictions": predictions,
            "errors": errors,
            "total_requested": len(entry_refs),
            "total_predicted": len(predictions),
        }
    )


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------


@api.route("/health", methods=["GET"])
def health_check() -> tuple[Response, int]:
    """
    API health check

    Returns:
        {"status": "success", "data": {"service": "olim-api", "version": "1.0.0"}}
    """
    return success_response({"service": "olim-api", "version": "1.0.0"})
