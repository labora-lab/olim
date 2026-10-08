import json

import pandas as pd
from flask import flash, jsonify, redirect, render_template, request, session, url_for
from flask_babel import _

from . import app
from .celery_app import launch_task_with_tracking
from .database import (
    get_celery_tasks,
    link_dataset_to_project,
    new_dataset,
)
from .entry_types.flexible_text import normalize_column_config
from .functions import check_is_setup, ensure_dir
from .project import update_session_project
from .settings import ALLOWED_EXTENSIONS, CHUNK_SIZE, MAX_FILE_SIZE, UPLOAD_PATH
from .tasks.upload_data import column_field, finalize_chunks_upload, upload_dataset

ALLOWED_ENCODINGS = {"utf-8", "latin-1", "cp1252"}
SAMPLE_DATA_PATH = "./data/sample_data.csv"


def _validate_csv_options(sep: str | None, encoding: str | None) -> tuple[str, str]:
    """Validate and normalize sep and encoding from request params.

    Returns (sep, encoding) tuple or raises ValueError with user-facing message.
    """
    # Encoding validation
    enc = (encoding or "utf-8").strip()
    if enc not in ALLOWED_ENCODINGS:
        raise ValueError(_("Invalid encoding. Use utf-8, latin-1, or cp1252."))

    # Sep validation
    s = sep if sep is not None else ","
    if s == "":
        raise ValueError(_("Separator cannot be empty."))
    # Convert literal \t to actual tab (store converted value in DB)
    if s == "\\t":
        s = "\t"
    if len(s) > 10:
        raise ValueError(_("Separator too long."))

    return s, enc


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
    if "." in file_name and file_name.rsplit(".", 1)[1].lower() not in ALLOWED_EXTENSIONS:
        return jsonify(error="Invalid file type"), 400

    if total_chunks * CHUNK_SIZE > MAX_FILE_SIZE:
        return jsonify(error="File too large"), 413

    chunk = request.files["file"].read()
    chunk_dir = UPLOAD_PATH / file_id
    ensure_dir(chunk_dir)
    chunk_path = chunk_dir / f"{chunk_number:04d}"
    with open(chunk_path, "wb") as f:
        f.write(chunk)

    return jsonify(success=True)


@app.route("/upload/finalize/<file_id>", methods=["GET"])
def finalize_upload(file_id) -> ...:
    filename = request.args.get("filename")
    total_chunks = request.args.get("total_chunks")

    if not filename or not total_chunks:
        return jsonify(error=_("filename and total_chunks are required")), 400

    final_path = UPLOAD_PATH / f"{file_id}_{filename}"

    try:
        sep, encoding = _validate_csv_options(
            request.args.get("sep", ","),
            request.args.get("encoding", "utf-8"),
        )
    except ValueError as e:
        return jsonify(error=str(e)), 400

    res = launch_task_with_tracking(
        finalize_chunks_upload,
        file_id=file_id,
        filename=str(final_path),
        total_chunks=int(total_chunks),  # type: ignore
        sep=sep,
        encoding=encoding,
        user_id=session["user_id"],
        track_progress=False,
    )

    try:
        result = res.get()
    except Exception as e:
        return jsonify(error=str(e)), 400

    if not result.get("success"):
        return jsonify(error=result["error"], can_retry=result.get("can_retry", False)), 400
    columns = result["columns"]

    return jsonify(
        success=True,
        path=str(final_path),
        columns=columns,
        sep=result.get("sep", ","),
        encoding=result.get("encoding", "utf-8"),
    )


