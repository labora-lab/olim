"""Export every entry with its original columns plus one column per label."""

import csv
import io
import json
from types import SimpleNamespace

import pytest

from olim.utils import export


def dataset(dataset_id, name, columns=None, id_column="id", text_column="body"):
    return SimpleNamespace(
        id=dataset_id, name=name, columns=columns, id_column=id_column, text_column=text_column
    )


def entry(pk, entry_id):
    return SimpleNamespace(id=pk, entry_id=entry_id)


@pytest.fixture
def storage(monkeypatch):
    """In-memory entries, search documents and label values."""
    data = {"entries": {}, "docs": {}, "values": {}, "batches": []}

    def iter_entries(dataset_id, batch_size):
        items = data["entries"].get(dataset_id, [])
        for start in range(0, len(items), batch_size):
            data["batches"].append(dataset_id)
            yield items[start : start + batch_size]

    def search(index, query, size):
        docs = data["docs"][index]
        ids = query["ids"]["values"]
        return {"hits": {"hits": [{"_id": i, "_source": docs[i]} for i in ids if i in docs]}}

    monkeypatch.setattr(export, "iter_dataset_entries", iter_entries)
    monkeypatch.setattr(export, "es_search", search)
    monkeypatch.setattr(
        export,
        "get_label_values",
        lambda pks, label_ids: {
            k: v for k, v in data["values"].items() if k[0] in pks and k[1] in label_ids
        },
    )
    return data


def read(datasets, labels):
    text = "".join(export.export_csv(datasets, labels))
    assert text.startswith("﻿")
    return list(csv.reader(io.StringIO(text[1:])))


LABELS = [SimpleNamespace(id=1, name="Topic"), SimpleNamespace(id=2, name="source")]


def test_one_dataset_keeps_the_file_columns_and_adds_labels(storage):
    ds = dataset(3, "Notes", columns=["source", "id", "body", "text"])
    storage["entries"][3] = [entry(10, "a"), entry(11, "b")]
    storage["docs"]["dataset-3"] = {
        "a": {"text": "first\nline", "source": "web", "metadata_text": "extra"},
        "b": {"text": "second"},  # empty cells are not stored on upload
    }
    storage["values"] = {(10, 1): json.dumps(["Cardio", "Onco"]), (11, 2): "yes"}

    rows = read([ds], LABELS)
    # The label "source" clashes with a file column, so it gets a suffix
    assert rows[0] == ["source", "id", "body", "text", "Topic", "source (label)"]
    assert rows[1] == ["web", "a", "first\nline", "extra", '["Cardio", "Onco"]', ""]
    assert rows[2] == ["", "b", "second", "", "", "yes"]


def test_all_datasets_union_columns_with_dataset_column(storage):
    first = dataset(1, "First", columns=["id", "body", "age"])
    second = dataset(
        2, "Second", columns=["code", "content", "city"], id_column="code", text_column="content"
    )
    storage["entries"] = {1: [entry(1, "a")], 2: [entry(2, "x")]}
    storage["docs"] = {
        "dataset-1": {"a": {"text": "t1", "age": 30}},
        "dataset-2": {"x": {"text": "t2", "city": "Rio"}},
    }

    rows = read([first, second], LABELS[:1])
    assert rows[0] == ["dataset", "id", "body", "age", "code", "content", "city", "Topic"]
    assert rows[1] == ["First", "a", "t1", "30", "", "", "", ""]
    assert rows[2] == ["Second", "", "", "", "x", "t2", "Rio", ""]


def test_legacy_dataset_rebuilds_columns_from_the_index():
    legacy = dataset(5, "Old", columns=None, id_column=None, text_column=None)
    assert export.export_columns(legacy, ["text", "source", "metadata_text"]) == [
        ("id", "_id"),
        ("text", "text"),
        ("text", "metadata_text"),
        ("source", "source"),
    ]


def test_entries_are_read_in_batches(storage, monkeypatch):
    monkeypatch.setattr(export, "BATCH_SIZE", 2)
    ds = dataset(3, "Notes", columns=["id", "body"])
    storage["entries"][3] = [entry(i, f"e{i}") for i in range(5)]
    storage["docs"]["dataset-3"] = {f"e{i}": {"text": str(i)} for i in range(5)}

    rows = read([ds], [])
    assert [r[0] for r in rows[1:]] == ["e0", "e1", "e2", "e3", "e4"]
    assert storage["batches"] == [3, 3, 3]


def test_entry_missing_from_the_index_still_has_a_row(storage):
    ds = dataset(3, "Notes", columns=["id", "body"])
    storage["entries"][3] = [entry(1, "gone")]
    storage["docs"]["dataset-3"] = {}
    assert read([ds], [])[1] == ["gone", ""]
