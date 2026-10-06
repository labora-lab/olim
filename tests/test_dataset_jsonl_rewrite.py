"""The ML text file must follow entry edits and append rollbacks.

The JSONL file is what models train on; an edit that only reaches the search index
would leave training data silently out of date.
"""

import json

import pytest

from olim.tasks import upload_data as tasks


@pytest.fixture
def work_path(tmp_path, monkeypatch):
    monkeypatch.setattr(tasks, "WORK_PATH", tmp_path)
    (tmp_path / "datasets").mkdir()
    return tmp_path


def write_jsonl(work_path, records):
    path = work_path / "datasets" / "7.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in records))
    return path


def test_only_edited_ids_change(work_path):
    records = [{"id": "a", "text": "one"}, {"id": "b", "text": "two"}, {"id": "c", "text": "três"}]
    path = write_jsonl(work_path, records)
    before = path.read_text().splitlines()

    assert tasks.rewrite_texts_al({"b": "TWO\nlines"}, 7) == 1

    after = path.read_text().splitlines()
    assert after[0] == before[0]
    assert after[2] == before[2]
    assert json.loads(after[1]) == {"id": "b", "text": "TWO\nlines"}
    assert not (work_path / "datasets" / "7.jsonl.tmp").exists()


def test_missing_file_is_a_no_op(work_path):
    assert tasks.rewrite_texts_al({"a": "x"}, 99) == 0


def test_rollback_truncates_appended_lines(work_path):
    path = write_jsonl(work_path, [{"id": "a", "text": "one"}])
    size = path.stat().st_size
    tasks.store_texts_al({"new1": "x", "new2": "y"}, 7)
    assert path.stat().st_size > size

    assert tasks.rollback_append(7, [], "dataset-7", size)
    assert path.read_text() == json.dumps({"id": "a", "text": "one"}) + "\n"
