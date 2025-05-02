from celery.result import AsyncResult
from flask import flash, jsonify, redirect, render_template, request
from flask_babel import _

from . import app
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

        try:
            # Handle sample data upload
            if upload_type == "sample_data":
                result = start_upload_chain(
                    upload_type=upload_type,
                    file_data="./data/sample_data.csv",
                )
                if result:
                    ACTIVE_TASKS.add(result)
                    return render_template(
                        "upload-data.html",
                        up_task=result,
                        active_tasks=list(ACTIVE_TASKS),
                        completed_tasks=COMPLETED_TASKS,
                    )

            # Validate file upload
            if not datafile:
                flash(_("No file selected"), category="error")
                return render_template("upload-data.html")

            # Handle text format upload
            if upload_type == "simple_text":
                if not text_id or not text:
                    flash(_("Missing text_id or text for text format upload"), category="error")
                    return redirect(request.url)

            # Start celery task chain
            task_id = start_upload_chain(
                upload_type=upload_type,
                file_data=datafile,
                text_id=text_id,
                text=text,
            )

            # Track new task
            ACTIVE_TASKS.add(task_id)
            return render_template(
                "upload-data.html",
                up_task=task_id,
                active_tasks=list(ACTIVE_TASKS),
                completed_tasks=COMPLETED_TASKS,
            )

        except Exception as e:
            flash(_("Error starting upload task: {error}").format(error=str(e)), category="error")
            return redirect(request.url)

    return render_template(
        "upload-data.html", active_tasks=list(ACTIVE_TASKS), completed_tasks=COMPLETED_TASKS
    )
