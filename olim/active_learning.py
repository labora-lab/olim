from pathlib import Path

import numpy as np
import pandas as pd
from celery.result import AsyncResult
from flask import Response, flash, redirect, render_template, request, session, url_for
from flask_babel import _

from . import app, db, settings
from .celery_app import launch_task_with_tracking
from .database import (
    CeleryTask,
    Label,
    add_entry_label,
    get_datasets,
    get_entry,
    get_label,
)
from .functions import get_highlights, render_entry
from .tasks.active_learning import (
    COMPOSITE_ID,
    add_label_value,
    create_label_al,
    export_predictions,
    train_model,
)


def new_al(label: Label) -> None:
    return None


def submit_label_value(
    label, entry, value_str, user_id, is_auto_label=False, suppress_flash=False
) -> list[str]:
    """Helper function to submit a label value and handle all associated tasks"""
    # Add the label to the database
    add_entry_label(label.id, entry.id, user_id, value_str)

    # Launch task to process the label
    launch_task_with_tracking(
        add_label_value,
        project_id=label.project_id,
        label_id=label.id,
        dataset_id=entry.dataset_id,
        entry_id=entry.entry_id,
        value=value_str,
        user_id=user_id,
        track_progress=False,
    )

    # Drop labeled entry from AL cache
    cache = label.cache if label.cache else []
    comp_id = COMPOSITE_ID.format(dataset_id=entry.dataset_id, entry_id=entry.entry_id)

    # Handle both old format (string) and new format (list from JSON)
    cache_items_to_remove = []
    for cache_item in cache:
        if isinstance(cache_item, list):
            entry_composite_id, review_needed = cache_item
            if entry_composite_id == comp_id:
                cache_items_to_remove.append(cache_item)
        else:
            if cache_item == comp_id:
                cache_items_to_remove.append(cache_item)

    for item in cache_items_to_remove:
        cache.remove(item)

    if cache_items_to_remove:
        label.cache = cache

    # Check for training
    tasks = CeleryTask.query.filter_by(
        task_name="learner.train_model",
    ).all()
    pending_tasks = [
        task.id
        for task in tasks
        if task.kwargs["label_id"] == label.id and task.status in ["PENDING", "STARTED"]
    ]

    # Check train
    if label.training_counter >= 4 and not pending_tasks:
        launch_task_with_tracking(
            train_model,
            description=_("Training for label {label_name}").format(
                label_name=label.name
            ),
            project_id=label.project_id,
            label_id=label.id,
            user_id=user_id,
            track_progress=True,
        )
        label.training_counter = 0
    else:
        label.training_counter += 1

    # Flash appropriate message (only if not suppressed)
    if not suppress_flash:
        suffix = " (auto-label file)" if is_auto_label else ""
        flash(
            _('Added value "{value_str}" for entry {entry_id}.').format(
                value_str=value_str, entry_id=entry.entry_id
            )
            + suffix,
            category="success",
        )

    return cache_items_to_remove


