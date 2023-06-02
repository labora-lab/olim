from . import app
from .functions import (
    get_labels,
    extract_label,
    store_queue,
    get_labels,
    create_new_label,
    add_patient_label,
)
from flask import render_template, Response, redirect, request
import pandas as pd
import numpy as np
import time


@app.route("/labels", methods=["GET"])
def labels():
    result = get_labels()["hits"]["hits"]
    res = []
    for r in result:
        values = np.array(extract_label(r["_source"]["label"].lower(), only_values=True))
        res.append(
            dict(
                r["_source"],
                _id=r["_id"],
                n_labeled=len(values),
                n_yes=np.sum(values == "sim"),
                n_no=np.sum(values == "nao"),
                n_dontknow=np.sum(values == "nao_sei"),
            )
        )
    return render_template("labels.html", res=res)


@app.route("/labels/", defaults={"path": ""})
@app.route("/labels/<path:path>")
def catch_all(path):
    if path.lower().endswith(".csv"):
        label = path[:-4].lower()
        return Response(extract_label(label), mimetype="text/csv")


@app.route("/label-queue/", methods=["GET"])
def catch_queue():
    label = request.args.get("label").lower()
    # Create a queue from label
    queue = extract_label(label, only_ids=True)
    queue_hash = store_queue(queue)
    # Redirect to queue
    return redirect(f"../patient?queue={queue_hash}")


@app.route("/label-upload", methods=["POST"])
def label_upload():
    # Create a df from csv passed by POST
    df = pd.read_csv(request.files["file"])

    # Create empty label_created column if it doenst exists
    if "label_created" not in df:
        df["label_created"] = None

    # Group by the columns we are interested
    group = (
        df.groupby(["patient_id", "label", "label_value", "label_created"]).any().index
    )

    # Get a list of existing labels
    labels = [label["_source"]["label"] for label in get_labels()["hits"]["hits"]]

    # Store labels
    for pid, label, value, created in group:
        label = label.replace(" ", "_")
        # If the label dont exist create it
        if label not in labels:
            create_new_label(label)
            labels.append(label)
        # And label the patient
        add_patient_label(label, pid, value, date_created=created)

    # Wait 2 seconds for write operations to finish and redirect back to labels page
    time.sleep(2)
    return redirect(f"../labels")
