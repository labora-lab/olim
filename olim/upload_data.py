from pathlib import Path

from celery.result import AsyncResult
from flask import flash, jsonify, redirect, render_template, request, session
from flask_babel import _

from . import app
from .database import get_dataset_stats, get_datasets, link_dataset_to_project, new_dataset
from .settings import ALLOWED_EXTENSIONS, CHUNK_SIZE, MAX_FILE_SIZE, UPLOAD_FOLDER
from .tasks.upload_data import start_upload_chain

ACTIVE_TASKS = set()
COMPLETED_TASKS = {}


@app.route("/task-status")
def check_task_status() -> ...:
    """Check and return the status of all tracked tasks"""
    status_updates = {}

    for task_id in list(ACTIVE_TASKS):
        result = AsyncResult(task_id)
        if result.ready():
            ACTIVE_TASKS.remove(task_id)
            task_result = (
                result.result
                if result.successful()
                else {"success": False, "errors": [str(result.result)]}
            )
            success = task_result.get("success", False)
            errors = task_result.get("errors", [])

            COMPLETED_TASKS[task_id] = {"success": success, "errors": errors}

    status_updates = {"active": list(ACTIVE_TASKS), "completed": COMPLETED_TASKS}

    return jsonify(status_updates)


def ensure_dir(path) -> None:
    Path(path).mkdir(parents=True, exist_ok=True)


@app.route("/upload/large-file", methods=["POST"])
def handle_large_upload() -> ...:
    # Get chunk metadata
    chunk_number = int(request.form["chunkNumber"])
    total_chunks = int(request.form["totalChunks"])
    file_id = request.form["fileId"]
    file_name = request.form["fileName"]

    # Validate input
    if not all([file_id, file_name]):
        return jsonify(error="Invalid request"), 400

    # Security checks
    if "." in file_name and file_name.rsplit(".", 1)[1].lower() not in ALLOWED_EXTENSIONS:
        return jsonify(error="Invalid file type"), 400

    if total_chunks * CHUNK_SIZE > MAX_FILE_SIZE:
        return jsonify(error="File too large"), 413

    # Save chunk
    chunk = request.files["file"]
    chunk_dir = Path(UPLOAD_FOLDER) / file_id
    ensure_dir(chunk_dir)

    chunk_path = chunk_dir / f"{chunk_number:04d}"
    chunk.save(chunk_path)

    return jsonify(success=True)


@app.route("/upload/finalize/<file_id>", methods=["GET"])
def finalize_upload(file_id) -> ...:
    try:
        # Reconstruct file
        chunk_dir = Path(UPLOAD_FOLDER) / file_id
        chunks = sorted(chunk_dir.glob("*"))

        if not chunks:
            return jsonify(error="No chunks found"), 400

        original_name = request.args.get("filename")
        final_path = Path(UPLOAD_FOLDER) / f"{file_id}_{original_name}"

        with open(final_path, "wb") as output:
            for chunk in chunks:
                with open(chunk, "rb") as f:
                    output.write(f.read())
                chunk.unlink()

        return jsonify(success=True, path=str(final_path))

    except Exception as e:
        return jsonify(error=str(e)), 500


@app.route("/upload-data", methods=["GET", "POST"])
def upload_data() -> ...:
    """Handle file uploads using celery tasks"""
    if request.method == "POST":
        upload_type = request.form.get("upload_type")
        if upload_type is None:
            raise NotImplementedError
        text_id = request.form.get("text_id")
        text = request.form.get("text")
        dataset_name = request.form.get("name")
        projects = [int(p) for p in request.form.getlist("projects")]
        filename = request.form.get("filename")
        file_id = request.form.get("file_id")

        if not filename and upload_type != "sample_data":
            flash(_("Error uploading file."), category="error")
            return redirect(request.url)
        filename = str(Path(UPLOAD_FOLDER) / f"{file_id}_{filename}")

        dataset = new_dataset(dataset_name, session["user_id"])

        for project_id in projects:
            link_dataset_to_project(dataset.id, project_id, session["user_id"])

        # try:
        # Handle sample data upload
        if upload_type == "sample_data":
            task_params = {
                "upload_type": upload_type,
                "filename": "./data/sample_data.csv",
                "dataset_id": dataset.id,
            }
        else:
            # Handle other types of upload
            if upload_type == "simple_text":
                if not text_id or not text:
                    flash(
                        _("Missing text_id or text for text format upload"),
                        category="error",
                    )
                    return redirect(request.url)

            # Validate file upload
            if not filename:
                flash(_("No file selected"), category="error")
                return redirect(request.url)

            task_params = {
                "upload_type": upload_type,
                "filename": filename,
                "text_id": text_id,
                "text": text,
                "dataset_id": dataset.id,
            }

        # Start celery task chain
        try:
            task_id = start_upload_chain(**task_params)
        except Exception as e:
            flash(
                _("Error starting upload task: {error}").format(error=str(e)),
                category="error",
            )
            return redirect(request.url)
        if task_id:
            ACTIVE_TASKS.add(task_id)
            return redirect(request.url)  # This fix a small bug in initial setup (nano)

    return render_template(
        "upload-data.html",
        active_tasks=list(ACTIVE_TASKS),
        completed_tasks=COMPLETED_TASKS,
        CHUNK_SIZE=CHUNK_SIZE,
        datasets=get_datasets(non_empty=True),
        stats=get_dataset_stats(),
    )