@app.route("/al/<int:label_id>", methods=["GET", "POST"])
def catch_al(label_id: int) -> ...:
    label = get_label(label_id)
    if not label:
        flash(_("Label not found."), category="error")
        return redirect("/")

    # Create learner if it doen't exists
    if label.al_key is None:
        launch_task_with_tracking(
            create_label_al,
            description=_("Creating Active Learning for {label_name}").format(
                label_name=label.name
            ),
            project_id=label.project_id,
            label_id=label.id,
            user_id=session["user_id"],
            track_progress=True,
        )
        label.al_key = "setup"
        db.session.commit()
        flash(
            _(
                "Seting up Active Learning pipeline for label {label_name}, "
                "please wait a few minutes and try again."
            ).format(label_name=label.name),
            category="warning",
        )
        return redirect(url_for("labels", project_id=label.project_id))

    # Assign label value if given
    if request.method == "POST":
        value_str = settings.LABELS[-1 - int(request.form["value"])][0]
        entry_id = request.form["entry_id"]
        entry = get_entry(request.form["entry_id"], by="id")
        if entry is None:
            flash(
                _(
                    "Error on active learning for label {label_name} report to developers."
                ).format(label_name=label.name),
                category="error",
            )
            return redirect("/")

        # Use helper function to submit the label
        submit_label_value(
            label, entry, value_str, session["user_id"], is_auto_label=False
        )
        db.session.commit()

    data = {
        "label": label,
        "highlight": get_highlights(),
        "valid_entry": True,
        "messages": label.metrics if label.metrics else [],
    }
    cache = label.cache[:] if label.cache else []
    cache_index = 0

    while cache_index < len(cache):
        cache_item = cache[cache_index]
        # Handle both old format (string) and new format (list from JSON)
        if isinstance(cache_item, list):
            entry_composite_id, review_needed = cache_item
        else:
            entry_composite_id = cache_item
            review_needed = False

        dataset_id, entry_id = eval(entry_composite_id)
        print(dataset_id, entry_id)
        entry = get_entry((dataset_id, str(entry_id)), "composite")
        if entry is None:
            raise ValueError(f"Failed to fetch entry {entry_id}")

        # Check if entry has an auto-label and auto-submit it
        if label.auto_labels and entry_composite_id in label.auto_labels:
            auto_label_value = label.auto_labels[entry_composite_id]
            print(
                f"[AUTO-LABEL] Found auto-label for {entry_composite_id}: {auto_label_value}"
            )

            # Use helper function to submit the auto-label
            submit_label_value(
                label, entry, auto_label_value, session["user_id"], is_auto_label=True
            )

            # Move to next cache item
            cache_index += 1
            continue

        # Skip only if already labeled AND not marked for review
        if label in [el.label for el in entry.labels] and not review_needed:
            print(f"Skipping {dataset_id}, {entry_id}")
            cache_index += 1
        else:
            break

    # Only update cache on POST (after submission), not on GET
    if request.method == "POST":
        # Remove the processed items from cache
        updated_cache = cache[cache_index + 1 :]
        label.cache = updated_cache
    db.session.commit()
    data = render_entry(str(entry_id), int(dataset_id), data)
    return render_template("al-entry.html", **data)


@app.route("/al/<int:label_id>/gen_predictions", methods=["GET"])
def gen_predictions(label_id: int) -> ...:
    label = get_label(label_id)
    if not label:
        flash(_("Label not found."), category="error")
        return redirect("/")

    tasks = CeleryTask.query.filter_by(task_name="learner.export_predictions").all()
    pending_tasks = [
        task.id
        for task in tasks
        if task.kwargs["label_id"] == label_id and task.status in ["PENDING", "STARTED"]
    ]

    if any(pending_tasks):
        flash(
            _("Already processing export of predictions for label {label_name}").format(
                label_name=label.name
            ),
            category="warning",
        )
    else:
        flash(
            _(
                "Processing export of predictions for label {label_name}, "
                "please wait a few minutes."
            ).format(label_name=label.name),
            category="success",
        )
        launch_task_with_tracking(
            export_predictions,
            project_id=label.project_id,
            label_id=label.id,
            user_id=session["user_id"],
            description=_("Generating predictions for {label_name}").format(
                label_name=label.name
            ),
            track_progress=True,
        )
    return redirect(url_for("label_settings", label_id=label_id))


@app.route("/al/<int:label_id>/predictions/<task_id>", methods=["GET", "POST"])
def get_predictions(label_id: int, task_id: str) -> ...:
    label = get_label(label_id)
    if not label:
        flash(_("Label not found."), category="error")
        return redirect("/")

    res = AsyncResult(task_id)

    dataset_names = {}
    for dataset in get_datasets():
        if dataset.id not in dataset_names:
            dataset_names[dataset.id] = dataset.name

    if res.ready():
        preds = res.result["predictions"]  # type: ignore
        preds_values = [
            pred[0] if len(pred) == 1 else np.nan for pred in preds.values()
        ]
        preds_ids = [eval(i)[1] for i in preds.keys()]
        dataset_ids = [eval(i)[0] for i in preds.keys()]
        dataset_names = [dataset_names[i] for i in dataset_ids]
        pred_df = pd.DataFrame(
            {
                "entry_id": preds_ids,
                "dataset_id": dataset_ids,
                "dataset_name": dataset_names,
                "value": preds_values,
            }
        )

        # Create file for local saving
        filename = Path("/app/data/predictions")
        filename.mkdir(parents=True, exist_ok=True)
        filename = filename / f"{label.name}-0.95-predictions.csv"

        # Save to data folder
        print(f"Saving exported predictions to {filename}")
        pred_df.to_csv(filename)

        # download json res["predictions"] as csv
        return Response(
            pred_df.to_csv(index=False),
            mimetype="text/csv",
            headers={"Content-disposition": f"attachment; filename={filename.name}"},
        )
    else:
        flash(
            _("Error exporting predictions: {error}").format(error=res["error"]),
            category="error",
        )
        return redirect(url_for("label_settings", label_id=label_id))
