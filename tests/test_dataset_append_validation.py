"""Checks run before appending a file to an existing dataset.

A renamed or extra column would scatter values into new fields, so the header is
checked up front. IDs are checked batch by batch during the upload itself (see
test_entry_id_trimming.py), so files of any size stream through.
"""

from types import SimpleNamespace

import pytest

from olim import app
from olim.datasets import display_fields, resolve_layout
from olim.tasks.upload_data import check_append_columns

COLUMNS = ["id", "body", "date", "source"]


@pytest.fixture(autouse=True)
def request_context():
    with app.test_request_context("/"):
        yield


def make_dataset(**overrides):
    values = {
        "id": 1,
        "id_column": "id",
        "text_column": "body",
        "columns": COLUMNS,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class TestColumns:
    def test_identical_header_passes(self):
        assert check_append_columns(COLUMNS, COLUMNS)["ok"]

    def test_column_order_does_not_matter(self):
        assert check_append_columns(list(reversed(COLUMNS)), COLUMNS)["ok"]

    def test_missing_and_unexpected_are_reported_separately(self):
        report = check_append_columns(["id", "body", "Source", "extra"], COLUMNS)
        assert not report["ok"]
        assert report["missing_columns"] == ["date", "source"]
        assert report["unexpected_columns"] == ["Source", "extra"]


class TestLayout:
    def test_known_layout_is_used_as_is(self):
        assert resolve_layout(make_dataset(), None, None) == ("id", "body", COLUMNS)

    def test_legacy_dataset_needs_id_and_text_columns(self):
        with pytest.raises(ValueError):
            resolve_layout(make_dataset(columns=None), None, "body", es_fields=[])

    def test_legacy_rejects_same_id_and_text_column(self):
        with pytest.raises(ValueError):
            resolve_layout(make_dataset(columns=None), "id", "id", es_fields=[])

    def test_legacy_layout_comes_from_the_index(self):
        id_col, text_col, expected = resolve_layout(
            make_dataset(columns=None),
            "pk",
            "content",
            es_fields=["text", "source", "metadata_text"],
        )
        assert (id_col, text_col) == ("pk", "content")
        # metadata_text is how a CSV column named "text" is stored
        assert expected == ["pk", "content", "source", "text"]


class TestDisplayFields:
    def test_follows_csv_order_and_skips_id(self):
        fields = display_fields(make_dataset())
        assert [f["field"] for f in fields] == ["text", "date", "source"]
        assert fields[0]["label"] == "body"

    def test_csv_column_named_text_maps_to_metadata_text(self):
        dataset = make_dataset(columns=["id", "body", "text"])
        assert display_fields(dataset)[1] == {"field": "metadata_text", "label": "text"}

    def test_legacy_uses_index_fields(self):
        fields = display_fields(make_dataset(columns=None, text_column=None), ["text", "b", "a"])
        assert [f["field"] for f in fields] == ["text", "a", "b"]
