"""Task configurations can preset the labeling queue in a "data" block.

A task built this way starts straight at LabelEntry with a fixed list of entries and
labels, so the block is checked when the task is created rather than failing later.
"""

from types import SimpleNamespace

import pytest

from olim import app, learning_tasks as lt
from olim.learning_tasks.states import LabelEntry

LABELS = [SimpleNamespace(id=12, name="Diagnosis"), SimpleNamespace(id=15, name="Severity")]


@pytest.fixture(autouse=True)
def project(monkeypatch):
    """Project 1: labels 12 and 15; entries a and b in dataset 3."""
    stored = {"a": 3, "b": 3}

    def resolve(entry_ids, datasets):
        missing = [e for e in entry_ids if e not in stored]
        problems = [f"Entries not found: {', '.join(missing)}"] if missing else []
        return [(e, stored[e]) for e in entry_ids if e in stored], problems

    monkeypatch.setattr(lt, "get_labels", lambda project_id: LABELS)
    monkeypatch.setattr(lt, "get_datasets", lambda project_id: [SimpleNamespace(id=3)])
    monkeypatch.setattr(lt, "resolve_entry_ids", resolve)
    with app.test_request_context("/"):
        yield


def build(**data):
    return lt.build_initial_data({"data": data}, project_id=1)


class TestBuildInitialData:
    def test_no_data_block(self):
        assert lt.build_initial_data({"sequence": []}, 1) == {}

    def test_full_block(self):
        data = build(
            entries=["a", " b "],
            labels=[12, "15"],
            required_labels=[12],
            completion_mode="all",
            enforce_required=True,
        )
        assert data == {
            "queue_ids": ["a", "b"],
            "queue_dataset_ids": [3, 3],
            "queue_labels": [{"id": 12, "name": "Diagnosis"}, {"id": 15, "name": "Severity"}],
            "queue_required_labels": [{"id": 12, "name": "Diagnosis"}],
            "queue_completion_mode": "all",
            "queue_enforce_required": True,
            "queue_position": 0,
        }

    def test_labels_default_to_all_project_labels(self):
        data = build(entries=["a"])
        assert [lbl["id"] for lbl in data["queue_labels"]] == [12, 15]
        assert data["queue_required_labels"] == []
        assert data["queue_completion_mode"] == "any"
        assert data["queue_enforce_required"] is False

    @pytest.mark.parametrize(
        ("data", "message"),
        [
            ({"entries": []}, "non-empty list"),
            ({"entries": ["a", "a"]}, "repeats these IDs: a"),
            ({"entries": ["a", "zz"]}, "Entries not found: zz"),
            ({"entries": ["a"], "labels": [99]}, "don't exist in this project: 99"),
            ({"entries": ["a"], "labels": ["x"]}, "list of label IDs"),
            ({"entries": ["a"], "labels": [12], "required_labels": [15]}, "also be in 'labels'"),
            ({"entries": ["a"], "completion_mode": "most"}, "completion_mode"),
            ({"entries": ["a"], "queue_ids": ["a"]}, "Unknown fields in 'data': queue_ids"),
        ],
    )
    def test_invalid_blocks_are_rejected(self, data, message):
        with pytest.raises(ValueError, match=message):
            build(**data)


class TestEnforceRequired:
    def state(self, enforce, complete_positions):
        data = {
            "queue_ids": ["a", "b"],
            "queue_dataset_ids": [3, 3],
            "queue_position": 0,
            "queue_enforce_required": enforce,
        }
        state = LabelEntry(data, {"_datasets": []})
        state._get_labels_context = lambda: ([], [12], [12], "any")
        state._compute_completed_positions = lambda items, *a: {
            i for i, item in enumerate(items) if item[0] in complete_positions
        }
        return state

    def test_next_is_blocked_on_an_incomplete_entry(self):
        state = self.state(True, set())
        assert state.handle("skip", {}) == 0
        assert state.data["queue_position"] == 0

    def test_next_moves_on_once_complete(self):
        state = self.state(True, {"a"})
        state.handle("skip", {})
        assert state.data["queue_position"] == 1

    def test_without_enforcement_next_always_moves_on(self):
        state = self.state(False, set())
        state.handle("skip", {})
        assert state.data["queue_position"] == 1

    def test_finish_jumps_to_the_first_incomplete_entry(self):
        state = self.state(True, {"a"})
        state.data["queue_position"] = 2
        assert state.handle("finish_queue", {}) == 0
        assert state.data["queue_position"] == 1

    def test_finish_when_all_complete(self):
        assert self.state(True, {"a", "b"}).handle("finish_queue", {}) == 1
