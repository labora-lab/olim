from pathlib import Path

from flask import flash, jsonify, redirect, render_template, request, session, url_for
from flask_babel import _

from . import app
from .celery_app import launch_task_with_tracking
from .database import get_dataset_stats, get_datasets, link_dataset_to_project, new_dataset
from .functions import check_is_setup
from .settings import ALLOWED_EXTENSIONS, CHUNK_SIZE, MAX_FILE_SIZE, UPLOAD_PATH
from .tasks.upload_data import upload_dataset


@app.route("/task-list")
def check_task_status() -> ...:
    """Check and return the status of all tracked tasks"""

    return render_template("task-list.html")


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
    chunk_dir = UPLOAD_PATH / file_id
    ensure_dir(chunk_dir)

    chunk_path = chunk_dir / f"{chunk_number:04d}"
    chunk.save(chunk_path)

    return jsonify(success=True)


@app.route("/upload/finalize/<file_id>", methods=["GET"])
def finalize_upload(file_id) -> ...:
    try:
        # Reconstruct file
        chunk_dir = UPLOAD_PATH / file_id
        chunks = sorted(chunk_dir.glob("*"))

        if not chunks:
            return jsonify(error="No chunks found"), 400

        original_name = request.args.get("filename")
        final_path = UPLOAD_PATH / f"{file_id}_{original_name}"

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
    """
    Handle file uploads and dataset creation using Celery tasks

    Methods:
        GET: Render upload form with dataset statistics
        POST: Process form data and start upload task chain

    Returns:
        GET: Rendered upload-data.html template
        POST: Redirect to same page with flash messages or error handling
    """
    # If not setup and GET we need to go back to init-config
    if request.method == "GET" and not check_is_setup():
        return redirect(url_for("init_config"))

    if request.method == "POST":
        # Extract form data
        upload_type = request.form.get("upload_type")
        dataset_name = request.form.get("name")
        projects = request.form.getlist("projects")
        filename = request.form.get("filename")
        file_id = request.form.get("file_id")

        # Validate required fields
        if not upload_type:
            flash(_("Upload type is required"), "error")
            if not check_is_setup():
                return redirect(url_for("init_config"))
            else:
                return redirect(request.url)

        if not dataset_name:
            flash(_("Dataset name is required"), "error")
            if not check_is_setup():
                return redirect(url_for("init_config"))
            else:
                return redirect(request.url)

        # Create new dataset
        try:
            dataset = new_dataset(dataset_name, session["user_id"])

            # Link to selected projects
            for project_id in projects:
                link_dataset_to_project(dataset.id, int(project_id), session["user_id"])
        except Exception as e:
            flash(_("Error creating dataset: {error}").format(error=str(e)), "error")
            if not check_is_setup():
                return redirect(url_for("init_config"))
            else:
                return redirect(request.url)

        # Prepare upload parameters
        upload_params = {
            "id_column": request.form.get("id_column"),
            "text_column": request.form.get("text_column"),
        }

        # Handle sample data specially
        if upload_type == "sample_data":
            upload_type = "single_text"
            upload_params.update(
                {
                    "filename": "./data/sample_data.csv",
                    "id_column": "text_id",
                    "text_column": "text",
                }
            )
            upload_type = "single_text"
        else:
            # Validate file upload for non-sample data
            if not filename or not file_id:
                flash(_("File upload incomplete"), "error")
                return redirect(request.url)

            # Construct actual file path
            upload_params["filename"] = str(UPLOAD_PATH / f"{file_id}_{filename}")

            # Validate required columns for single_text format
            if upload_type == "single_text":
                if not upload_params["id_column"] or not upload_params["text_column"]:
                    flash(_("ID and Text columns are required"), "error")
                    return redirect(request.url)

        # Start upload task chain
        try:
            launch_task_with_tracking(
                upload_dataset,
                description=_("Uploading and processing file {filename}").format(
                    filename=upload_params.get("filename", "").split("/")[-1]
                ),
                upload_type=upload_type,
                upload_params=upload_params,
                dataset_id=dataset.id,
                user_id=session["user_id"],
                track_progress=True,
            )

            flash(_("Document processing started successfully"), "success")
            return redirect(request.url)

        except Exception as e:
            flash(_("Error starting upload: {error}").format(error=str(e)), "error")
            return redirect(request.url)

    # GET request - render form
    return render_template(
        "upload-data.html",
        CHUNK_SIZE=CHUNK_SIZE,
        datasets=get_datasets(non_empty=True),
        stats=get_dataset_stats(),
    )
