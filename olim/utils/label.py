import pandas as pd
from flask import session
from tqdm import tqdm

from ..database import add_entry_label, get_labels, new_label


def label_upload(df, user_id=None) -> None:
    """Upload label data from a dataframe

    Args:
        df: DataFrame with label data
        user_id: User ID to register labels as, defaults to current session user
    """
    user_id = user_id or session["user_id"]
    # Parse dates and sort by them
    df["created"] = pd.to_datetime(df["created"])
    df = df.sort_values(by="created")

    # Group by the columns we are interested
    group = df.groupby(["entry_id", "label", "value", "created"]).any().index

    # Get a list of existing labels and respective ids
    labels = {L.name: L.id for L in get_labels()}

    # Store labels
    for entry_id, label, value, created in tqdm(group):
        # If the label doesnt exist create it
        if label not in labels:
            label_creation_result = new_label(label, user_id)
            labels[label_creation_result.name] = label_creation_result.id
        # Add the label to the entry
        add_entry_label(labels[label], entry_id, user_id, value, created=created)
