"""Dataset columns: display settings and adding columns to existing entries.

The column configuration editor is shared by the upload form and the edit page, so
both go through normalize_column_config. Adding columns matches rows by ID: every ID
is checked before anything is written, and a failed write removes the new fields.
"""

from types import SimpleNamespace

import pytest

from olim import app
from olim.datasets import config_fields, existing_columns
from olim.entry_types.flexible_text import (
    _LEGACY_PDF_CONFIG,
    DEFAULT_COLUMN_CONFIG,
    current_column_config,
    normalize_column_config,
)
from olim.tasks import upload_data as tasks


@pytest.fixture(autouse=True)
def request_context():
    with app.test_request_context("/"):
        yield


def make_dataset(**overrides):
    values = {"id": 1, "id_column": "id", "text_column": "body", "columns": ["id", "body", "src"]}
    values.update(overrides)
    return SimpleNamespace(**values)


class TestNormalizeConfig:
    def test_keeps_valid_settings(self):
        raw = {
            "text_is_html": True,
            "text_hidden": False,
            "show_remaining_as_metadata": False,
            "extra_columns": [
                {"column": "src", "render_as": "image", "show_title": True, "as_tab": True}
            ],
        }
        assert normalize_column_config(raw, ["src"]) == raw

    def test_empty_config_gets_defaults(self):
        assert normalize_column_config({}, []) == DEFAULT_COLUMN_CONFIG

    def test_unknown_column_is_rejected(self):
        with pytest.raises(ValueError, match="Unknown column: other"):
            normalize_column_config({"extra_columns": [{"column": "other"}]}, ["src"])

    def test_unknown_render_mode_is_rejected(self):
        with pytest.raises(ValueError, match="Unknown display mode"):
            normalize_column_config(
                {"extra_columns": [{"column": "src", "render_as": "video"}]}, ["src"]
            )

    def test_legacy_pdf_mode_and_repeats(self):
        config = normalize_column_config(
            {"extra_columns": [{"column": "src", "render_as": "pdf_url"}, {"column": "src"}]},
            ["src"],
        )
        assert config["extra_columns"] == [
            {"column": "src", "render_as": "pdf", "show_title": False, "as_tab": False}
        ]

    def test_not_a_dict(self):
        with pytest.raises(ValueError):
            normalize_column_config([], [])


class TestCurrentConfig:
    def test_stored_config_wins(self):
        stored = {"text_is_html": True}
        assert current_column_config(stored, ["pdf_url"]) is stored

    def test_legacy_pdf_dataset(self):
        assert current_column_config(None, ["text", "pdf_url"]) == _LEGACY_PDF_CONFIG

    def test_default(self):
        assert current_column_config(None, ["text"]) == DEFAULT_COLUMN_CONFIG


class TestDatasetColumns:
    def test_existing_columns_include_id_and_text(self):
        assert existing_columns(make_dataset()) == ["id", "body", "src"]

    def test_legacy_existing_columns_come_from_the_index(self):
        dataset = make_dataset(id_column=None, text_column=None, columns=None)
        assert existing_columns(dataset, ["text", "metadata_text", "src"]) == [
            "text",
            "text",
            "src",
        ]

    def test_config_fields_keep_configured_columns_the_dataset_lacks(self):
        config = {"extra_columns": [{"column": "pdf_url"}, {"column": "src"}]}
        assert config_fields(make_dataset(), config) == [
            {"field": "src", "label": "src"},
            {"field": "pdf_url", "label": "pdf_url"},
        ]

    def test_text_metadata_column_uses_its_field(self):
        dataset = make_dataset(columns=["id", "body", "text"])
        assert config_fields(dataset, DEFAULT_COLUMN_CONFIG) == [
            {"field": "metadata_text", "label": "text"}
        ]


class TestCheckNewColumns:
    def test_new_columns(self):
        report = tasks.check_new_columns(["key", "a", "b"], "key", ["id", "body"])
        assert report == {
            "ok": True,
            "id_column": "key",
            "new_columns": ["a", "b"],
            "existing_columns": [],
        }

    def test_existing_column_blocks(self):
        report = tasks.check_new_columns(["id", "body", "a"], "id", ["id", "body"])
        assert not report["ok"]
        assert report["existing_columns"] == ["body"]

    def test_only_the_id_column(self):
        report = tasks.check_new_columns(["id"], "id", ["id", "body"])
        assert not report["ok"]
        assert report["new_columns"] == []


