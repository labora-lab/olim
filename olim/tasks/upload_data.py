import json
import os
from collections.abc import Generator
from time import sleep, time
from typing import Any

import pandas as pd
from elasticsearch import helpers
from flask_babel import gettext as _

from .. import app as flask_app, db, entry_types
from ..celery_app import app
from ..database import Dataset, Entry, LabelEntry, ProjectDataset, del_controled, register_entries
from ..functions import ensure_dir
from ..settings import ES_INDEX, ES_SERVER, UPLOAD_BATCH_SIZE, UPLOAD_PATH, WORK_PATH
from ..utils.es import create_index, get_es_conn


def cleanup_failed_dataset(dataset_id: int, user_id: int = 1) -> dict:
    """Clean up a failed dataset upload by removing dataset and associated entries."""
    try:
        with flask_app.app_context():
            # Get the dataset
            dataset = db.session.get(Dataset, dataset_id)
            if not dataset:
                return {"success": False, "error": "Dataset not found"}

            # Delete associated entries (hard delete since Entry doesn't inherit CreationControl)
            entries = (
                db.session.execute(db.select(Entry).filter_by(dataset_id=dataset_id))
                .scalars()
                .all()
            )

            entries_deleted = 0
            for entry in entries:
                # First delete any label associations
                label_entries = (
                    db.session.execute(
                        db.select(LabelEntry).filter_by(entry_id=entry.id, is_deleted=False)
                    )
                    .scalars()
                    .all()
                )

                for le in label_entries:
                    del_controled(le, user_id)

                # Then delete the entry itself
                db.session.delete(entry)
                entries_deleted += 1

            # Soft delete project associations
            project_datasets = (
                db.session.execute(
                    db.select(ProjectDataset).filter_by(dataset_id=dataset_id, is_deleted=False)
                )
                .scalars()
                .all()
            )

            associations_deleted = 0
            for pd in project_datasets:
                del_controled(pd, user_id)
                associations_deleted += 1

            # Soft delete the dataset
            del_controled(dataset, user_id)

            db.session.commit()

            return {
                "success": True,
                "entries_deleted": entries_deleted,
                "associations_deleted": associations_deleted,
            }

    except Exception as e:
        try:
            db.session.rollback()
        except:  # noqa
            pass
        return {"success": False, "error": str(e)}


def cleanup_elasticsearch_index(index_name: str) -> bool:
    """Clean up Elasticsearch index for failed dataset."""
    try:
        es = get_es_conn(hosts=ES_SERVER)
        if es.indices.exists(index=index_name):
            es.indices.delete(index=index_name)
        return True
    except Exception:
        return False


