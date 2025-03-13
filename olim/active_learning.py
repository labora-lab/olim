from . import app
from .database import get_labels, get_label, new_label
from .functions import get_highlights, render_entry, add_entry_label
from flask import render_template, redirect, request, session, flash, Response
from flask_babel import _
import requests
from . import settings
from . import db
import json
from icecream import ic
from time import sleep
import pandas as pd
import numpy as np


def new_al(label):
    data = dict(
        app_key=settings.LEARNER_KEY,
        user_id=session["user_id"],
        label=label.name,
        values=[l for l, *_ in settings.LABELS],
    )
    res = requests.put(
        f"{settings.LEARNER_URL}/al/new-label", json=json.dumps(data)
    ).json()

    print(res["label_id"])
    label.al_key = res["label_id"]
    db.session.commit()


@app.route("/al", methods=["GET"])
def active_learning():
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
        "al-list.html",
        labels=labels,
        values=labels_values,
        possible_values=possible_values,
    )


@app.route("/al/new", methods=["POST"])
def create_al():
    label = new_label(request.form.get("label"), session["user_id"])
    new_al(label)

    flash(
        _("Active learning for  {label_name} sucessfully created").format(
            label_name=label.name
        ),
        category="success",
    )
    return redirect("/al")


@app.route("/al/<int:label_id>", methods=["GET", "POST"])
def catch_al(label_id):
    label = get_label(label_id)

    # Assign label value if given
    if request.method == "POST":
        value_str = settings.LABELS[-1 - int(request.form["value"])][0]
        data_req = dict(
            app_key=settings.LEARNER_KEY,
            user_id=session["user_id"],
            label_id=label.al_key,
            entry_id=request.form["entry_id"],
            value=value_str,
        )
        ic(data_req)
        res = requests.put(f"{settings.LEARNER_URL}/al/add-value", data_req).json()
        ic(res)
        try:
            if res["entry_id"] == data_req["entry_id"]:
                add_entry_label(
                    label_id, request.form["entry_id"], session["user_id"], value_str
                )
                flash(
                    _(
                        f"Added value \"{value_str}\" for entry {request.form['entry_id']}."
                    ).format(label_name=label.name),
                    category="success",
                )
            else:
                flash(
                    _(
                        f"Error adding value \"{value_str}\" for entry {request.form['entry_id']}."
                    ).format(label_name=label.name),
                    category="error",
                )
        except KeyError:
            flash(
                _(
                    f"Error adding value \"{value_str}\" for entry {request.form['entry_id']}. Got key error."
                ).format(label_name=label.name),
                category="error",
            )
    data_req = dict(
        app_key=settings.LEARNER_KEY,
        user_id=session["user_id"],
        label_id=label.al_key,
    )
    res = requests.put(f"{settings.LEARNER_URL}/al/req-entry", data_req).json()
    data = {
        "label": label,
        "highlight": get_highlights(),
        "valid_entry": True,
        "messages": res["messages"],
    }
    data = render_entry(res["entry_id"], data)
    return render_template("al-entry.html", **data)


@app.route("/al/<int:label_id>/sync", methods=["GET", "POST"])
def sync_label(label_id):
    label = get_label(label_id)
    if not label.al_key:
        new_al(label)
        sleep(5.0)
    data = {
        "app_key": settings.LEARNER_KEY,
        "user_id": session["user_id"],
        "values": [l for l, *_ in settings.LABELS],
        "label": {
            "label_name": label.name,
            "label_id": label.al_key,
            "entries": {entry.entry_id: entry.value for entry in label.entries},
        },
    }

    res = requests.put(f"{settings.LEARNER_URL}/al/sync-label", json=json.dumps(data))
    ic(res.json())
    al_key = res.json()["al_key"]

    # TODO update label al_key
    print(al_key)
    label.al_key = al_key
    db.session.commit()

    if res.status_code == 200:
        flash(_("Labels successfully synced."), category="success")
    else:
        flash(_("Error syncing labels."), category="error")

    return redirect("/labels")


@app.route("/al/<int:label_id>/export", methods=["GET", "POST"])
def export_label(label_id):
    label = get_label(label_id)
    data_req = dict(
        app_key=settings.LEARNER_KEY,
        user_id=session["user_id"],
        label_id=label.al_key,
    )

    if request.method == "POST":
        # get alpha from request and add to data_req
        alpha = request.form["alpha"]
    else:
        alpha = 0.95

    data_req["alpha"] = alpha

    ic(data_req)

    res = requests.put(
        f"{settings.LEARNER_URL}/al/export-predictions",
        json=json.dumps(data_req),
    )

    preds = res.json()["predictions"]
    preds_values = [pred[0] if len(pred) == 1 else np.nan for pred in preds.values()]
    preds_ids = list(preds.keys())
    pred_df = pd.DataFrame({"entry_id": preds_ids, "value": preds_values})

    ic(pred_df)

    # download json res["predictions"] as csv
    return Response(
        pred_df.to_csv(index=False),
        mimetype="text/csv",
        headers={
            "Content-disposition": f"attachment; filename={label.name}-{alpha}-predictions.csv"
        },
    )
