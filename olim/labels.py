import json
import time

import pandas as pd
from flask import Response, flash, redirect, render_template, request, session, url_for
from flask_babel import _

from . import app, db, entry_types
from .celery_app import launch_task_with_tracking
from .database import (
    CeleryTask,
    del_label,
    get_dataset,
    get_datasets,
    get_label,
    get_labeled,
    get_labels,
    new_label,
)
from .project import update_session_project
from .tasks.active_learning import create_label_al
from .utils.label import label_upload
from .utils.queues import store_queue


@app.route("/<int:project_id>", methods=["GET"])
@app.route("/<int:project_id>/labels", methods=["GET"])
def labels(project_id: int) -> ...:
    # Check project_id
    res = update_session_project(project_id)
    if res is not None:
        return res

    labels_values = {label.id: {} for label in get_labels(project_id)}
    possible_values = []
    for label in get_labels(project_id):
        for entry in label.entries:
            if not entry.is_deleted:
                if entry.value in labels_values[label.id]:
                    labels_values[label.id][entry.value] += 1
                else:
                    labels_values[label.id][entry.value] = 1
            if entry.value not in possible_values:
                possible_values.append(entry.value)
    possible_values.append("Total")
    for label_id in labels_values:
        labels_values[label_id]["Total"] = sum(labels_values[label_id].values())
    labels = get_labels(project_id)
    datasets = list(get_datasets(project_id, non_empty=True))
    return render_template(
        "labels.html",
        labels=labels,
        values=labels_values,
        possible_values=possible_values,
        datasets=datasets,
    )


@app.route("/<int:project_id>/labels/new", methods=["POST"])
def create_label(project_id: int) -> ...:
    # Check project_id
    res = update_session_project(project_id)
    if res is not None:
        return res

    label_name = request.form.get("label")
    label = new_label(label_name, session["user_id"], project_id)
    launch_task_with_tracking(
        create_label_al,
        project_id=project_id,
        label_id=label.id,
        user_id=session["user_id"],
        track_progress=True,
    )
    flash(
        _("Label {label_name} successfully created").format(label_name=label.name),
        category="success",
    )

    return redirect(url_for("labels", project_id=project_id))


@app.route("/labels/<int:label_id>/delete", methods=["GET"])
def delete_label(label_id: int) -> ...:
    label = get_label(label_id)
    if label is None:
        flash(
            _("Label id: {label_id} not found!").format(label_id=label_id),
            category="warning",
        )
        return redirect("/")

    # Check project_id
    res = update_session_project(label.project_id)
    if res is not None:
        return res

    label = del_label(label_id, session["user_id"])
    flash(
        _("Label {label_name} sucessfully deleted").format(label_name=label.name),
        category="success",
    )
    return redirect(url_for("labels", project_id=label.project_id))


@app.route("/labels/<label_id>/csv")
def extract_labels(label_id: int) -> ...:
    label = get_label(label_id)
    if label is None:
        flash(
            _("Label id: {label_id} not found!").format(label_id=label_id),
            category="warning",
        )
        return redirect("/")
    project_id = label.project_id

    # Check project_id
    res = update_session_project(project_id)
    if res is not None:
        return res
    if label is None:
        flash(_("Label not found"), category="error")
        return redirect(url_for("labels", project_id=project_id))

    label_str = label.name
    df = pd.read_sql(get_labeled(label_id), db.engine)
    print(df.head())
    dfs_entries = []
    for le in label.entries:
        if not le.is_deleted:
            module = getattr(entry_types, le.entry.type)
            dfs_entries.append(module.extract_texts(le.entry.entry_id, le.entry.dataset.id))
    df = df.merge(pd.concat(dfs_entries, ignore_index=True), how="left", on="entry_id")
    return Response(
        df.to_csv(index=False),
        mimetype="text/csv",
        headers={"Content-disposition": f"attachment; filename={label_str}.csv"},
    )