@app.task(bind=True, name="upload.process_batch")
def process_batch(
    self,
    batch_data: list[dict],
    dataset_id: int,
    entry_type: str,
    index_name: str,
    **kwargs,
) -> dict:
    """Process a batch of data through the entire pipeline"""
    try:
        # Extract IDs and texts
        ids = [entry["id"] for entry in batch_data]
        texts = {entry["id"]: entry["text"] for entry in batch_data}
        metadata = {entry["id"]: entry["metadata"] for entry in batch_data}

        # Check for duplicate IDs in this batch
        if len(ids) != len(set(ids)):
            duplicates = [id for id in set(ids) if ids.count(id) > 1]
            raise Exception(
                _(
                    "Duplicate text IDs found in batch: %(duplicates)s. "
                    "Each text must have a unique ID.",
                    duplicates=", ".join(duplicates),
                )
            )

        # Note: Called synchronously, so no task state updates

        # Executing upload steps on batches with detailed error tracking
        try:
            upload_to_elasticsearch(ids, texts, metadata, index_name)
        except Exception as e:
            raise Exception(
                _("Failed to upload data to search engine: %(error)s", error=str(e))
            ) from e

        try:
            db_result = register_batch_entries(ids, entry_type, dataset_id)
            if not db_result.get("success", False):
                # Extract the user-friendly error message directly
                user_error = db_result.get("error", _("Unknown database error"))
                raise Exception(user_error)
        except Exception as e:
            # Don't wrap the error if it's already user-friendly
            raise e

        try:
            store_texts_al(texts, dataset_id)
        except Exception as e:
            raise Exception(
                _("Failed to store texts for machine learning: %(error)s", error=str(e))
            ) from e

        return {"success": True, "batch_size": len(batch_data)}

    except Exception as e:
        # Check for specific database errors first
        error_str = str(e).lower()
        if (
            "uniqueviolation" in error_str
            or "duplicate key" in error_str
            or "unique constraint" in error_str
        ):
            # Extract the duplicate ID from the error message
            if "entry_id" in str(e):
                import re

                match = re.search(r"entry_id.*?=\(([^,)]+)", str(e))
                duplicate_id = match.group(1) if match else "unknown"
                raise Exception(
                    _(
                        "Duplicate text ID '%(id)s' found. "
                        "Each text must have a unique ID within the dataset.",
                        id=duplicate_id,
                    )
                ) from e
            else:
                raise Exception(
                    _(
                        "Duplicate text IDs found. Each text must "
                        "have a unique ID within the dataset."
                    )
                ) from e

        # If it's already a user-friendly message, pass it through
        elif not ("Traceback" in str(e) or 'File "' in str(e) or ".py" in str(e)):
            raise e from e

        # Otherwise wrap with generic message
        else:
            raise Exception(_("Processing failed: %(error)s", error=str(e))) from e


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
            doc = {
                "_index": index,
                "_id": entry_id,
                "_source": {"text": texts[entry_id]},
            }
            for key, value in metadata[entry_id].items():
                doc["_source"][key] = value
            yield doc

    # Perform bulk upload
    try:
        bulk_result = helpers.bulk(es, doc_generator())
        # helpers.bulk returns (success_count, errors_list) or just success_count
        if isinstance(bulk_result, tuple):
            success, errors = bulk_result
        else:
            success = bulk_result
            errors = []

        if errors:
            # Extract meaningful error messages for user
            error_details = []
            errors_to_check = errors[:3] if isinstance(errors, list) else []
            for error in errors_to_check:  # Show first 3 errors
                if isinstance(error, dict) and "index" in error:
                    error_info = error["index"]
                    if "error" in error_info and isinstance(error_info["error"], dict):
                        error_details.append(
                            error_info["error"].get("reason", str(error_info["error"]))
                        )

            error_summary = ", ".join(error_details) if error_details else str(errors)
            raise Exception(
                _(
                    "Failed to save data to search engine. Error details: %(errors)s",
                    errors=error_summary,
                )
            )

        return {"success": True, "documents_uploaded": success}

    except Exception as e:
        if "connection" in str(e).lower() or "timeout" in str(e).lower():
            raise Exception(
                _("Cannot connect to search engine. Please check your connection and try again.")
            ) from e
        elif "index" in str(e).lower() and "not found" in str(e).lower():
            raise Exception(_("Search engine index not found. Please contact support.")) from e
        else:
            raise Exception(_("Search engine error: %(error)s", error=str(e))) from e


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
        error_msg = str(e).lower()
        if "duplicate" in error_msg or "unique" in error_msg:
            return {
                "success": False,
                "error": _(
                    "Some text IDs already exist in the database. Please ensure all IDs are unique."
                ),
            }
        elif "foreign key" in error_msg or "dataset" in error_msg:
            return {
                "success": False,
                "error": _("Dataset not found. Please refresh the page and try again."),
            }
        elif "connection" in error_msg or "database" in error_msg:
            return {
                "success": False,
                "error": _("Database connection error. Please try again in a moment."),
            }
        else:
            return {"success": False, "error": _("Database error: %(error)s", error=str(e))}


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
    try:
        with file_path.open("a") as f:
            for entry_id, text in texts_dict.items():
                json_line = json.dumps({"id": entry_id, "text": text})
                f.write(json_line + "\n")

        return {"success": True, "path": str(file_path), "entries_stored": len(texts_dict)}

    except PermissionError as e:
        raise Exception(
            _("Permission denied while saving texts. Please check file permissions.")
        ) from e
    except OSError as e:
        if "No space left" in str(e):
            raise Exception(
                _("Not enough disk space to save texts. Please free up space and try again.")
            ) from e
        else:
            raise Exception(
                _("File system error while saving texts: %(error)s", error=str(e))
            ) from e
    except Exception as e:
        raise Exception(
            _("Failed to save texts for machine learning: %(error)s", error=str(e))
        ) from e


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

    # Load CSV options from dataset record
    dataset_record = db.session.get(Dataset, dataset_id)
    if dataset_record:
        upload_params["sep"] = dataset_record.sep
        upload_params["encoding"] = dataset_record.encoding

    # Check if JSONL file already exists and backup if needed
    dataset_dir = WORK_PATH / "datasets"
    dataset_dir.mkdir(parents=True, exist_ok=True)
    jsonl_file = dataset_dir / f"{dataset_id}.jsonl"

    if jsonl_file.exists():
        from datetime import datetime

        backup_name = f"{dataset_id}.jsonl.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        backup_path = dataset_dir / backup_name
        jsonl_file.rename(backup_path)
        print(f"WARNING: Existing JSONL file found and moved to {backup_name}")

    try:
        # Create batch generator
        try:
            if not hasattr(entry_types, upload_type):
                raise Exception(
                    _("Invalid data format selected. Please refresh the page and try again.")
                )

            type_module = getattr(entry_types, upload_type)
            if not hasattr(type_module, "generate_upload_batches"):
                raise Exception(
                    _("Data format '%(format)s' is not supported for upload.", format=upload_type)
                )

            batch_generator = type_module.generate_upload_batches(
                batch_size=UPLOAD_BATCH_SIZE,
                **upload_params,
            )
        except Exception:
            raise

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
                error_msg = result.get("error", _("Unknown error occurred"))
                # Don't wrap if it's already a user-friendly message
                if not ("Traceback" in error_msg or 'File "' in error_msg or ".py" in error_msg):
                    raise Exception(error_msg)
                else:
                    raise Exception(
                        _(
                            "Processing failed at batch %(batch)d: %(error)s",
                            batch=batch_count,
                            error=error_msg,
                        )
                    )

        return {
            "success": True,
            "total_records": total_records,
            "batches_processed": batch_count,
            "batch_results": processed_batches,
        }

    except Exception as e:
        # Upload failed - clean up the dataset and associated data
        self.update_state(
            state="PROGRESS", meta={"status": _("Upload failed. Cleaning up dataset...")}
        )

        # Clean up database entries and dataset
        cleanup_result = cleanup_failed_dataset(dataset_id)

        # Clean up Elasticsearch index
        cleanup_elasticsearch_index(index_name)

        # Clean up uploaded file if it exists
        try:
            filename = upload_params.get("filename")
            if filename and os.path.exists(filename):
                os.remove(filename)
        except:  # noqa
            pass  # File cleanup is not critical

        # Extract user-friendly error message
        original_error = str(e)

        # If it's already a clean user message, use it directly
        if not (
            "Traceback" in original_error or 'File "' in original_error or ".py" in original_error
        ):
            user_message = original_error
        else:
            # Extract just the final exception message
            lines = original_error.split("\n")
            for line in reversed(lines):
                if line.strip() and not line.startswith(" ") and ":" in line:
                    user_message = line.split(":", 1)[-1].strip()
                    break
            else:
                user_message = _("Upload processing failed")

        # Add cleanup information to the clean message
        if cleanup_result.get("success", False):
            final_message = _(
                "%(error)s. Dataset and associated data have been cleaned up.", error=user_message
            )
        else:
            final_message = _(
                "%(error)s. Warning: Dataset cleanup may have been incomplete.", error=user_message
            )

        raise Exception(final_message) from e


