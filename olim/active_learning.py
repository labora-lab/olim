from . import app
from .database import get_labels, get_label, new_label
from .functions import get_highlights, render_entry, add_entry_label
from flask import render_template, redirect, request, session, flash
from flask_babel import _
import requests
from . import settings


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
    label = request.form.get("label")
    data = dict(
        app_key=settings.BACKEND_KEY,
        user_id=session["user_id"],
        label=label,
        values=[l for l, *_ in settings.LABELS]
    )
    res = requests.post(f"{settings.BACKEND_URL}/al/new-label", data).json()
    print(res)
    label = new_label(label, session["user_id"], al_id=res["label_id"])
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
        data_req = dict(
            app_key=settings.BACKEND_KEY,
            user_id=session["user_id"],
            label_id=label.al_key,
            text_id=request.form["text_id"],
            value=request.form["value"],
        )
        value_str = settings.LABELS[-1 - int(request.form["value"])][0]
        res = requests.post(f"{settings.BACKEND_URL}/al/add-value", data_req).json()
        add_entry_label(
            label_id, request.form["text_id"], session["user_id"], value_str
        )
        try:
            if res["text_id"] == data_req["text_id"]:
                flash(
                    _(
                        f"Added value \"{value_str}\" for entry {request.form['text_id']}."
                    ).format(label_name=label.name),
                    category="success",
                )
            else:
                flash(
                    _(
                        f"Error adding value \"{value_str}\" for entry {request.form['text_id']}."
                    ).format(label_name=label.name),
                    category="error",
                )
        except KeyError:
            flash(
                _(
                    f"Error adding value \"{value_str}\" for entry {request.form['text_id']}."
                ).format(label_name=label.name),
                category="error",
            )
    data_req = dict(
        app_key=settings.BACKEND_KEY,
        user_id=session["user_id"],
        label_id=label.al_key,
    )
    res = requests.post(f"{settings.BACKEND_URL}/al/req-entry", data_req).json()
    data = {
        "label": label,
        "highlight": get_highlights(),
        "valid_entry": True,
    }
    data = render_entry(res["text_id"], data)
    return render_template("al-entry.html", **data)
