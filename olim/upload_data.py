from flask import flash, jsonify, redirect, render_template, request, session, url_for
from flask_babel import _

from . import app
from .celery_app import launch_task_with_tracking
from .database import (
    get_celery_tasks,
    get_dataset_stats,
    get_datasets,
    get_projects,
    link_dataset_to_project,
    new_dataset,
)
from .functions import check_is_setup
from .project import update_session_project
from .settings import ALLOWED_EXTENSIONS, CHUNK_SIZE, MAX_FILE_SIZE, UPLOAD_PATH
from .tasks.upload_data import finalize_chunks_upload, save_chunk, upload_dataset


@app.before_request  # type: ignore
def add_tasks() -> ...:
    if check_is_setup():
        app.jinja_env.globals.update(tasks=get_celery_tasks())


@app.route("/task-list")
def task_list() -> ...:
    """Check and return the status of all tracked tasks"""

    return render_template("task-list.html")


@app.route("/upload/chunk", methods=["POST"])
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
    if (
        "." in file_name
        and file_name.rsplit(".", 1)[1].lower() not in ALLOWED_EXTENSIONS
    ):
        return jsonify(error="Invalid file type"), 400

    if total_chunks * CHUNK_SIZE > MAX_FILE_SIZE:
        return jsonify(error="File too large"), 413

    chunk = request.files["file"].read()

    launch_task_with_tracking(
        save_chunk,
        chunk=chunk,
        chunk_number=chunk_number,
        file_id=file_id,
        user_id=session["user_id"],
        track_progress=False,
    )

    return jsonify(success=True)


@app.route("/upload/finalize/<file_id>", methods=["GET"])
def finalize_upload(file_id) -> ...:
    filename = request.args.get("filename")
    total_chunks = request.args.get("total_chunks")
    final_path = UPLOAD_PATH / f"{file_id}_{filename}"

    res = launch_task_with_tracking(
        finalize_chunks_upload,
        file_id=file_id,
        filename=str(final_path),
        total_chunks=int(total_chunks),  # type: ignore
        user_id=session["user_id"],
        track_progress=False,
    )

    columns = res.get()["columns"]

    return jsonify(success=True, path=str(final_path), columns=columns)


@app.route("/upload-data", methods=["GET", "POST"])
@app.route("/upload-data/<int:project_id>", methods=["GET", "POST"])
def upload_data(project_id: int | None = None) -> ...:
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

    # Handle project_id parameter - check project and update session if provided
    if project_id is not None:
        res = update_session_project(project_id)
        if res is not None:
            return res

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

        # Add PDF URL column for text_pdf_url format
        if upload_type == "text_pdf_url":
            upload_params["pdf_url_column"] = request.form.get("pdf_url_column")

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

            # Validate required columns for text_pdf_url format
            if upload_type == "text_pdf_url":
                if (
                    not upload_params["id_column"]
                    or not upload_params["text_column"]
                    or not upload_params["pdf_url_column"]
                ):
                    flash(_("ID, Text, and PDF URL columns are required"), "error")
                    return redirect(request.url)

        # Start upload task chain
        try:
            filename = "_".join(upload_params.get("filename", "").split("/")[-1].split("_")[1:])  # type: ignore
            launch_task_with_tracking(
                upload_dataset,
                description=_("Uploading and processing file {filename}").format(
                    filename=filename
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
        projects=list(get_projects()),
    )
