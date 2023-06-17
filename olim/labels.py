from . import app
from .functions import store_queue
from .database import get_labels, new_label, del_label, get_label, add_entry_label
from flask import render_template, redirect, request, session, flash
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


# @app.route("/labels/", defaults={"path": ""})
# @app.route("/labels/<path:path>")
# def catch_all(path):
#     if path.lower().endswith(".csv"):
#         label = path[:-4].lower()
#         return Response(extract_label(label), mimetype="text/csv")


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
def label_upload():
    # Create a df from csv passed by POST
    df = pd.read_csv(request.files["file"])

    # Create empty label_created column if it doenst exists
    if "label_created" not in df:
        df["label_created"] = None

    # Group by the columns we are interested
    group = (
        df.groupby(["entry_id", "label", "label_value", "label_created"]).any().index
    )

    # Get a list of existing labels
    labels = [label.name for label in get_labels()]

    # Store labels
    for entry_id, label, value, created in group:
        label = label.replace(" ", "_")
        # If the label dont exist create it
        if label not in labels:
            new_label(label, session["user_id"])
            labels.append(label)
        # And label the patient
        add_entry_label(
            label, entry_id, session["user_id"], value
        )  # , date_created=created)

    # Wait 2 seconds for write operations to finish and redirect back to labels page
    time.sleep(2)
    return redirect(f"../labels")
