import csv
import json
import os
import re
from collections.abc import Callable, Generator
from datetime import datetime
from pathlib import Path
from time import sleep, time
from typing import Any

import pandas as pd
from charset_normalizer import from_bytes
from elasticsearch import helpers
from flask_babel import gettext as _

from .. import app as flask_app, entry_types
from ..celery_app import app
from ..database import (
    check_entries_exist,
    cleanup_dataset,
    delete_new_entries,
    get_dataset,
    register_entries,
    update_dataset,
)
from ..settings import ES_INDEX, ES_SERVER, UPLOAD_BATCH_SIZE, UPLOAD_PATH, WORK_PATH
from ..utils.es import create_index, get_es_conn


def cleanup_failed_dataset(dataset_id: int, user_id: int = 1) -> dict:
    """Clean up a failed dataset upload by removing dataset and associated entries."""
    with flask_app.app_context():
        return cleanup_dataset(dataset_id, user_id)


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
    append: bool = False,
    dataset_layout: dict[str, Any] | None = None,
    **kwargs,
) -> dict:
    """Orchestrate dataset upload in batches without full memory load

    Args:
        upload_params: Dictionary containing:
            - filename: Path to CSV file
            - id_column: Name of ID column
            - text_column: Name of text column
            - sep / encoding: Optional CSV options (default: dataset's)
        dataset_id: ID of dataset to associate with
        append: Add entries to an existing dataset. On failure only the
            entries added by this run are removed.
        dataset_layout: Optional id_column/text_column/columns to store on the
            dataset after a successful append (legacy datasets).
    """
    # Create Elasticsearch index
    index_name = ES_INDEX.format(dataset_id=dataset_id)
    create_index(index_name)

    # Load CSV options from dataset record unless the caller set them for this file
    with flask_app.app_context():
        dataset_record = get_dataset(dataset_id)
        if dataset_record:
            upload_params.setdefault("sep", dataset_record.sep)
            upload_params.setdefault("encoding", dataset_record.encoding)

    # Check if JSONL file already exists and backup if needed
    dataset_dir = WORK_PATH / "datasets"
    dataset_dir.mkdir(parents=True, exist_ok=True)
    jsonl_file = dataset_dir / f"{dataset_id}.jsonl"

    # Appending keeps existing texts; remember where the new ones start for rollback
    jsonl_start_size = jsonl_file.stat().st_size if jsonl_file.exists() else 0
    appended_ids: list[str] = []

    if jsonl_file.exists() and not append:
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
            if append:
                appended_ids.extend(entry["id"] for entry in batch)
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

        if append:
            if dataset_layout:
                with flask_app.app_context():
                    update_dataset(dataset_id, **dataset_layout)
            _remove_file(upload_params.get("filename"))

        return {
            "success": True,
            "total_records": total_records,
            "batches_processed": batch_count,
            "batch_results": processed_batches,
        }

    except Exception as e:
        if append:
            self.update_state(
                state="PROGRESS", meta={"status": _("Upload failed. Removing added entries...")}
            )
            rollback_ok = rollback_append(dataset_id, appended_ids, index_name, jsonl_start_size)
            _remove_file(upload_params.get("filename"))
            if rollback_ok:
                raise Exception(
                    _(
                        "%(error)s. No entries were added; the existing data was kept.",
                        error=_user_message(e),
                    )
                ) from e
            raise Exception(
                _(
                    "%(error)s. Warning: some of the new entries may not have been removed.",
                    error=_user_message(e),
                )
            ) from e

        # Upload failed - clean up the dataset and associated data
        self.update_state(
            state="PROGRESS", meta={"status": _("Upload failed. Cleaning up dataset...")}
        )

        # Clean up database entries and dataset
        cleanup_result = cleanup_failed_dataset(dataset_id)

        # Clean up Elasticsearch index
        cleanup_elasticsearch_index(index_name)

        # Clean up uploaded file if it exists
        _remove_file(upload_params.get("filename"))

        user_message = _user_message(e)

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


