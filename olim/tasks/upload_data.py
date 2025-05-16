from pathlib import Path

import click

from .. import app as flask_app
from ..celery_app import app
from ..entry_types.patient import up_patients
from ..entry_types.single_text import up_single_text


@app.task(bind=True)
def upload_to_elasticsearch(
    self,
    upload_type: str,
    filename: str | Path,
    dataset_id: int,
    text_id: str | None = None,
    text: str | None = None,
) -> dict:
    """
    Handle file upload to Elasticsearch
    """
    temp_dir = None

    try:
        if upload_type == "patient_sheet":
            up_func = up_patients
            params = {"csv_file": filename, "dataset_id": dataset_id}
        elif upload_type == "simple_text":
            up_func = up_single_text
            params = {
                "csv_file": filename,
                "id_column": text_id,
                "text_column": text,
                "dataset_id": dataset_id,
            }
        elif upload_type == "sample_data":
            up_func = up_single_text
            params = {
                "csv_file": filename,
                "id_column": "text_id",
                "text_column": "text",
                "dataset_id": dataset_id,
            }
        else:
            raise ValueError(f"Unknown upload type: {upload_type}")

        with flask_app.app_context():
            with click.Context(up_func) as ctx:
                ctx.invoke(up_func, **params)

        return {
            "success": True,
            "filename": filename,
            "temp_dir": temp_dir.name if temp_dir else None,
            "errors": None,
        }

    except Exception as e:
        return {
            "success": False,
            "filename": filename,
            "temp_dir": temp_dir.name if temp_dir else None,
            "errors": [str(e)],
        }


@app.task
def update_database(upload_result: dict) -> dict:
    """
    Update database based on upload results
    """
    try:
        if not upload_result["success"]:
            raise ValueError(f"Previous task failed: {upload_result['errors']}")

        # TODO: implement the database filling with the ids
        return {"success": True, "errors": None}

    except Exception as e:
        return {"success": False, "errors": [str(e)]}


def start_upload_chain(
    upload_type: str,
    filename: str,
    dataset_id: int,
    text_id: str | None = None,
    text: str | None = None,
) -> str:
    """
    Helper function to start the upload task chain
    Returns the chain's task ID
    """
    result = (
        upload_to_elasticsearch.s(upload_type, filename, dataset_id, text_id, text)
        | update_database.s()
    )()
    return result.id