@app.route("/upload-data", methods=["GET", "POST"])
@app.route("/upload-data/<int:project_id>", methods=["GET", "POST"])
def upload_data(project_id: int | None = None) -> ...:
    """
    Create a dataset from an uploaded file using Celery tasks

    Methods:
        GET: Redirect to the dataset creation page
        POST: Process form data and start upload task chain

    Returns:
        Redirect to the dataset list (or init-config during setup) with flash messages
    """
    # If not setup and GET we need to go back to init-config
    if request.method == "GET" and not check_is_setup():
        return redirect(url_for("init_config"))

    # Handle project_id parameter - check project and update session if provided
    if project_id is not None:
        res = update_session_project(project_id)
        if res is not None:
            return res

    # Dataset creation now lives in the dataset management area
    if request.method == "GET":
        return redirect(url_for("dataset_new"))

    if request.method == "POST":
        # Extract form data
        upload_type = request.form.get("upload_type")
        dataset_name = request.form.get("name")
        projects = request.form.getlist("projects")
        filename = request.form.get("filename")
        file_id = request.form.get("file_id")

        # Extract and validate CSV options
        try:
            sep, encoding = _validate_csv_options(
                request.form.get("sep", ","),
                request.form.get("encoding", "utf-8"),
            )
        except ValueError as e:
            flash(str(e), "error")
            return redirect(request.url)

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

        # Remember the CSV layout so later appends can be checked against it
        if upload_type == "sample_data":
            id_column, text_column = "text_id", "text"
            columns = read_csv_header(SAMPLE_DATA_PATH, ",", "utf-8")
        else:
            id_column = request.form.get("id_column") or None
            text_column = request.form.get("text_column") or None
            try:
                columns = json.loads(request.form.get("columns") or "null")
            except (ValueError, TypeError):
                columns = None
            if not isinstance(columns, list):
                columns = None

        # Display settings from the column configuration editor (flexible_text)
        column_config = None
        if upload_type == "flexible_text":
            fields = [column_field(c) for c in columns or [] if c not in (id_column, text_column)]
            try:
                raw_config = json.loads(request.form.get("column_config") or "{}")
                column_config = normalize_column_config(raw_config, fields)
            except json.JSONDecodeError:
                flash(_("Invalid column configuration."), "error")
                return redirect(request.url)
            except ValueError as e:
                flash(str(e), "error")
                return redirect(request.url)

        # Create new dataset
        try:
            dataset = new_dataset(
                dataset_name,
                session["user_id"],
                sep=sep,
                encoding=encoding,
                column_config=column_config,
                id_column=id_column,
                text_column=text_column,
                columns=columns,
            )

            # Link to selected projects
            for project_id_str in projects:
                project_id = int(project_id_str)
                link_dataset_to_project(dataset.id, project_id, session["user_id"])
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
            upload_type = "flexible_text"
            upload_params.update(
                {
                    "filename": SAMPLE_DATA_PATH,
                    "id_column": "text_id",
                    "text_column": "text",
                }
            )
        else:
            # Validate file upload for non-sample data
            if not filename or not file_id:
                flash(_("File upload incomplete"), "error")
                return redirect(request.url)

            # Construct actual file path
            upload_params["filename"] = str(UPLOAD_PATH / f"{file_id}_{filename}")

            # Validate required columns
            if upload_type in ("single_text", "flexible_text"):
                if not upload_params["id_column"] or not upload_params["text_column"]:
                    flash(_("ID and Text columns are required"), "error")
                    return redirect(request.url)

        # Start upload task chain
        try:
            filename = "_".join(upload_params.get("filename", "").split("/")[-1].split("_")[1:])  # type: ignore
            launch_task_with_tracking(
                upload_dataset,
                description=_("Uploading and processing file {filename}").format(filename=filename),
                upload_type=upload_type,
                upload_params=upload_params,
                dataset_id=dataset.id,
                user_id=session["user_id"],
                track_progress=True,
            )

            flash(_("Document processing started successfully"), "success")
            if not check_is_setup():
                return redirect(url_for("init_config"))
            return redirect(url_for("datasets"))

        except Exception as e:
            flash(_("Error starting upload: {error}").format(error=str(e)), "error")
            return redirect(request.url)

    return redirect(url_for("dataset_new"))


def read_csv_header(filename: str, sep: str, encoding: str) -> list[str] | None:
    """Return the column names of a CSV file, or None if it can't be read."""
    try:
        read_kwargs: dict = {"nrows": 0, "sep": sep, "encoding": encoding}
        if len(sep) > 1:
            read_kwargs["engine"] = "python"
        return [str(c) for c in pd.read_csv(filename, **read_kwargs).columns]
    except Exception:
        return None