def _remove_file(filename: str | None) -> None:
    """Remove an uploaded file, ignoring errors (cleanup is not critical)."""
    try:
        if filename and os.path.exists(filename) and Path(filename).is_relative_to(UPLOAD_PATH):
            os.remove(filename)
    except Exception:
        pass


def _user_message(e: Exception) -> str:
    """Extract a user-friendly message from an exception."""
    original_error = str(e)

    # If it's already a clean user message, use it directly
    if not ("Traceback" in original_error or 'File "' in original_error or ".py" in original_error):
        return original_error

    # Extract just the final exception message
    for line in reversed(original_error.split("\n")):
        if line.strip() and not line.startswith(" ") and ":" in line:
            return line.split(":", 1)[-1].strip()
    return _("Upload processing failed")


def rollback_append(
    dataset_id: int, entry_ids: list[str], index_name: str, jsonl_size: int
) -> bool:
    """Undo a failed append: remove the new entries from the DB, ES and JSONL file."""
    ok = True
    if entry_ids:
        try:
            with flask_app.app_context():
                delete_new_entries(entry_ids, dataset_id)
        except Exception:
            ok = False
        try:
            es = get_es_conn(hosts=ES_SERVER, request_timeout=120)
            for start in range(0, len(entry_ids), UPLOAD_BATCH_SIZE):
                es.delete_by_query(
                    index=index_name,
                    query={"ids": {"values": entry_ids[start : start + UPLOAD_BATCH_SIZE]}},
                    refresh=True,
                    conflicts="proceed",
                )
        except Exception:
            ok = False

    jsonl_file = WORK_PATH / "datasets" / f"{dataset_id}.jsonl"
    try:
        if jsonl_file.exists() and jsonl_file.stat().st_size > jsonl_size:
            with jsonl_file.open("r+b") as f:
                f.truncate(jsonl_size)
    except Exception:
        ok = False
    return ok


def read_csv_ids(
    filename: str, id_column: str, sep: str, encoding: str, batch_size: int = UPLOAD_BATCH_SIZE
) -> tuple[list[str], int]:
    """Read the ID column of a CSV the same way ``generate_upload_batches`` does.

    Reading in chunks of the same size keeps pandas' dtype inference (and so the
    ``str()`` form of numeric IDs) identical to what the upload will store.

    Returns:
        (ids, empty_count) where ids keeps file order, duplicates included
    """
    read_kwargs: dict = {"chunksize": batch_size, "sep": sep, "encoding": encoding}
    if len(sep) > 1:
        read_kwargs["engine"] = "python"

    ids: list[str] = []
    empty = 0
    for chunk in pd.read_csv(filename, **read_kwargs):
        chunk = chunk.fillna(-1)
        for value in chunk[id_column].tolist():
            if not value or value == -1 or str(value).strip() == "":
                empty += 1
                continue
            ids.append(str(value))
    return ids, empty