@app.route("/labels/<label_id>/json")
def extract_labels_json(label_id: int) -> ...:
    label = get_label(label_id)
    if label is None:
        flash(
            _("Label id: {label_id} not found!").format(label_id=label_id),
            category="warning",
        )
        return redirect("/")
    project_id = label.project_id

    # Check project_id
    res = update_session_project(project_id)
    if res is not None:
        return res
    if label is None:
        flash(_("Label not found"), category="error")
        return redirect(url_for("labels", project_id=project_id))
    label_str = label.name
    entries_values = {}
    for le in label.entries:
        if not le.is_deleted:
            entries_values[(le.entry.dataset.name, le.entry.entry_id)] = le.value
    return Response(
        json.dumps(entries_values),
        mimetype="text/json",
        headers={"Content-disposition": f"attachment; filename={label_str}.json"},
    )


@app.route("/labels/<int:label_id>/queue", methods=["GET"])
def catch_queue(label_id: int) -> ...:
    label = get_label(label_id)
    if label is None:
        flash(
            _("Label id: {label_id} not found!").format(label_id=label_id),
            category="warning",
        )
        return redirect("/")
    project_id = label.project_id

    # Check project_id
    res = update_session_project(project_id)
    if res is not None:
        return res
    if label is None:
        flash(_("Label not found"), category="error")
        return redirect(url_for("labels", project_id=project_id))
    queue = [
        (label.entry.dataset_id, label.entry.entry_id)
        for label in label.entries
        if not label.is_deleted and label.value
    ]
    queue_id = store_queue(queue, project_id)
    # Redirect to queue
    return redirect(url_for("entry", project_id=project_id, queue_id=queue_id))


@app.route("/labels/<int:label_id>/settings", methods=["GET"])
def label_settings(label_id: int) -> ...:
    label = get_label(label_id)
    if label is None:
        flash(
            _("Label id: {label_id} not found!").format(label_id=label_id),
            category="warning",
        )
        return redirect("/")
    project_id = label.project_id

    export_tasks = CeleryTask.query.filter_by(task_name="learner.export_predictions").all()[::-1]

    # Check project_id
    res = update_session_project(project_id)
    if res is not None:
        return res
    if label is None:
        flash(_("Label not found"), category="error")
        return redirect(url_for("labels", project_id=project_id))
    return render_template("label-settings.html", label=label, export_tasks=export_tasks)


@app.route("/label/<int:label_id>/update-learner-parameters", methods=["POST"])
def update_learner_parameters(label_id: int) -> ...:
    """Update learner parameters for a label"""
    # Check admin role
    if session.get("role") != "admin":
        flash(_("Admin access required"), category="error")
        return redirect(url_for("label_settings", label_id=label_id))

    label = get_label(label_id)
    if label is None:
        flash(_("Label not found"), category="error")
        return redirect("/")

    try:
        # Get form data
        param_names = request.form.getlist("param_names[]")
        param_types = request.form.getlist("param_types[]")
        param_values = request.form.getlist("param_values[]")
        param_is_list = request.form.getlist("param_is_list[]")

        # Convert form data to parameters dictionary
        parameters = {}

        for i, name in enumerate(param_names):
            if not name.strip():  # Skip empty names
                continue

            if i >= len(param_types) or i >= len(param_values):
                continue

            base_type = param_types[i]
            value_str = param_values[i]
            is_list = str(i + 1) in param_is_list  # Check if checkbox was checked

            # Type conversion function
            def convert_value(val_str: str, val_type: str) -> ...:
                val_str = val_str.strip()
                if val_type == "int":
                    return int(val_str)
                elif val_type == "float":
                    return float(val_str)
                elif val_type == "bool":
                    return val_str.lower() in ("true", "1", "yes", "on")
                else:  # str
                    return val_str

            # Process value based on whether it's a list or single value
            if is_list:
                # Split by comma and convert each value
                if value_str.strip():
                    list_values = [v.strip() for v in value_str.split(",") if v.strip()]
                    parameters[name] = [convert_value(v, base_type) for v in list_values]
                else:
                    parameters[name] = []
            else:
                # Single value - always store the parameter, even if empty
                parameters[name] = convert_value(value_str, base_type) if value_str.strip() else ""

        # Update label with new parameters
        label.learner_parameters = parameters if parameters else None
        db.session.commit()

        flash(_("Learner parameters updated successfully"), category="success")

    except ValueError as e:
        flash(
            _("Error converting parameter values: {error}").format(error=str(e)),
            category="error",
        )
    except Exception as e:
        flash(
            _("Error updating parameters: {error}").format(error=str(e)),
            category="error",
        )

    return redirect(url_for("label_settings", label_id=label_id))


