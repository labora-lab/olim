import json
from datetime import datetime

import pandas as pd
from flask import flash, session
from flask_babel import _
from tqdm import tqdm

from ..database import (
    Label,
    add_entry_label,
    check_entries_exist,
    get_entry,
    get_labels,
    new_label,
)
from ..label_types import get_class_values, is_free_text_label

REQUIRED_COLUMNS = ("entry_id", "label", "value")
MAX_EXAMPLES = 5


def label_value_policy(label: Label | None) -> tuple[dict[str, str] | None, bool]:
    """How uploaded values must look for a label.

    Returns:
        (allowed, multi_select) where allowed maps a lowercased value to the
        option value declared by the label, or is None when any value is
        accepted (free text, unconfigured or untyped labels), and multi_select
        tells whether several values of one entry are combined.
    """
    if label is None or not label.label_type or is_free_text_label(label.label_type):
        return None, False

    declared = get_class_values(label, include_abstain=True)
    allowed = {value.lower(): value for value in declared} if declared else None
    settings = label.label_settings or {}
    multi_select = label.label_type == "multiple_choice" and not settings.get(
        "single_select", False
    )
    return allowed, multi_select


def label_upload(
    df: pd.DataFrame,
    user_id: int | None = None,
    project_id: int | None = None,
    dataset_id: int = 1,
) -> int:
    """Upload label data from a dataframe

    Values are matched case-insensitively against the options a label declares
    and stored as the declared option; rows with any other value are skipped and
    reported. For multi-select labels, the rows of one entry are combined into the
    JSON list the labelling screen stores; for other labels the latest row wins.

    Args:
        df: DataFrame with entry_id, label and value columns (created optional)
        user_id: User ID to register labels as, defaults to current session user
        project_id: Project ID
        dataset_id: Dataset ID

    Returns:
        Number of label values stored
    """
    user_id = user_id or session["user_id"]
    project_id = project_id or session["project_id"]

    missing_columns = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing_columns:
        flash(
            _("The labelling file is missing the columns: {columns}").format(
                columns=", ".join(missing_columns)
            ),
            category="error",
        )
        return 0

    df = df.dropna(subset=list(REQUIRED_COLUMNS)).copy()
    for column in REQUIRED_COLUMNS:
        df[column] = df[column].astype(str).str.strip()

    # Parse dates and sort by them
    if "created" not in df.columns:
        df["created"] = datetime.now()

    df["created"] = pd.to_datetime(df["created"])
    df = df.sort_values(by="created", kind="stable")

    # Bulk check which entries exist
    unique_entry_ids = list(df["entry_id"].unique())
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

    labels = {label.name: label for label in get_labels(project_id=project_id)}
    existing_ids_set = set(existing_ids)

    # Collect the values of each (entry, label), checked against the label's options
    collected: dict[tuple[str, str], list[tuple[str, datetime]]] = {}
    invalid_count = 0
    invalid_examples: dict[str, None] = {}
    for entry_id, label_name, value, created in df[
        ["entry_id", "label", "value", "created"]
    ].itertuples(index=False):
        if entry_id not in existing_ids_set:
            continue
        allowed = label_value_policy(labels.get(label_name))[0]
        if allowed is not None:
            if value.lower() not in allowed:
                invalid_count += 1
                if len(invalid_examples) < MAX_EXAMPLES:
                    invalid_examples[f"{label_name}: {value}"] = None
                continue
            value = allowed[value.lower()]
        collected.setdefault((entry_id, label_name), []).append((value, created))

    if invalid_count:
        flash(
            _(
                "Skipped {count} rows whose value is not an option of the label "
                "(for example {examples}). Check the options in the label settings."
            ).format(count=invalid_count, examples="; ".join(invalid_examples)),
            category="warning",
        )

    stored = 0
    for (entry_id, label_name), values in tqdm(collected.items()):
        # Get entry within selected dataset
        entry = get_entry((dataset_id, entry_id))
        if entry is None:
            continue

        # If the label doesnt exist create it
        if label_name not in labels:
            labels[label_name] = new_label(label_name, user_id, project_id)
        label = labels[label_name]

        created = values[-1][1]
        if label_value_policy(label)[1]:
            value = json.dumps(list(dict.fromkeys(v[0] for v in values)))
        else:
            value = values[-1][0]

        # Add the label to the entry
        add_entry_label(label.id, entry.id, user_id, value, created=created)
        stored += 1

    flash(_("Uploaded {count} label values").format(count=stored), category="success")
    return stored