def check_append_file(
    columns: list[str],
    expected_columns: list[str],
    ids: list[str],
    empty_ids: int,
    existing_ids: Callable[[list[str]], list[str]],
    sample_size: int = 20,
) -> dict:
    """Check a file to be appended against a dataset.

    Args:
        columns: Header of the new file
        expected_columns: Header the dataset was created with
        ids: IDs read from the new file (file order, duplicates included)
        empty_ids: Number of rows without an ID
        existing_ids: Callback returning which of the given IDs already exist

    Returns:
        Validation report; ``ok`` is True only if every check passed
    """
    missing_columns = [c for c in expected_columns if c not in columns]
    unexpected_columns = [c for c in columns if c not in expected_columns]

    seen: set[str] = set()
    duplicates: dict[str, None] = {}
    for entry_id in ids:
        if entry_id in seen:
            duplicates[entry_id] = None
        seen.add(entry_id)

    unique_ids = list(dict.fromkeys(ids))
    existing: list[str] = []
    for start in range(0, len(unique_ids), UPLOAD_BATCH_SIZE):
        existing.extend(existing_ids(unique_ids[start : start + UPLOAD_BATCH_SIZE]))
    existing_set = set(existing)
    existing = [entry_id for entry_id in unique_ids if entry_id in existing_set]

    report = {
        "missing_columns": missing_columns,
        "unexpected_columns": unexpected_columns,
        "duplicate_ids": {"count": len(duplicates), "sample": list(duplicates)[:sample_size]},
        "existing_ids": {"count": len(existing), "sample": existing[:sample_size]},
        "empty_ids": empty_ids,
        "new_entries": len(unique_ids) - len(existing),
    }
    report["ok"] = not (
        missing_columns or unexpected_columns or duplicates or existing or empty_ids
    ) and bool(unique_ids)
    return report


@app.task(bind=True, name="upload.validate_append")
def validate_append(
    self,
    dataset_id: int,
    filename: str,
    columns: list[str],
    expected_columns: list[str],
    id_column: str,
    sep: str,
    encoding: str,
    **kwargs,
) -> dict:
    """Check a CSV against an existing dataset before appending it."""
    if id_column not in columns:
        ids, empty = [], 0
    else:
        try:
            ids, empty = read_csv_ids(filename, id_column, sep, encoding)
        except FileNotFoundError as e:
            raise Exception(_("Uploaded file not found. Please try uploading again.")) from e

    def existing_ids(chunk: list[str]) -> list[str]:
        with flask_app.app_context():
            return check_entries_exist(chunk, dataset_id)[0]

    return check_append_file(columns, expected_columns, ids, empty, existing_ids)


def update_entries(dataset_id: int, changes: dict[str, dict[str, Any]]) -> list[dict[str, str]]:
    """Partially update entry documents in ES and keep the ML text file in sync.

    Args:
        dataset_id: Dataset the entries belong to
        changes: {entry_id: {field: value}}

    Returns:
        List of {entry_id, error} for documents that failed to update
    """
    index_name = ES_INDEX.format(dataset_id=dataset_id)
    es = get_es_conn(hosts=ES_SERVER, request_timeout=120)
    actions = [
        {"_op_type": "update", "_index": index_name, "_id": entry_id, "doc": fields}
        for entry_id, fields in changes.items()
    ]
    _, errors = helpers.bulk(es, actions, raise_on_error=False, refresh="wait_for")

    failed: list[dict[str, str]] = []
    for error in errors if isinstance(errors, list) else []:
        info = error.get("update", {})
        reason = info.get("error", {})
        if isinstance(reason, dict):
            reason = reason.get("reason", str(reason))
        failed.append({"entry_id": str(info.get("_id")), "error": str(reason)})

    failed_ids = {f["entry_id"] for f in failed}
    texts = {
        entry_id: str(fields["text"])
        for entry_id, fields in changes.items()
        if "text" in fields and entry_id not in failed_ids
    }
    if texts:
        rewrite_texts_al(texts, dataset_id)
    return failed


def rewrite_texts_al(texts_dict: dict[str, str], dataset_id: int) -> int:
    """Replace the text of existing entries in the dataset's JSON Lines file.

    Streams into a temporary file and atomically swaps it in.

    Returns:
        Number of lines rewritten
    """
    file_path = WORK_PATH / "datasets" / f"{dataset_id}.jsonl"
    if not file_path.exists():
        return 0

    tmp_path = file_path.with_suffix(".jsonl.tmp")
    rewritten = 0
    with file_path.open() as src, tmp_path.open("w") as dst:
        for line in src:
            stripped = line.strip()
            if stripped:
                record = json.loads(stripped)
                if record.get("id") in texts_dict:
                    record["text"] = texts_dict[record["id"]]
                    line = json.dumps(record) + "\n"
                    rewritten += 1
            dst.write(line)
    os.replace(tmp_path, file_path)
    return rewritten