@pytest.fixture
def run_add(monkeypatch, tmp_path):
    """Run add_dataset_columns against fake storage, with batches of 2 rows."""
    stored = {"a", "b", "c"}
    calls: dict[str, list] = {"bulk": [], "removed": [], "updated": []}
    fail_batches: set[int] = set()

    def bulk(es, actions, raise_on_error):
        calls["bulk"].append(actions)
        if len(calls["bulk"]) in fail_batches:
            return 0, [{"update": {"_id": "x", "error": {"reason": "mapper_parsing_exception"}}}]
        return len(actions), []

    monkeypatch.setattr(tasks, "UPLOAD_BATCH_SIZE", 2)
    monkeypatch.setattr(
        tasks,
        "check_entries_exist",
        lambda ids, dataset_id: (
            [i for i in ids if i in stored],
            [i for i in ids if i not in stored],
        ),
    )
    monkeypatch.setattr(
        tasks, "get_es_conn", lambda **k: SimpleNamespace(indices=SimpleNamespace(refresh=dict))
    )
    monkeypatch.setattr(tasks, "helpers", SimpleNamespace(bulk=bulk))
    monkeypatch.setattr(tasks, "get_dataset", lambda dataset_id: make_dataset())
    monkeypatch.setattr(tasks, "update_dataset", lambda dataset_id, **f: calls["updated"].append(f))
    monkeypatch.setattr(
        tasks, "remove_fields", lambda index, fields: calls["removed"].append(fields)
    )
    monkeypatch.setattr(tasks.add_dataset_columns, "update_state", lambda *a, **k: None)

    def run(text, new_columns, fail=()):
        fail_batches.update(fail)
        path = tmp_path / "columns.csv"
        path.write_text(text)
        return tasks.add_dataset_columns(
            dataset_id=1,
            filename=str(path),
            id_column="key",
            new_columns=new_columns,
            sep=",",
            encoding="utf-8",
        )

    return run, calls


class TestAddColumns:
    def test_values_are_set_by_id(self, run_add):
        run, calls = run_add
        result = run('key,score,text\n"a ",1,x\nb,,\nc,3,z\n', ["score", "text"])
        docs = [(a["_id"], a["doc"]) for batch in calls["bulk"] for a in batch]
        # IDs trimmed, empty cells skipped, a "text" column kept apart from the main text
        assert docs == [
            ("a", {"score": 1.0, "metadata_text": "x"}),
            ("c", {"score": 3.0, "metadata_text": "z"}),
        ]
        assert result["updated"] == 2
        assert calls["updated"] == [{"columns": ["id", "body", "src", "score", "text"]}]
        assert calls["removed"] == []

    def test_unknown_id_writes_nothing(self, run_add):
        run, calls = run_add
        with pytest.raises(Exception, match=r"'zz' at row 4 is not in the dataset") as error:
            run("key,score\na,1\nb,2\nzz,3\n", ["score"])
        assert "No columns were added" in str(error.value)
        assert calls["bulk"] == []

    def test_repeated_id_across_batches_writes_nothing(self, run_add):
        run, calls = run_add
        with pytest.raises(Exception, match=r"'a' at row 4 appears earlier in the file"):
            run("key,score\na,1\nb,2\na,3\n", ["score"])
        assert calls["bulk"] == []

    def test_failed_write_removes_the_new_fields(self, run_add):
        run, calls = run_add
        with pytest.raises(Exception, match="mapper_parsing_exception") as error:
            run("key,score,text\na,1,x\nb,2,y\nc,3,z\n", ["score", "text"], fail={2})
        assert "the existing data was kept" in str(error.value)
        assert calls["removed"] == [["score", "metadata_text"]]
        assert calls["updated"] == []


def test_fields_without_values_are_ignored(monkeypatch):
    """Undoing a failed column upload leaves the field mapped but empty."""
    from olim.utils import es

    queries = []

    def search(index, size, aggs):
        queries.append(aggs)
        counts = {"text": 5, "src": 2, "score": 0}
        return {
            "aggregations": {
                "fields": {"buckets": {f: {"doc_count": n} for f, n in counts.items()}}
            }
        }

    monkeypatch.setattr(es, "es_list_fields", lambda index: ["text", "src", "score"])
    monkeypatch.setattr(es, "get_es_conn", lambda: SimpleNamespace(search=search))
    assert es.es_fields_with_values("dataset-1") == ["text", "src"]
    assert queries[0]["fields"]["filters"]["filters"]["score"] == {"exists": {"field": "score"}}