@app.task(bind=True, name="upload.save_chunk")
def save_chunk(
    self,
    chunk: bytes,
    chunk_number: int,
    file_id: str,
    **kwargs,
) -> dict:
    # Save chunk
    chunk_dir = UPLOAD_PATH / file_id
    ensure_dir(chunk_dir)

    chunk_path = chunk_dir / f"{chunk_number:04d}"
    with open(chunk_path, "wb") as f:
        f.write(chunk)

    return {
        "success": True,
    }


@app.task(bind=True, name="upload.finalize_upload")
def finalize_chunks_upload(
    self,
    file_id: str,
    filename: str,
    total_chunks: int,
    sep: str = ",",
    encoding: str = "utf-8",
    **kwargs,
) -> dict:
    chunk_dir = UPLOAD_PATH / file_id
    chunks = sorted(chunk_dir.glob("*"))

    # Wait for all chunks to arrive with a timeout of 60 seconds
    start_time = time()
    while time() - start_time < 360:
        chunks = list(chunk_dir.glob("*"))
        if len(chunks) == total_chunks:
            break
        sleep(1)

    if len(chunks) != total_chunks:
        raise Exception(
            _(
                "File upload incomplete. Only %(received)d of %(total)d parts "
                "received. Please try uploading again.",
                received=len(chunks),
                total=total_chunks,
            )
        )

    # Sort the chunks to ensure correct order
    chunks.sort()

    try:
        with open(filename, "wb") as output:
            for chunk in chunks:
                with open(chunk, "rb") as f:
                    output.write(f.read())
                chunk.unlink()  # Remove processed chunk

        # Read columns from the first few rows of the CSV
        try:
            read_kwargs: dict = {"nrows": 1, "sep": sep, "encoding": encoding}
            if len(sep) > 1:
                read_kwargs["engine"] = "python"
            columns = list(pd.read_csv(filename, **read_kwargs).columns)

            # Validate CSV structure
            if not columns:
                raise Exception(_("CSV file appears to be empty or has no columns."))

            return {
                "success": True,
                "columns": columns,
            }

        except pd.errors.EmptyDataError as e:
            raise Exception(_("CSV file is empty. Please upload a file with data.")) from e
        except pd.errors.ParserError as e:
            raise Exception(
                _(
                    "Could not read the CSV with separator '%(sep)s'. "
                    "Please check the advanced options.",
                    sep=sep,
                )
            ) from e
        except UnicodeDecodeError as e:
            raise Exception(
                _(
                    "Encoding error reading the file with '%(encoding)s'. "
                    "Please try a different encoding in the advanced options.",
                    encoding=encoding,
                )
            ) from e
        except Exception as e:
            if "No such file" in str(e):
                raise Exception(_("Uploaded file not found. Please try uploading again.")) from e
            else:
                raise self.retry(countdown=2, exc=e) from e
    except Exception as e:
        raise self.retry(countdown=2, exc=e) from e
