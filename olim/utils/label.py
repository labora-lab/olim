import json
import unicodedata
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
from ..label_types import get_class_values, is_free_text_label, parse_label_value

REQUIRED_COLUMNS = ("entry_id", "label", "value")
MAX_EXAMPLES = 5

# Reasons a row's value is rejected
NOT_AN_OPTION = "not_an_option"
SEVERAL_FOR_SINGLE = "several_for_single"
EMPTY_VALUE = "empty_value"


def option_key(value: str) -> str:
    """Comparison key for option values.

    Ignores case, repeated or odd whitespace and how accented letters are
    encoded (a precomposed "ç" and "c" + combining cedilla look the same but
    differ byte by byte, depending on the system the text was typed on).
    """
    return " ".join(unicodedata.normalize("NFC", value).split()).casefold()


def label_value_policy(label: Label | None) -> tuple[dict[str, str] | None, bool]:
    """How uploaded values must look for a label.

    Returns:
        (allowed, multi_select) where allowed maps an option_key() to the option
        value declared by the label, or is None when any value is accepted (free
        text, unconfigured or untyped labels), and multi_select tells whether
        several values of one entry are combined.
    """
    if label is None or not label.label_type or is_free_text_label(label.label_type):
        return None, False

    declared = get_class_values(label, include_abstain=True)
    allowed = {option_key(value): value for value in declared} if declared else None
    settings = label.label_settings or {}
    multi_select = label.label_type == "multiple_choice" and not settings.get(
        "single_select", False
    )
    return allowed, multi_select


def check_label_value(label: Label | None, raw_value: str) -> tuple[list[str], str | None]:
    """Turn an uploaded value into the option values it selects.

    Option-based labels accept a single option (``Red``) or the JSON list the
    labelling screen stores and the export writes (``["Red", "Blue"]``). Free
    text and untyped labels keep the value exactly as written.

    Returns:
        (values, error) where values are the declared option values and error is
        None or the reason the row has to be skipped
    """
    if label is None or not label.label_type or is_free_text_label(label.label_type):
        return [raw_value], None

    allowed, multi_select = label_value_policy(label)
    values = [v.strip() for v in parse_label_value(raw_value) if v.strip()]
    if not values:
        return [], EMPTY_VALUE
    if len(values) > 1 and not multi_select:
        return [], SEVERAL_FOR_SINGLE
    if allowed is None:
        return values, None
    if any(option_key(v) not in allowed for v in values):
        return [], NOT_AN_OPTION
    return [allowed[option_key(v)] for v in values], None


def clean_label_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Drop incomplete rows and normalize the text columns of a labelling file.

    Entry IDs are kept exactly as written; they're matched with and without
    surrounding spaces later.
    """
    df = df.dropna(subset=list(REQUIRED_COLUMNS)).copy()
    df["entry_id"] = df["entry_id"].astype(str)
    df["label"] = df["label"].astype(str).str.strip()
    df["value"] = df["value"].astype(str).str.strip()
    return df


def new_label_names(df: pd.DataFrame, project_id: int) -> list[str]:
    """Label names used in a labelling file that don't exist in the project yet."""
    if "label" not in df.columns:
        return []
    names = df["label"].dropna().astype(str).str.strip()
    known = {label.name for label in get_labels(project_id=project_id)}
    return sorted({name for name in names if name and name not in known})


def suggest_label_config(df: pd.DataFrame, label_name: str) -> dict:
    """Suggest a configuration for a new label from the values in a labelling file.

    Returns:
        {"options": distinct values in order of appearance, "multi_select": True
        if any entry has several values, "rows": number of rows}
    """
    df = clean_label_frame(df)
    rows = df[df["label"] == label_name]
    options: dict[str, str] = {}
    multi_select = False
    for _entry, group in rows.groupby("entry_id", sort=False):
        entry_values: set[str] = set()
        for raw in group["value"]:
            for value in parse_label_value(raw):
                value = " ".join(value.split())
                if value:
                    options.setdefault(option_key(value), value)
                    entry_values.add(option_key(value))
        multi_select = multi_select or len(entry_values) > 1
    return {"options": list(options.values()), "multi_select": multi_select, "rows": len(rows)}


