"""Entry IDs on upload: trimmed, never dropped, and conflicts undo the upload.

"ABC " looks exactly like "ABC" but is a different ID, so IDs are trimmed on the way
in. A missing or repeated ID is an error the user has to fix in the file: rows are
never skipped silently. Files can be very large, so IDs are checked per batch while
streaming, and the first conflict undoes everything the upload wrote.
"""

from types import SimpleNamespace

import pytest

from olim import api_rest, app
from olim.entry_types import flexible_text, single_text
from olim.entry_types.base import EntryIdError
from olim.tasks import upload_data as tasks

MODULES = [single_text, flexible_text]


def write(tmp_path, text, name="data.csv"):
    path = tmp_path / name
    path.write_text(text)
    return str(path)


def all_entries(module, path, batch_size=1000):
    return [
        e
        for batch in module.generate_upload_batches(path, "id", "body", batch_size=batch_size)
        for e in batch
    ]


@pytest.mark.parametrize("module", MODULES)
class TestGenerator:
    def test_ids_are_trimmed(self, module, tmp_path):
        path = write(tmp_path, 'id,body\n"ABC ",first\n"  DEF",second\n"GHI\t",third\n')
        assert [e["id"] for e in all_entries(module, path)] == ["ABC", "DEF", "GHI"]

    def test_ids_differing_only_by_spaces_are_a_duplicate(self, module, tmp_path):
        path = write(tmp_path, 'id,body\nABC,first\n"ABC ",second\n')
        with pytest.raises(EntryIdError) as error:
            all_entries(module, path)
        assert (error.value.kind, error.value.entry_id, error.value.row) == ("duplicate", "ABC", 3)

    @pytest.mark.parametrize("blank", ['""', '"   "', ""])
    def test_row_without_id_is_an_error(self, module, tmp_path, blank):
        path = write(tmp_path, f"id,body\nA,first\n{blank},second\n")
        with pytest.raises(EntryIdError) as error:
            all_entries(module, path)
        assert (error.value.kind, error.value.row) == ("empty", 3)

    def test_zero_is_a_valid_id(self, module, tmp_path):
        path = write(tmp_path, "id,body\n0,zero\n1,one\n")
        assert [e["id"] for e in all_entries(module, path)] == ["0", "1"]

    def test_row_numbers_continue_across_batches(self, module, tmp_path):
        path = write(tmp_path, "id,body\na,1\nb,2\nc,3\nd,4\ne,5\n")
        batches = list(module.generate_upload_batches(path, "id", "body", batch_size=2))
        assert [[e["row"] for e in batch] for batch in batches] == [[2, 3], [4, 5], [6]]


@pytest.fixture
def run_upload(monkeypatch, tmp_path):
    """Run upload_dataset against in-memory storage, with batches of 2 rows."""
    stored: set[str] = set()
    calls: dict[str, list] = {"cleanup": [], "rollback": []}

    monkeypatch.setattr(tasks, "UPLOAD_BATCH_SIZE", 2)
    monkeypatch.setattr(tasks, "WORK_PATH", tmp_path)
    monkeypatch.setattr(tasks, "create_index", lambda index: None)
    monkeypatch.setattr(tasks, "get_dataset", lambda dataset_id: None)
    monkeypatch.setattr(
        tasks,
        "check_entries_exist",
        lambda ids, dataset_id: (
            [i for i in ids if i in stored],
            [i for i in ids if i not in stored],
        ),
    )

    def process(batch, *args):
        def run():
            stored.update(e["id"] for e in batch)
            return {"success": True}

        return run

    monkeypatch.setattr(tasks, "process_batch", SimpleNamespace(s=process))
    monkeypatch.setattr(
        tasks,
        "cleanup_failed_dataset",
        lambda dataset_id: calls["cleanup"].append(dataset_id) or {"success": True},
    )
    monkeypatch.setattr(tasks, "cleanup_elasticsearch_index", lambda index: True)
    monkeypatch.setattr(
        tasks,
        "rollback_append",
        lambda dataset_id, ids, index, size: calls["rollback"].append(list(ids)) or True,
    )
    monkeypatch.setattr(tasks.upload_dataset, "update_state", lambda *a, **k: None)

    def run(text, append=False, existing=()):
        stored.update(existing)
        path = write(tmp_path, text, "upload.csv")
        with app.test_request_context("/"):
            return tasks.upload_dataset(
                upload_type="single_text",
                upload_params={"filename": path, "id_column": "id", "text_column": "body"},
                dataset_id=7,
                append=append,
            )

    return run, stored, calls


class TestUploadRewind:
    def test_clean_file_uploads_everything(self, run_upload):
        run, stored, calls = run_upload
        result = run("id,body\na,1\nb,2\nc,3\n")
        assert result["total_records"] == 3
        assert stored == {"a", "b", "c"}
        assert calls == {"cleanup": [], "rollback": []}

    def test_duplicate_in_a_later_batch_undoes_the_new_dataset(self, run_upload):
        run, _stored, calls = run_upload
        with pytest.raises(Exception, match=r"'a' at row 5 appears earlier in the file") as error:
            run("id,body\na,1\nb,2\nc,3\na,4\n")
        assert "cleaned up" in str(error.value)
        assert calls["cleanup"] == [7]

    def test_append_conflict_removes_only_what_this_upload_added(self, run_upload):
        run, _stored, calls = run_upload
        with pytest.raises(Exception, match=r"'x' at row 4 already exists in the dataset") as error:
            run("id,body\ny,1\nz,2\nx,3\n", append=True, existing={"x"})
        assert "No entries were added" in str(error.value)
        # The pre-existing "x" is never part of the rollback
        assert calls["rollback"] == [["y", "z"]]
        assert calls["cleanup"] == []

    def test_empty_id_is_reported_with_its_row(self, run_upload):
        run, _stored, _calls = run_upload
        with pytest.raises(Exception, match=r"Row 3 has no ID"):
            run("id,body\na,1\n,2\n")


def test_api_ingest_trims_ids(monkeypatch):
    registered = []
    monkeypatch.setattr(api_rest, "check_entries_exist", lambda ids, dataset_id: ([], ids))
    monkeypatch.setattr(api_rest, "upload_to_elasticsearch", lambda *a, **k: None)
    monkeypatch.setattr(api_rest, "register_entries", lambda ids, *a, **k: registered.extend(ids))
    monkeypatch.setattr(api_rest, "store_texts_al", lambda *a, **k: None)

    with app.test_request_context("/"):
        _resp, status = api_rest._do_ingest(
            [{"id": " A1 ", "text": "x"}, {"id": "A1", "text": "dup"}], 1
        )
        _resp, blank_status = api_rest._do_ingest([{"id": "   ", "text": "x"}], 1)

    assert status == 201
    assert registered == ["A1"]
    assert blank_status == 400
