import pandas as pd
from flask import flash, session
from flask_babel import _
from tqdm import tqdm

from ..database import add_entry_label, get_dataset, get_entry, get_labels, new_label


def label_upload(
    df, user_id: int | None = None, project_id: int | None = None, dataset_id: int | None = None
) -> None:
    """Upload label data from a dataframe

    Args:
        df: DataFrame with label data
        user_id: User ID to register labels as, defaults to current session user
    """
    user_id = user_id or session["user_id"]
    project_id = project_id or session["project_id"]
    # Parse dates and sort by them
    df["created"] = pd.to_datetime(df["created"])
    df = df.sort_values(by="created")

    # Group by the columns we are interested
    group = df.groupby(["entry_id", "label", "value", "created"]).any().index

    # Get a list of existing labels and respective ids
    labels = {L.name: L.id for L in get_labels(project_id=project_id)}

    # Store labels
    for entry_id, label_name, value, created in tqdm(group):
        # Get entry within selected dataset
        entry = get_entry((dataset_id, str(entry_id)))
        if not entry:
            dataset = get_dataset(dataset_id)  # type: ignore (¬_¬)
            flash(
                _("Entry id: {entry_id} not found on dataset {dataset_name}").format(
                    entry_id=entry_id,
                    dataset_name=dataset.name,  # type: ignore (¬_¬)
                )
            )
            continue

        # If the label doesnt exist create it
        if label_name not in labels:
            label = new_label(label_name, user_id, project_id)
            labels[label_name] = label.id
        # Add the label to the entry
        add_entry_label(labels[label_name], entry.id, user_id, value, created=created)
