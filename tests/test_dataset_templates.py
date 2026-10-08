"""Dataset management pages render for every state the routes can hand them."""

import re
from datetime import datetime
from types import SimpleNamespace

import pytest
from flask import render_template, session

from olim import app
from olim.datasets import PAGE_SIZES, build_grid_rows, cell_text, display_fields
from olim.entry_types.flexible_text import DEFAULT_COLUMN_CONFIG


@pytest.fixture(autouse=True)
def request_context():
    with app.test_request_context("/"):
        session["language"] = "en_US"
        session["role"] = "admin"
        yield


def make_dataset(**overrides):
    values = {
        "id": 3,
        "name": "Notes",
        "id_column": "id",
        "text_column": "body",
        "columns": ["id", "body", "source"],
        "sep": "\t",
        "encoding": "utf-8",
        "created": datetime(2026, 10, 6, 9, 30),
        "creator": SimpleNamespace(name="Ana", username="ana"),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class TestList:
    def test_unlinked_dataset_without_stats_renders(self):
        """get_dataset_stats used to drop datasets with no project link."""
        dataset = make_dataset()
        html = render_template(
            "datasets/list.html", datasets=[dataset], stats={}, entry_types={3: "single_text"}
        )
        assert "Notes" in html
        assert "/datasets/3/delete" in html
        assert "Not linked" in html

    def test_empty_list(self):
        html = render_template("datasets/list.html", datasets=[], stats={}, entry_types={})
        assert "No datasets found" in html


class TestGridRows:
    """Rows the entries grid loads for a page."""

    def test_rows_hold_the_id_and_each_field_as_text(self):
        dataset = make_dataset()
        entries = [SimpleNamespace(entry_id="e1")]
        docs = {"e1": {"text": 'He said "hi"\nbye', "source": 12}}
        rows = build_grid_rows(entries, docs, display_fields(dataset, []))
        assert rows == [
            {"_id": "e1", "_missing": False, "text": 'He said "hi"\nbye', "source": "12"}
        ]

    def test_entry_missing_from_index_is_flagged(self):
        rows = build_grid_rows(
            [SimpleNamespace(entry_id="gone")], {}, display_fields(make_dataset(), [])
        )
        assert rows[0]["_missing"] is True
        assert rows[0]["text"] == ""

    def test_absent_and_structured_values(self):
        assert cell_text(None) == ""
        assert cell_text({"a": "ç"}) == '{"a": "ç"}'
        assert cell_text([1, 2]) == "[1, 2]"

    def test_legacy_dataset_uses_index_fields(self):
        dataset = make_dataset(columns=None, id_column=None, text_column=None)
        rows = build_grid_rows(
            [SimpleNamespace(entry_id="e1")],
            {"e1": {"text": "x", "extra": "y"}},
            display_fields(dataset, ["text", "extra"]),
        )
        assert rows[0]["extra"] == "y"


class TestEdit:
    def render(self, **overrides):
        values = {
            "dataset": make_dataset(),
            "stats": {"entry_count": 4, "projects": []},
            "projects": [SimpleNamespace(id=1, name="P1"), SimpleNamespace(id=2, name="P2")],
            "linked_project_ids": {2},
            "entry_type": "single_text",
            "can_append": True,
            "is_legacy": False,
            "expected_columns": ["id", "body", "source"],
            "CHUNK_SIZE": 1024,
            "page_sizes": PAGE_SIZES,
            "grid_fields": display_fields(make_dataset(), []),
            "column_config": DEFAULT_COLUMN_CONFIG,
            "column_config_fields": [{"field": "source", "label": "source"}],
        }
        values.update(overrides)
        return render_template("datasets/edit.html", **values)

    def test_renders_with_append_and_table(self):
        html = self.render()
        assert 'id="append-file-input"' in html
        # The grid loads pages from the JSON endpoint, with the dataset's columns
        assert '"/datasets/3/entries"' in html
        assert 'id="entries-grid"' in html
        assert '{"field": "source", "label": "source"}' in html
        assert "tabulator-tables@" in html
        # Tab separator is shown as \t so it can be typed back
        assert 'id="append-sep" value="\\t"' in html
        # JS placeholders survive Jinja's %-formatting
        assert "{count} unsaved changes" in html

    def test_linked_projects_are_checked(self):
        html = self.render()
        checkboxes = re.findall(
            r'<input type="checkbox" name="projects" value="(\d+)"[^>]*?(checked)?>', html
        )
        assert sorted(v for v, checked in checkboxes if checked) == ["2"]
        assert len(checkboxes) == 2

    def test_tabs_and_upload_modes(self):
        html = self.render()
        assert re.findall(r'data-tab="(\w+)"', html) == [
            "data",
            "columns",
            "add",
            "details",
        ]
        assert re.findall(r'name="append-mode" value="(\w+)"', html) == ["rows", "columns"]
        assert '"/datasets/3/columns"' in html

    def test_flexible_text_gets_the_column_editor(self):
        html = self.render(entry_type="flexible_text")
        assert 'id="dataset-column-config"' in html
        assert 'data-option="show_remaining_as_metadata"' in html
        assert 'fields: [{"field": "source", "label": "source"}]' in html

    def test_single_text_has_no_column_editor(self):
        html = self.render()
        assert 'id="dataset-column-config"' not in html
        assert "available for datasets uploaded as Flexible Text" in html

    def test_legacy_shows_column_pickers(self):
        html = self.render(is_legacy=True, dataset=make_dataset(columns=None))
        assert 'id="append-id-column"' in html

    def test_unsupported_format_hides_append(self):
        html = self.render(can_append=False, entry_type="pdf")
        assert 'id="append-file-input"' not in html


def test_upload_form_uses_the_shared_column_editor():
    html = render_template("datasets/new.html", CHUNK_SIZE=1024, projects=[])
    assert 'id="upload-column-config"' in html
    assert 'name="column_config"' in html
    assert "createColumnConfigEditor" in html
