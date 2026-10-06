"""Export a project's data with its label values, one row per entry."""

import csv
import io
import json
from collections.abc import Generator

from ..database import Dataset, Label, get_label_values, iter_dataset_entries
from ..settings import ES_INDEX
from .es import es_list_fields, es_search

BATCH_SIZE = 1000


def cell_text(value: object) -> str:
    """Show a stored value as text (for the editing grid and CSV exports)."""
    if value is None:
        return ""
    if isinstance(value, dict | list):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def export_columns(dataset: Dataset, es_fields: list[str] | None = None) -> list[tuple[str, str]]:
    """Columns of the file a dataset was uploaded from, and where each value is stored.

    Returns:
        [(column name, source)] where source is "_id" (the entry ID) or a field
        of the search document. The upload stores the text column as "text" and
        renames a metadata column called "text" to "metadata_text".
    """
    if dataset.columns and dataset.id_column and dataset.text_column:
        columns = []
        for column in dataset.columns:
            if column == dataset.id_column:
                columns.append((column, "_id"))
            elif column == dataset.text_column:
                columns.append((column, "text"))
            elif column == "text":
                columns.append((column, "metadata_text"))
            else:
                columns.append((column, column))
        return columns

    # Datasets created before the layout was recorded: rebuild it from the index
    if es_fields is None:
        try:
            es_fields = es_list_fields(index=ES_INDEX.format(dataset_id=dataset.id))
        except Exception:
            es_fields = []
    columns = [("id", "_id"), ("text", "text")]
    for field in sorted(f for f in es_fields if f != "text"):
        columns.append(("text" if field == "metadata_text" else field, field))
    return columns


def label_headers(labels: list[Label], taken: list[str]) -> list[str]:
    """One column name per label, made unique against the data columns."""
    used = set(taken)
    headers = []
    for label in labels:
        name = label.name
        while name in used:
            name = f"{name} (label)"
        used.add(name)
        headers.append(name)
    return headers


def export_csv(datasets: list[Dataset], labels: list[Label]) -> Generator[str]:
    """Stream a CSV with every entry of the datasets and the value of each label.

    The data columns are those of the original file(s), in file order; with
    several datasets a leading "dataset" column says where each row comes from
    and the columns are the union of all files. Label values are written as
    stored, so multi-select answers keep the ["A", "B"] format the label upload
    accepts. Entries are read in batches, so memory use doesn't grow with the
    dataset size.
    """
    layouts = {d.id: export_columns(d) for d in datasets}
    with_dataset = len(datasets) > 1

    data_headers: list[str] = []
    for dataset in datasets:
        for header, _source in layouts[dataset.id]:
            if header not in data_headers:
                data_headers.append(header)
    if with_dataset:
        data_headers.insert(0, "dataset")
    headers = data_headers + label_headers(labels, data_headers)
    label_ids = [label.id for label in labels]

    buffer = io.StringIO()
    writer = csv.writer(buffer)

    def flush() -> str:
        text = buffer.getvalue()
        buffer.seek(0)
        buffer.truncate(0)
        return text

    # BOM so spreadsheet programs detect UTF-8 (the label upload accepts it too)
    writer.writerow(headers)
    yield "﻿" + flush()

    for dataset in datasets:
        layout = layouts[dataset.id]
        index = ES_INDEX.format(dataset_id=dataset.id)
        for entries in iter_dataset_entries(dataset.id, BATCH_SIZE):
            ids = [e.entry_id for e in entries]
            hits = es_search(index=index, query={"ids": {"values": ids}}, size=len(ids))
            docs = {hit["_id"]: hit["_source"] for hit in hits["hits"]["hits"]}
            values = get_label_values([e.id for e in entries], label_ids)

            for entry in entries:
                doc = docs.get(entry.entry_id, {})
                row = dict.fromkeys(data_headers, "")
                if with_dataset:
                    row["dataset"] = dataset.name
                for header, source in layout:
                    row[header] = entry.entry_id if source == "_id" else cell_text(doc.get(source))
                labels_part = [cell_text(values.get((entry.id, lid))) for lid in label_ids]
                writer.writerow([row[h] for h in data_headers] + labels_part)
            yield flush()
