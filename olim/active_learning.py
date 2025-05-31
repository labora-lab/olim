import json

from flask import flash, redirect, render_template, request, session, url_for
from flask_babel import _

from . import app, db, settings
from .celery_app import launch_task_with_tracking
from .database import Label, add_entry_label, get_entry, get_label
from .functions import get_highlights, render_entry
from .tasks.active_learning import COMPOSITE_ID, add_label_value, create_label_al, train_model


def new_al(label: Label) -> None:
    return None


@app.route("/al/<int:label_id>", methods=["GET", "POST"])
def catch_al(label_id: int) -> ...:
    label = get_label(label_id)
    if not label:
        flash(_("Label not found."), category="error")
        return redirect("/al")

    # Create learner if it doen't exists
    if label.al_key is None:
            launch_task_with_tracking(
                create_label_al,
                project_id = label.project_id,
                label_id = label.id,
                user_id=session["user_id"],
                track_progress=True,
            )
            label.al_key = "setup"
            db.session.commit()
            flash(_("Seting up active learn pipeline for label {label_name}, "
                    "please wait a few minutes and try again.").format(
                        label_name=label.name
                    ), category="warning")
            return redirect(url_for("labels"))

    # Assign label value if given
    if request.method == "POST":
        value_str = settings.LABELS[-1 - int(request.form["value"])][0]
        entry_id = request.form["entry_id"]
        entry = get_entry(request.form["entry_id"], by="id")
        if entry is None:
            flash(_("Error on active learning for label {label_name} report to developers.").format(
                        label_name=label.name), category="error")
            return redirect("/")

        add_entry_label(label_id, entry.id, session["user_id"], value_str)
        launch_task_with_tracking(
            add_label_value,
            project_id = label.project_id,
            label_id = label.id,
            dataset_id = entry.dataset_id,
            entry_id = entry.entry_id,
            value = value_str,
            user_id=session["user_id"],
            track_progress=False,
        )

        # Drop labeled entry from AL cache
        cache = json.loads(label.cache) # type: ignore
        comp_id = COMPOSITE_ID.format(dataset_id=entry.dataset_id, entry_id= entry.entry_id)
        if comp_id in cache:
            cache.remove(
                COMPOSITE_ID.format(dataset_id=entry.dataset_id, entry_id= entry.entry_id)
            )
            label.cache = json.dumps(cache)

        # Check train
        if label.training_counter == 4:
            launch_task_with_tracking(
                train_model,
                project_id = label.project_id,
                label_id = label.id,
                user_id=session["user_id"],
                track_progress=True,
            )
            label.training_counter = 0
        else:
            label.training_counter += 1

        db.session.commit()

        flash(
            _(f'Added value "{value_str}" for entry {request.form["entry_id"]}.').format(
                label_name=label.name
            ),
            category="success",
        )


    data = {
        "label": label,
        "highlight": get_highlights(),
        "valid_entry": True,
        "messages": json.loads(label.metrics), # type: ignore
    }
    dataset_id, entry_id = eval(json.loads(label.cache)[0]) # type: ignore
    data = render_entry(str(entry_id), int(dataset_id), data)
    return render_template("al-entry.html", **data)


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
