import os
import tempfile
import threading
from collections.abc import Callable

import click
from flask import flash, redirect, render_template, request
from flask_babel import _
from werkzeug.datastructures import FileStorage

from . import app
from .entry_types.patient import up_patients
from .entry_types.single_text import up_single_text


# Singleton to manage upload tasks
class UploadManager:
    _instance = None
    _lock = threading.Lock()
    _task_id = None
    _is_uploading = False
    _last_error = None
    _tmp_dir = None

    def __new__(cls) -> "UploadManager":
        if cls._instance is None:
            with cls._lock:
                if not cls._instance:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def get_task(self) -> bool | str | None:
        with self._lock:
            if self._is_uploading:
                return self._task_id
        return False

    def get_error(self) -> str | None:
        with self._lock:
            return self._last_error

    def upload_data(
        self,
        up_function: Callable,
        task_id: str,
        csv_file: str | FileStorage | None = None,
        **parameters,
    ) -> bool:
        if self._is_uploading:
            print("Another upload is already in progress. Upload request ignored.")
            return False
        # lock uploads
        with self._lock:
            self._is_uploading = True
        self._task_id = task_id
        self._last_error = None

        # If we have it save csv file in a temporary folder
        if csv_file:
            if type(csv_file) is str:
                parameters["csv_file"] = csv_file
            else:
                self._tmp_dir = tempfile.TemporaryDirectory()
                # FIXME: task_id is not unique, its being used as `filename`
                temp_path = os.path.join(self._tmp_dir.name, task_id)
                csv_file.save(temp_path)
                parameters["csv_file"] = temp_path

        # Start a new thread to handle the upload function invocation
        thread = threading.Thread(
            target=self._run_function_with_context,
            args=(up_function, parameters),
            daemon=True,
        )
        thread.start()
        return True

    def _run_function_with_context(self, up_function: click.Command, parameters: ...) -> None:
        try:
            with app.app_context():
                with click.Context(up_function) as ctx:
                    ctx.invoke(up_function, **parameters)
        except Exception as e:
            with self._lock:
                self._last_error = _("Error processing {task_id}: {error}").format(
                    task_id=self._task_id, error=e
                )
        else:
            self._last_error = None
        finally:
            # Release lock at the end
            with self._lock:
                self._is_uploading = False
            self._task_id = None
            if self._tmp_dir is not None:
                self._tmp_dir.cleanup()
                self._tmp_dir = None


@app.route("/upload-data", methods=["GET", "POST"])
def upload_data() -> ...:
    if request.method == "POST":
        upload_type = request.form.get("upload_type")
        datafile = request.files.get("file")
        text_id = request.form.get("text_id")
        text = request.form.get("text")

        if upload_type == "sample_data":
            if not UploadManager().upload_data(
                up_single_text,
                task_id="sample data",
                csv_file="./data/sample_data.csv",
                id_column="text_id",
                text_column="text",
            ):
                flash(
                    _("Can only process one data upload task at a time, try later"),
                    category="warning",
                )
        else:
            if not datafile:
                flash(_("No file selected"), category="error")
                return render_template("upload-data.html")

            filename = datafile.filename or "upload_data"
            try:
                if upload_type == "patient_sheet":
                    if not UploadManager().upload_data(
                        up_patients, task_id=filename, csv_file=datafile
                    ):
                        flash(
                            _("Can only process one data upload task at a time, try later"),
                            category="warning",
                        )

                elif upload_type == "simple_text":
                    if not text_id or not text:
                        flash(
                            _("Missing text_id or text for text format upload"),
                            category="error",
                        )
                        return redirect(request.url)

                    if not UploadManager().upload_data(
                        up_single_text,
                        task_id=filename,
                        csv_file=datafile,
                        id_column=text_id,
                        text_column=text,
                    ):
                        flash(
                            _("Can only process one data upload task at a time, try later"),
                            category="warning",
                        )
            except Exception as e:
                flash(
                    _("Error executing upload command: {error}").format(error=str(e)),
                    category="error",
                )
                return redirect(request.url)

    um = UploadManager()
    if um.get_error():
        # TODO: translate error message or type the get_error correctly.
        flash(um.get_error() or "An error occurred", category="error")
    return render_template("upload-data.html", up_task=um.get_task())