_ENCODING_ALIASES: dict[str, str] = {
    "utf-8": "utf-8",
    "utf_8": "utf-8",
    "utf-8-sig": "utf-8",
    "ascii": "utf-8",
    "latin-1": "latin-1",
    "latin_1": "latin-1",
    "iso-8859-1": "latin-1",
    "iso8859-1": "latin-1",
    "iso_8859_1": "latin-1",
    "cp1252": "cp1252",
    "windows-1252": "cp1252",
    "windows_1252": "cp1252",
}


def _detect_csv_options(filename: str, sample_size: int = 32768) -> tuple[str, str]:
    """Detect encoding and separator from the first bytes of a CSV file."""
    with open(filename, "rb") as f:
        raw = f.read(sample_size)

    # Detect encoding via charset-normalizer
    best = from_bytes(raw).best()
    raw_encoding = str(best.encoding) if best else "utf-8"
    encoding = _ENCODING_ALIASES.get(raw_encoding, "utf-8")

    # Detect separator via stdlib sniffer
    try:
        sample_text = raw.decode(encoding, errors="replace")
        dialect = csv.Sniffer().sniff(sample_text, delimiters=",;\t|")
        sep = dialect.delimiter
    except (csv.Error, UnicodeDecodeError):
        sep = ","

    return sep, encoding


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
    final_path = Path(filename)

    if not final_path.exists():
        # Wait for all chunks to arrive with a timeout of 360 seconds
        start_time = time()
        while time() - start_time < 360:
            chunks = list(chunk_dir.glob("*"))
            if len(chunks) == total_chunks:
                break
            sleep(1)

        chunks = list(chunk_dir.glob("*"))
        if len(chunks) != total_chunks:
            raise Exception(
                _(
                    "File upload incomplete. Only %(received)d of %(total)d parts "
                    "received. Please try uploading again.",
                    received=len(chunks),
                    total=total_chunks,
                )
            )

        chunks.sort()

        try:
            with open(filename, "wb") as output:
                for chunk in chunks:
                    with open(chunk, "rb") as f:
                        output.write(f.read())
                    chunk.unlink()  # Remove processed chunk
        except OSError as e:
            raise self.retry(countdown=2, exc=e) from e

    # Auto-detect sep/encoding when the caller is using defaults
    if sep == "," and encoding == "utf-8":
        try:
            sep, encoding = _detect_csv_options(filename)
        except Exception:
            pass  # Keep defaults on detection failure

    # Read columns from the first few rows of the CSV
    try:
        read_kwargs: dict = {"nrows": 1, "sep": sep, "encoding": encoding}
        if len(sep) > 1:
            read_kwargs["engine"] = "python"
        columns = list(pd.read_csv(filename, **read_kwargs).columns)

        if not columns:
            raise Exception(_("CSV file appears to be empty or has no columns."))

        return {
            "success": True,
            "columns": columns,
            "sep": sep,
            "encoding": encoding,
        }

    except pd.errors.EmptyDataError as e:
        raise Exception(_("CSV file is empty. Please upload a file with data.")) from e
    except pd.errors.ParserError:
        return {
            "success": False,
            "error": _(
                "Could not read the CSV with separator '%(sep)s'. Try a different separator.",
                sep=sep,
            ),
            "can_retry": True,
        }
    except UnicodeDecodeError:
        return {
            "success": False,
            "error": _(
                "Encoding error reading the file with '%(encoding)s'. Try a different encoding.",
                encoding=encoding,
            ),
            "can_retry": True,
        }
    except Exception as e:
        if "No such file" in str(e):
            raise Exception(_("Uploaded file not found. Please try uploading again.")) from e
        else:
            raise self.retry(countdown=2, exc=e) from e
