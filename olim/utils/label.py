from datetime import datetime

import pandas as pd
from flask import flash, session
from flask_babel import _
from tqdm import tqdm

from ..database import (
    add_entry_label,
    check_entries_exist,
    get_entry,
    get_label,
    get_labels,
    new_label,
)


def label_upload(
    df,
    user_id: int | None = None,
    project_id: int | None = None,
    dataset_id: int = 1,
    use_active_learning: bool = False,
) -> None:
    """Upload label data from a dataframe

    Args:
        df: DataFrame with label data
        user_id: User ID to register labels as, defaults to current session user
        project_id: Project ID
        dataset_id: Dataset ID
        use_active_learning: If True, submit through active learning pipeline
    """
    user_id = user_id or session["user_id"]
    project_id = project_id or session["project_id"]
    # Parse dates and sort by them
    if "created" not in df.columns:
        df["created"] = datetime.now()

    df["created"] = pd.to_datetime(df["created"])
    df = df.sort_values(by="created")

    # Bulk check which entries exist
    unique_entry_ids = [str(eid) for eid in df["entry_id"].unique()]
    existing_ids, missing_ids = check_entries_exist(unique_entry_ids, dataset_id)

    # Flash summary
    total_count = len(unique_entry_ids)
    existing_count = len(existing_ids)
    missing_count = len(missing_ids)

    if missing_ids:
        print(f"Missing entry IDs: {missing_ids}")
        flash(
            _("Entry check: {existing}/{total} entries found, {missing} missing").format(
                existing=existing_count, total=total_count, missing=missing_count
            ),
            category="warning",
        )
    else:
        flash(
            _("Entry check: {existing}/{total} entries found").format(
                existing=existing_count, total=total_count
            ),
            category="info",
        )

    # Group by the columns we are interested
    group = df.groupby(["entry_id", "label", "value", "created"]).any().index

    # Get a list of existing labels and respective ids
    labels = {L.name: L.id for L in get_labels(project_id=project_id)}

    # Store labels (only for existing entries)
    existing_ids_set = set(existing_ids)

    if use_active_learning:
        # Import here to avoid circular imports
        from ..active_learning import submit_label_value
        from ..celery_app import launch_task_with_tracking
        from ..tasks.active_learning import create_label_al

        processed_count = 0
        for entry_id, label_name, value, __ in tqdm(group, desc="Processing via active learning"):
            # Skip if entry doesn't exist
            if str(entry_id) not in existing_ids_set:
                continue

            # Get entry within selected dataset
            entry = get_entry((dataset_id, str(entry_id)))
            if entry is None:
                continue

            # If the label doesn't exist create it
            if label_name not in labels:
                label = new_label(label_name, user_id, project_id)
                labels[label_name] = label.id
                # Initialize active learning for new label
                launch_task_with_tracking(
                    create_label_al,
                    project_id=project_id,
                    label_id=label.id,
                    user_id=user_id,
                    track_progress=False,
                )

            # Get the label object
            label = get_label(labels[label_name])
            if label is None:
                continue

            # Submit through active learning pipeline (suppress individual flashes)
            skip_train = processed_count < len(group) - 1  # Skip training until the last value
            submit_label_value(
                label,
                entry,
                value,
                user_id,
                is_auto_label=False,
                suppress_flash=True,
                skip_train=skip_train,
            )
            processed_count += 1

        # Show summary flash message
        flash(
            _("Successfully processed {count} labels through active learning pipeline").format(
                count=processed_count
            ),
            category="success",
        )
    else:
        # Normal upload pipeline
        for entry_id, label_name, value, created in tqdm(group):
            # Skip if entry doesn't exist
            if str(entry_id) not in existing_ids_set:
                continue

            # Get entry within selected dataset
            entry = get_entry((dataset_id, str(entry_id)))
            if entry is None:
                continue

            # If the label doesnt exist create it
            if label_name not in labels:
                label = new_label(label_name, user_id, project_id)
                labels[label_name] = label.id
            # Add the label to the entry
            add_entry_label(labels[label_name], entry.id, user_id, value, created=created)
