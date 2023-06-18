from . import app, db, entry_types
from .functions import store_queue, label_upload
from .database import (
    get_labels,
    get_user,
    new_label,
    del_label,
    get_label,
    add_entry_label,
    get_labeled,
)
from flask import render_template, redirect, request, session, flash, Response
import pandas as pd
import numpy as np
import time


@app.route("/labels", methods=["GET"])
def labels():
    labels_values = {label.id: {} for label in get_labels()}
    possible_values = []
    for label in get_labels():
        for l in label.entries:
            if not l.is_deleted:
                if l.value in labels_values[l.label_id]:
                    labels_values[l.label_id][l.value] += 1
                else:
                    labels_values[l.label_id][l.value] = 1
            if l.value not in possible_values:
                possible_values.append(l.value)
    possible_values.append("Total")
    for label_id in labels_values:
        labels_values[label_id]["Total"] = sum(
            [v for v in labels_values[label_id].values()]
        )
    labels = get_labels()
    return render_template(
        "labels.html",
        labels=labels,
        values=labels_values,
        possible_values=possible_values,
    )


@app.route("/labels/new", methods=["POST"])
def create_label():
    label = request.form.get("label")
    label = new_label(label, session["user_id"])
    flash(f"Criado rótulo {label.name}", category="success")
    return redirect("/labels")


@app.route("/labels/<int:label_id>/delete", methods=["GET"])
def delete_label(label_id):
    label = del_label(label_id, session["user_id"])
    flash(f"Deletado rótulo {label.name}", category="success")
    return redirect("/labels")


@app.route("/labels/<label_id>/csv")
def extract_labels(label_id):
    label = get_label(label_id)
    label_str = label.name
    df = pd.read_sql(get_labeled(label_id), db.engine)
    dfs_entries = []
    for le in label.entries:
        if not le.is_deleted:
            module = getattr(entry_types, le.entry.type)
            dfs_entries.append(module.extract_texts(le.entry.entry_id))
    df = df.merge(pd.concat(dfs_entries, ignore_index=True), how="left", on="entry_id")
    return Response(
        df.to_csv(index=False),
        mimetype="text/csv",
        headers={"Content-disposition": f"attachment; filename={label_str}.csv"},
    )


@app.route("/labels/<int:label_id>/queue", methods=["GET"])
def catch_queue(label_id):
    # Create a queue from label
    queue = [
        l.entry.entry_id
        for l in get_label(label_id).entries
        if not l.is_deleted and l.value != ""
    ]
    queue_hash = store_queue(queue)
    # Redirect to queue
    return redirect(f"/queue/{queue_hash}")


@app.route("/label-upload", methods=["POST"])
def label_up():
    # Create a df from csv passed by POST
    df = pd.read_csv(request.files["file"])

    label_upload(df)

    # Wait 2 seconds for write operations to finish and redirect back to labels page
    time.sleep(2)
    return redirect(f"../labels")
