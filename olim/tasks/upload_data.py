import json
from collections.abc import Generator
from typing import Any

from elasticsearch import helpers

from .. import app as flask_app, entry_types
from ..celery_app import app
from ..database import register_entries
from ..settings import ES_INDEX, ES_SERVER, UPLOAD_BATCH_SIZE, WORK_PATH
from ..utils.es import create_index, get_es_conn


@app.task(bind=True, name="upload.process_batch")
def process_batch(
    self, batch_data: list[dict], dataset_id: int, entry_type: str, index_name: str, **kwargs
) -> dict:
    """Process a batch of data through the entire pipeline"""
    # Extract IDs and texts
    ids = [entry["id"] for entry in batch_data]
    texts = {entry["id"]: entry["text"] for entry in batch_data}
    metadata = {entry["id"]: entry["metadata"] for entry in batch_data}

    # Executing upload steps on batches.
    results = [
        upload_to_elasticsearch(ids, texts, metadata, index_name),
        register_batch_entries(ids, entry_type, dataset_id),
        store_texts_al(texts, dataset_id),
    ]

    # Check for failures
    errors = []
    for res in results:
        if not res.get("success", False):
            errors.append(res.get("error", "Unknown error"))

    if errors:
        raise Exception(f"Batch processing failed: {', '.join(errors)}")

    return {"success": True, "batch_size": len(batch_data)}


# @app.task(bind=True, name="upload.upload_to_elasticsearch")
def upload_to_elasticsearch(
    # self,
    # prev_result: list[dict],
    ids: list[str],
    texts: dict[str, str],
    metadata: dict[str, dict[str, str]],
    index: str,
) -> dict:
    """Upload a batch of data to Elasticsearch"""
    es = get_es_conn(
        hosts=ES_SERVER,
        request_timeout=120,
        read_timeout=120,
        timeout=120,
        max_retries=20,
    )

    # Generator for bulk upload
    def doc_generator() -> Generator[dict]:
        for entry_id in ids:
            doc = {"_index": index, "_id": entry_id, "_source": {"text": texts[entry_id]}}
            for key, value in metadata[entry_id].items():
                doc["_source"][key] = value
            yield doc

    # Perform bulk upload
    success, errors = helpers.bulk(es, doc_generator())

    if errors:
        raise Exception(f"ES upload errors: {errors!s}")

    return {"success": True, "documents_uploaded": success}


# @app.task(bind=True, name="upload.register_batch_entries")
def register_batch_entries(
    # self,
    # prev_result: list[dict],
    entry_ids: list[str],
    entry_type: str,
    dataset_id: int,
) -> dict:
    """Register a batch of entries in the database"""
    try:
        with flask_app.app_context():
            register_entries(entry_ids, entry_type, dataset_id)
            return {"success": True, "entries_registered": len(entry_ids)}
    except Exception as e:
        return {"success": False, "error": str(e)}


# @app.task(bind=True, name="storage.store_texts_al")
def store_texts_al(texts_dict: dict, dataset_id: int) -> dict:
    """
    Store texts using JSON Lines format for efficient large-scale storage

    Args:
        texts_dict: Dictionary of {id: text} to store
        dataset_id: Dataset identifier for file path

    Returns:
        dict: Result with success status and file path
    """
    dataset_dir = WORK_PATH / "datasets"
    dataset_dir.mkdir(parents=True, exist_ok=True)
    file_path = dataset_dir / f"{dataset_id}.jsonl"

    # Append new texts in JSON Lines format
    with file_path.open("a") as f:
        for entry_id, text in texts_dict.items():
            json_line = json.dumps({"id": entry_id, "text": text})
            f.write(json_line + "\n")

    return {"success": True, "path": str(file_path), "entries_stored": len(texts_dict)}


@app.task(bind=True, name="upload.upload_dataset")
def upload_dataset(
    self,
    upload_type: str,
    upload_params: dict[str, Any],
    dataset_id: int,
    **kwargs,
) -> dict:
    """Orchestrate dataset upload in batches without full memory load

    Args:
        upload_params: Dictionary containing:
            - filename: Path to CSV file
            - id_column: Name of ID column
            - text_column: Name of text column
            - entry_type: Type of entries ('text' or 'patient')
        dataset_id: ID of dataset to associate with
    """
    # Create Elasticsearch index
    index_name = ES_INDEX.format(dataset_id=dataset_id)
    create_index(index_name)

    # Create batch generator
    if not hasattr(entry_types, upload_type):
        raise ValueError(f"Invalid upload type: {upload_type}")
    type_module = getattr(entry_types, upload_type)
    if not hasattr(type_module, "generate_upload_batches"):
        raise NotImplementedError(
            f"Upload type {upload_type} doesn't contain upload batches generation function."
        )
    batch_generator = type_module.generate_upload_batches(
        batch_size=UPLOAD_BATCH_SIZE,
        **upload_params,
    )

    # Process batches sequentially
    total_records = 0
    batch_count = 0
    processed_batches = []
    for batch in batch_generator:
        batch_count += 1
        total_records += len(batch)

        # Update task state
        self.update_state(
            state="PROGRESS",
            meta={
                "current": batch_count,
                "total": "unknown",
                "status": f"Processing batch {batch_count}",
            },
        )

        # Process current batch
        result = process_batch.s(batch, dataset_id, upload_type, index_name)()

        processed_batches.append({"batch": batch_count, "result": result, "size": len(batch)})

        # Check for failure
        if not result.get("success", False):
            raise Exception(f"Batch {batch_count} failed: {result.get('error', 'Unknown error')}")

    return {
        "success": True,
        "total_records": total_records,
        "batches_processed": batch_count,
        "batch_results": processed_batches,
    }