def _flash_skipped(errors: dict[str, list[str]]) -> None:
    messages = {
        NOT_AN_OPTION: _(
            "Skipped {count} rows with values that are not options of the label "
            "(for example {examples}). Check the options in the label settings."
        ),
        SEVERAL_FOR_SINGLE: _(
            "Skipped {count} rows with several options for a single-select label "
            "(for example {examples}). Switch the label to multi-select in its "
            "settings to upload several options per entry."
        ),
        EMPTY_VALUE: _("Skipped {count} rows without any option (for example {examples})."),
    }
    for reason, examples in errors.items():
        flash(
            messages[reason].format(
                count=len(examples), examples="; ".join(dict.fromkeys(examples[:MAX_EXAMPLES]))
            ),
            category="warning",
        )


def label_upload(
    df: pd.DataFrame,
    user_id: int | None = None,
    project_id: int | None = None,
    dataset_id: int = 1,
) -> int:
    """Upload label data from a dataframe

    A value is one option or a JSON list of options (``["A", "B"]``, the format
    the export writes). Values are matched against the options a label declares,
    ignoring case, spacing and accent encoding, and stored as the declared
    option; rows with any other value are skipped and reported. For multi-select
    labels, the rows of one entry are combined into the JSON list the labelling
    screen stores; for other labels the latest row wins.

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

    df = clean_label_frame(df)

    # Parse dates and sort by them
    if "created" not in df.columns:
        df["created"] = datetime.now()

    df["created"] = pd.to_datetime(df["created"])
    df = df.sort_values(by="created", kind="stable")

    # Bulk check which entries exist, as written or without surrounding spaces
    unique_entry_ids = list(df["entry_id"].unique())
    candidates = list(dict.fromkeys([*unique_entry_ids, *(e.strip() for e in unique_entry_ids)]))
    existing_ids_set = set(check_entries_exist(candidates, dataset_id)[0])
    resolved = {}
    for raw_id in unique_entry_ids:
        if raw_id in existing_ids_set:
            resolved[raw_id] = raw_id
        elif raw_id.strip() in existing_ids_set:
            resolved[raw_id] = raw_id.strip()
    missing_ids = [e for e in unique_entry_ids if e not in resolved]

    # Flash summary
    total_count = len(unique_entry_ids)
    existing_count = len(resolved)
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

    # Collect the values of each (entry, label), checked against the label's options
    collected: dict[tuple[str, str], list[tuple[list[str], datetime]]] = {}
    errors: dict[str, list[str]] = {}
    for raw_id, label_name, raw_value, created in df[
        ["entry_id", "label", "value", "created"]
    ].itertuples(index=False):
        entry_id = resolved.get(raw_id)
        if entry_id is None:
            continue
        values, error = check_label_value(labels.get(label_name), raw_value)
        if error:
            errors.setdefault(error, []).append(f"{label_name}: {raw_value}")
            continue
        collected.setdefault((entry_id, label_name), []).append((values, created))

    _flash_skipped(errors)

    stored = 0
    for (entry_id, label_name), rows in tqdm(collected.items()):
        # Get entry within selected dataset
        entry = get_entry((dataset_id, entry_id))
        if entry is None:
            continue

        # If the label doesnt exist create it
        if label_name not in labels:
            labels[label_name] = new_label(label_name, user_id, project_id)
        label = labels[label_name]

        created = rows[-1][1]
        if label_value_policy(label)[1]:
            # Same format the labelling screen stores: a JSON list of the options
            value = json.dumps(list(dict.fromkeys(v for row in rows for v in row[0])))
        else:
            value = rows[-1][0][0]

        # Add the label to the entry
        add_entry_label(label.id, entry.id, user_id, value, created=created)
        stored += 1

    flash(_("Uploaded {count} label values").format(count=stored), category="success")
    return stored
