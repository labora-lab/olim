import json
from time import sleep

import requests
from flask import flash, redirect, render_template, request, session, url_for
from flask_babel import _
from requests.models import Response as HTTPResponse

from . import app, db, settings
from .database import Label, add_entry_label, get_entry, get_label
from .functions import get_highlights, render_entry


def new_al(label: Label) -> None:
    return None


def sync_al(label: Label) -> HTTPResponse:
    if not label.al_key:
        new_al(label)
        sleep(4.0)
    data = {
        "app_key": label.project.datasets[0].learner_key,
        "user_id": session["user_id"],
        "values": [label_value for label_value, *_ in settings.LABELS],
        "label": {
            "label_name": label.name,
            "label_id": label.al_key,
            "entries": {entry.entry.entry_id: entry.value for entry in label.entries},
        },
    }

    res = requests.put(f"{settings.LEARNER_URL}/al/sync-label", json=json.dumps(data))
    if res.status_code == 200:
        al_key = res.json()["al_key"]
        label.al_key = al_key
        db.session.commit()

    return res


@app.route("/al/<int:label_id>", methods=["GET", "POST"])
def catch_al(label_id: int) -> ...:
    label = get_label(label_id)
    if not label:
        flash(_("Label not found."), category="error")
        return redirect("/al")

    try:
        # Only try to sync when entrering AL
        if request.method == "GET":
            res = sync_al(label)
            if res.status_code != 200:
                if "message" in res.json():
                    message = res.json()["message"]
                else:
                    message = ""
                flash(
                    _(
                        "WARNING: Error syncing labels, models might not been trained on"
                        " complete dataset: {message}"
                    ).format(message=message),
                    category="warning",
                )

        # Assign label value if given
        if request.method == "POST":
            value_str = settings.LABELS[-1 - int(request.form["value"])][0]
            entry = get_entry(request.form["entry_id"], by="id")
            data_req = {
                "app_key": label.project.datasets[0].learner_key,
                "user_id": session["user_id"],
                "label_id": label.al_key,
                "entry_id": entry.entry_id,  # type: ignore
                "value": value_str,
            }
            res = requests.put(f"{settings.LEARNER_URL}/al/add-value", data_req)
            if res.status_code != 200:
                if "message" in res.json():
                    message = res.json()["message"]
                else:
                    message = ""
                flash(
                    _("Error setting value {entry_value} to entry {entry_id}: {message}").format(
                        entry_value=value_str, entry_id=request.form["entry_id"], message=message
                    ),
                    category="error",
                )
            else:
                res = res.json()

            add_entry_label(label_id, request.form["entry_id"], session["user_id"], value_str)
            flash(
                _(f'Added value "{value_str}" for entry {request.form["entry_id"]}.').format(
                    label_name=label.name
                ),
                category="success",
            )
        data_req = {
            "app_key": label.project.datasets[0].learner_key,
            "user_id": session["user_id"],
            "label_id": label.al_key,
        }
        res = requests.put(f"{settings.LEARNER_URL}/al/req-entry", data_req)
        if res.status_code != 200:
            if "message" in res.json():
                message = res.json()["message"]
            else:
                message = ""
            flash(
                _("Error getting next entry for label {label_name}}: {message}").format(
                    label_name=label.name, message=message
                ),
                category="error",
            )
            return redirect(url_for("labels"))
        else:
            res = res.json()

        data = {
            "label": label,
            "highlight": get_highlights(),
            "valid_entry": True,
        }
        if "messages" in res:
            data["messages"] = res["messages"]
        else:
            data["messages"] = ""
        data = render_entry(res["entry_id"], label.project.datasets[0].id, data)
        return render_template("al-entry.html", **data)
    except requests.exceptions.ConnectionError:
        flash(
            _(
                "Failed to enter active learner for label {label_name}, please check learner"
                " connection."
            ).format(label_name=label.name),
            category="error",
        )
        return redirect(url_for("labels"))


@app.route("/al/<int:label_id>/export", methods=["GET", "POST"])
def export_label(label_id: int) -> ...:
    return redirect("/")
    # label = get_label(label_id)

    # if label is None:
    #     # TODO: Add error message as below
    #     # flash(_("Label not found."), category="error")
    #     return redirect("/labels")

    # try:
    #     data_req = {
    #         "app_key": label.project.datasets[0].learner_key,
    #         "user_id": session["user_id"],
    #         "label_id": label.al_key,
    #     }

    #     if request.method == "POST":
    #         # get alpha from request and add to data_req
    #         alpha = request.form["alpha"]
    #     else:
    #         alpha = 0.95

    #     data_req["alpha"] = alpha

    #     ic(data_req)

    #     res = requests.put(
    #         f"{settings.LEARNER_URL}/al/export-predictions",
    #         json=json.dumps(data_req),
    #     ).json()

    #     if res["status"] == "success":
    #         preds = res["predictions"]
    #         preds_values = [pred[0] if len(pred) == 1 else np.nan for pred in preds.values()]
    #         preds_ids = list(preds.keys())
    #         pred_df = pd.DataFrame({"entry_id": preds_ids, "value": preds_values})

    #         ic(pred_df)

    #         # download json res["predictions"] as csv
    #         return Response(
    #             pred_df.to_csv(index=False),
    #             mimetype="text/csv",
    #             headers={
    #                 "Content-disposition": "attachment; "
    #                 f"filename={label.name}-{alpha}-predictions.csv"
    #             },
    #         )
    #     else:
    #         flash(
    #             _("Error exporting predictions: {error}").format(error=res["error"]),
    #             category="error",
    #         )
    #         return redirect("/labels")
    # except requests.exceptions.ConnectionError:
    #     flash(
    #         _(
    #             "Failed to export predictions for label {label_name}, "
    #             "please check learner connection."
    #         ).format(label_name=label.name),
    #         category="error",
    #     )
    #     return redirect(f"/labels/{label_id}/settings")
