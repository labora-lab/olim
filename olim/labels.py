import json
import time

import pandas as pd
from flask import Response, flash, redirect, render_template, request, session, url_for
from flask_babel import _

from . import app, db, entry_types
from .celery_app import launch_task_with_tracking
from .database import (
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
    datasets = get_datasets(project_id, non_empty=True)
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
        project_id = project_id,
        label_id = label.id,
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
        flash(_("Label id: {label_id} not found!").format(label_id=label_id), category="warning")
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
        flash(_("Label id: {label_id} not found!").format(label_id=label_id), category="warning")
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
        flash(_("Label id: {label_id} not found!").format(label_id=label_id), category="warning")
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
        flash(_("Label id: {label_id} not found!").format(label_id=label_id), category="warning")
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
        flash(_("Label id: {label_id} not found!").format(label_id=label_id), category="warning")
        return redirect("/")
    project_id = label.project_id

    # Check project_id
    res = update_session_project(project_id)
    if res is not None:
        return res
    if label is None:
        flash(_("Label not found"), category="error")
        return redirect(url_for("labels", project_id=project_id))
    return render_template("label-settings.html", label=label)


@app.route("/<int:project_id>/label-upload", methods=["POST"])
def label_up(project_id: int) -> ...:
    # Check project_id
    res = update_session_project(project_id)
    if res is not None:
        return res

    # Get selected dataset from form
    dataset_id = request.form.get("dataset_id")
    if not dataset_id:
        flash(_("Dataset selection required"), category="warning")
        return redirect(url_for("labels", project_id=project_id))

    # Verify dataset exists
    dataset = get_dataset(dataset_id)
    if not dataset:
        flash(_("Invalid dataset selection"), category="warning")
        return redirect(url_for("labels", project_id=project_id))

    # Create a df from csv passed by POST
    df = pd.read_csv(request.files["file"].stream)

    label_upload(df, session["user_id"], project_id, dataset.id)

    # Wait 1 seconds for write operations to finish and redirect back to labels page
    time.sleep(1)
    return redirect(url_for("labels", project_id=project_id))
