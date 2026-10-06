"""Checks run before appending a file to an existing dataset.

An append that slips a conflicting ID or a renamed column through would silently
overwrite documents in the search index or scatter values into new fields, so every
conflict has to be caught up front and reported, not skipped.
"""

from types import SimpleNamespace

import pytest

from olim import app
from olim.datasets import display_fields, resolve_layout
from olim.entry_types import single_text
from olim.tasks.upload_data import check_append_file, read_csv_ids

COLUMNS = ["id", "body", "date", "source"]


def no_existing(ids):
    return []


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
        report = check_append_file(COLUMNS, COLUMNS, ["a", "b"], 0, no_existing)
        assert report["ok"]
        assert report["new_entries"] == 2

    def test_column_order_does_not_matter(self):
        report = check_append_file(list(reversed(COLUMNS)), COLUMNS, ["a"], 0, no_existing)
        assert report["ok"]

    def test_missing_and_unexpected_are_reported_separately(self):
        header = ["id", "body", "Source", "extra"]
        report = check_append_file(header, COLUMNS, ["a"], 0, no_existing)
        assert not report["ok"]
        assert report["missing_columns"] == ["date", "source"]
        assert report["unexpected_columns"] == ["Source", "extra"]


class TestIds:
    def test_duplicates_inside_the_file(self):
        report = check_append_file(COLUMNS, COLUMNS, ["a", "b", "a", "c", "b", "a"], 0, no_existing)
        assert not report["ok"]
        assert report["duplicate_ids"] == {"count": 2, "sample": ["a", "b"]}

    def test_ids_already_in_the_dataset(self):
        report = check_append_file(
            COLUMNS, COLUMNS, ["a", "b", "c"], 0, lambda ids: [i for i in ids if i in {"c", "a"}]
        )
        assert not report["ok"]
        # Reported in file order, not in whatever order the database returns them
        assert report["existing_ids"] == {"count": 2, "sample": ["a", "c"]}
        assert report["new_entries"] == 1

    def test_sample_is_capped_but_count_is_not(self):
        ids = [str(i) for i in range(50)]
        report = check_append_file(COLUMNS, COLUMNS, ids, 0, lambda chunk: chunk)
        assert report["existing_ids"]["count"] == 50
        assert len(report["existing_ids"]["sample"]) == 20

    def test_rows_without_id(self):
        report = check_append_file(COLUMNS, COLUMNS, ["a"], 3, no_existing)
        assert not report["ok"]
        assert report["empty_ids"] == 3

    def test_empty_file_is_not_ok(self):
        assert not check_append_file(COLUMNS, COLUMNS, [], 0, no_existing)["ok"]


class TestIdNormalization:
    """IDs must be compared in exactly the form the upload stores them."""

    @pytest.mark.parametrize(
        "rows",
        [
            ["1,first", "2,second", "10,third"],
            # A missing ID turns the column into floats: "1.0", not "1"
            ["1,first", ",no id", "3,third"],
            ["a-1,first", "b-2,second"],
        ],
    )
    def test_matches_generate_upload_batches(self, tmp_path, rows):
        csv = tmp_path / "data.csv"
        csv.write_text("id,body\n" + "\n".join(rows) + "\n")

        ids, _empty = read_csv_ids(str(csv), "id", ",", "utf-8")
        uploaded = [
            entry["id"]
            for batch in single_text.generate_upload_batches(str(csv), "id", "body")
            for entry in batch
        ]
        # The uploader turns a blank ID into the placeholder -1; the check reports
        # those rows as missing an ID instead, so they never reach the upload
        assert set(ids) == set(uploaded) - {"-1", "-1.0"}

    def test_missing_ids_are_counted(self, tmp_path):
        csv = tmp_path / "data.csv"
        csv.write_text("id,body\n1,first\n,no id\n3,third\n")
        ids, empty = read_csv_ids(str(csv), "id", ",", "utf-8")
        assert empty == 1
        assert len(ids) == 2

    def test_duplicates_are_kept_for_the_check(self, tmp_path):
        csv = tmp_path / "data.csv"
        csv.write_text("id,body\nx,1\nx,2\n")
        assert read_csv_ids(str(csv), "id", ",", "utf-8")[0] == ["x", "x"]


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
