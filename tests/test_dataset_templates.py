"""Dataset management pages render for every state the routes can hand them."""

import re
from datetime import datetime
from types import SimpleNamespace

import pytest
from flask import render_template, session

from olim import app
from olim.datasets import PAGE_SIZES, display_fields


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


def render_table(dataset, entries, docs, page=1, pages=1, total=None, error=None):
    return render_template(
        "datasets/_entries_table.html",
        dataset=dataset,
        entries=entries,
        docs=docs,
        fields=display_fields(dataset, []),
        page=page,
        pages=pages,
        per_page=25,
        total=len(entries) if total is None else total,
        page_sizes=PAGE_SIZES,
        error=error,
    )


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


class TestEntriesTable:
    def test_cells_carry_entry_field_and_original_value(self):
        dataset = make_dataset()
        entries = [SimpleNamespace(entry_id="e1")]
        docs = {"e1": {"text": 'He said "hi"\nbye', "source": 12}}
        html = render_table(dataset, entries, docs)
        assert 'data-entry-id="e1" data-field="text"' in html
        assert 'data-original="He said &#34;hi&#34;\nbye"' in html
        assert 'data-field="source"' in html
        assert 'data-original="12"' in html
        # The id column is shown but never editable
        assert 'data-field="id"' not in html

    def test_entry_missing_from_index_is_disabled(self):
        html = render_table(make_dataset(), [SimpleNamespace(entry_id="gone")], {})
        assert "disabled" in html
        assert "Not found in the search engine" in html

    def test_pager_edges(self):
        entries = [SimpleNamespace(entry_id="e1")]
        first = render_table(
            make_dataset(), entries, {"e1": {"text": "x"}}, page=1, pages=3, total=60
        )
        assert "?page=2&amp;per_page=25" in first
        assert "?page=0" not in first
        assert "Page 1 of 3" in first

        last = render_table(
            make_dataset(), entries, {"e1": {"text": "x"}}, page=3, pages=3, total=60
        )
        assert "?page=4" not in last
        assert "?page=2&amp;per_page=25" in last

    def test_empty_dataset(self):
        html = render_table(make_dataset(), [], {}, total=0)
        assert "This dataset has no entries yet." in html

    def test_legacy_dataset_uses_index_fields(self):
        dataset = make_dataset(columns=None, id_column=None, text_column=None)
        html = render_template(
            "datasets/_entries_table.html",
            dataset=dataset,
            entries=[SimpleNamespace(entry_id="e1")],
            docs={"e1": {"text": "x", "extra": "y"}},
            fields=display_fields(dataset, ["text", "extra"]),
            page=1,
            pages=1,
            per_page=25,
            total=1,
            page_sizes=PAGE_SIZES,
            error=None,
        )
        assert 'data-field="extra"' in html


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
        }
        values.update(overrides)
        return render_template("datasets/edit.html", **values)

    def test_renders_with_append_and_table(self):
        html = self.render()
        assert 'id="append-file-input"' in html
        assert 'hx-get="/datasets/3/entries?page=1&amp;per_page=25"' in html
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

    def test_legacy_shows_column_pickers(self):
        html = self.render(is_legacy=True, dataset=make_dataset(columns=None))
        assert 'id="append-id-column"' in html

    def test_unsupported_format_hides_append(self):
        html = self.render(can_append=False, entry_type="pdf")
        assert 'id="append-file-input"' not in html
