import os
import tempfile

import click
from flask import flash, redirect, render_template, request
from flask_babel import _

from . import app
from .entry_types.patient import up_patients
from .entry_types.single_text import up_single_text


@app.route("/upload-data", methods=["GET", "POST"])
def upload_data() -> ...:
    if request.method == "POST":
        upload_type = request.form.get("upload_type")
        file = request.files.get("file")
        text_id = request.form.get("text_id")
        text = request.form.get("text")

        if not file or not file.filename:
            flash(_("No file selected", category="error"))
            return redirect(request.url)

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = os.path.join(temp_dir, file.filename)
            file.save(temp_path)

            try:
                if upload_type == "patient_sheet":
                    with app.app_context():
                        with click.Context(up_patients) as ctx:
                            ctx.invoke(up_patients, csv_file=temp_path)
                    flash(
                        _(
                            f"Uploaded patient_sheetdata with file {file.filename}",
                            category="success",
                        )
                    )

                elif upload_type == "simple_text":
                    if not text_id or not text:
                        flash(
                            _(
                                "Missing text_id or text for simple_text upload",
                                "error",
                            )
                        )
                        return redirect(request.url)

                    with app.app_context():
                        with click.Context(up_single_text) as ctx:
                            ctx.invoke(
                                up_single_text,
                                csv_file=temp_path,
                                id_column=text_id,
                                text_column=text,
                            )
                    flash(
                        _(
                            f"Uploaded simple_text data with file {file.filename} and columns "
                            f"{text_id=}, {text=}",
                            category="success",
                        )
                    )
            except Exception:
                # flash(_(f"Error executing upload command: {e}"), category="error")
                return redirect(request.url)

    return render_template("upload-data.html")