@app.route("/label/<int:label_id>/upload-auto-labels", methods=["POST"])
def upload_auto_labels(label_id: int) -> ...:
    """Upload and process auto-labels CSV file"""
    # Check admin role
    if session.get("role") != "admin":
        flash(_("Admin access required"), category="error")
        return redirect(url_for("label_settings", label_id=label_id))

    label = get_label(label_id)
    if label is None:
        flash(_("Label not found"), category="error")
        return redirect("/")

    if "auto_label_file" not in request.files:
        flash(_("No file selected"), category="error")
        return redirect(url_for("label_settings", label_id=label_id))

    file = request.files["auto_label_file"]
    if file.filename == "":
        flash(_("No file selected"), category="error")
        return redirect(url_for("label_settings", label_id=label_id))

    try:
        # Read CSV file
        df = pd.read_csv(file.stream)

        # Validate required columns
        required_columns = {"dataset_id", "entry_id", "value"}
        if not required_columns.issubset(df.columns):
            missing = required_columns - set(df.columns)
            flash(
                _("Missing required columns: {columns}").format(columns=", ".join(missing)),
                category="error",
            )
            return redirect(url_for("label_settings", label_id=label_id))

        # Convert to {COMPOSITE_ID: value} format
        new_auto_labels = {}
        from .tasks.active_learning import COMPOSITE_ID

        for __, row in df.iterrows():
            composite_id = COMPOSITE_ID.format(
                dataset_id=int(row["dataset_id"]), entry_id=row["entry_id"]
            )
            new_auto_labels[composite_id] = str(row["value"])

        # Merge with existing auto-labels if they exist
        existing_auto_labels = label.auto_labels if label.auto_labels else {}
        merged_auto_labels = {**existing_auto_labels, **new_auto_labels}

        # Update label with merged auto-labels
        label.auto_labels = merged_auto_labels
        db.session.commit()

        flash(
            _("Successfully uploaded {count} auto-labels").format(count=len(new_auto_labels)),
            category="success",
        )

    except Exception as e:
        flash(_("Error processing file: {error}").format(error=str(e)), category="error")

    return redirect(url_for("label_settings", label_id=label_id))


@app.route("/<int:project_id>/label-upload", methods=["POST"])
def label_up(project_id: int) -> ...:
    # Check project_id
    res = update_session_project(project_id)
    if res is not None:
        return res

    # Get datasets for this project
    datasets = list(get_datasets(project_id))
    if not datasets:
        flash(_("No datasets available for this project"), category="warning")
        return redirect(url_for("labels", project_id=project_id))

    # Handle dataset selection
    if len(datasets) == 1:
        # Auto-select if only one dataset
        dataset_id = datasets[0].id
    else:
        # Multiple datasets - require selection
        dataset_id = request.form.get("dataset_id")
        if not dataset_id:
            flash(_("Dataset selection required"), category="warning")
            return redirect(url_for("labels", project_id=project_id))

    # Verify dataset exists and is valid
    try:
        dataset_id = int(dataset_id)
        dataset = get_dataset(dataset_id)
        if not dataset or dataset not in datasets:
            flash(_("Invalid dataset selection"), category="warning")
            return redirect(url_for("labels", project_id=project_id))
    except (ValueError, TypeError):
        flash(_("Invalid dataset selection"), category="warning")
        return redirect(url_for("labels", project_id=project_id))

    # Check if user wants to use validation (active learning pipeline)
    use_for_validation = request.form.get("use_for_validation") == "on"

    # Create a df from csv passed by POST
    df = pd.read_csv(request.files["file"].stream)

    # Use the label_upload function with the use_active_learning parameter
    label_upload(
        df, session["user_id"], project_id, dataset.id, use_active_learning=use_for_validation
    )

    # Wait 1 seconds for write operations to finish and redirect back to labels page
    time.sleep(1)
    return redirect(url_for("labels", project_id=project_id))
