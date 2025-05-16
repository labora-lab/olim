from celery.result import AsyncResult
from flask import flash, jsonify, redirect, render_template, request, session
from flask_babel import _

from . import app
from .database import link_dataset_to_project, new_dataset
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


@app.route("/upload-data", methods=["GET", "POST"])
def upload_data() -> ...:
    """Handle file uploads using celery tasks"""
    if request.method == "POST":
        upload_type = request.form.get("upload_type")
        if upload_type is None:
            raise NotImplementedError
        datafile = request.files.get("file")
        text_id = request.form.get("text_id")
        text = request.form.get("text")
        dataset_name = request.form.get("name")
        projects = [int(p) for p in request.form.getlist("projects")]

        dataset = new_dataset(dataset_name, session["user_id"])

        for project_id in projects:
            link_dataset_to_project(dataset.id, project_id, session["user_id"])

        # try:
        # Handle sample data upload
        if upload_type == "sample_data":
            task_params = {
                "upload_type": upload_type,
                "file_data": "./data/sample_data.csv",
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
            if not datafile:
                flash(_("No file selected"), category="error")
                return redirect(request.url)

            task_params = {
                "upload_type": upload_type,
                "file_data": datafile,
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
    )
