"""Labelling faster than training must not wedge the loop.

Reported symptom: the status bar shows "retraining…" with the counter past its
target (30/10) while no training is actually running. Cause: only one training runs
at a time, gated on `al_task_id`; Celery reports a *lost* task as PENDING —
indistinguishable from "queued" — so a worker restart, a dropped broker message or a
result aged past result_expires (1h) leaves that id set forever. The gate then never
reopens and the counter climbs without bound.
"""

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from flask import session

from olim import app
from olim.learning_tasks.states import (
    TRAINING_QUEUE_TIMEOUT,
    TRAINING_STALL_TIMEOUT,
    ActiveLearningLoop,
)


@pytest.fixture(autouse=True)
def request_context():
    with app.test_request_context("/"):
        session["language"] = "en_US"
        yield


def state(**data):
    base = {
        "al_label_id": 1,
        "al_task_id": "dead-task",
        "al_task_started_at": datetime.now().isoformat(),
        "al_cache": list(range(100)),
        "al_cache_position": 40,
        "al_labels_this_round": 30,
    }
    return ActiveLearningLoop({**base, **data}, {"_project_id": 1, "_user_id": 1})


def with_celery(monkeypatch, target, celery_state, record=None):
    """Fake both status sources: the Celery result and the tracking row."""
    monkeypatch.setattr(
        target, "_get_task_status", lambda _self, _id: dict(celery_state), raising=False
    )
    monkeypatch.setattr(
        "olim.learning_tasks.states.get_celery_task", lambda _id: record, raising=False
    )


PENDING = {"state": "pending", "progress": 0, "message": "Task pending..."}
PROCESSING = {"state": "processing", "progress": 40, "message": "working"}


class TestLostTraining:
    def test_a_task_pending_past_the_deadline_is_declared_lost(self, monkeypatch):
        target = state(
            al_task_started_at=(
                datetime.now() - timedelta(seconds=TRAINING_QUEUE_TIMEOUT + 60)
            ).isoformat()
        )
        with_celery(monkeypatch, ActiveLearningLoop, PENDING, record=None)
        assert target._training_status("dead-task")["state"] == "lost"

    def test_a_freshly_queued_task_is_left_alone(self, monkeypatch):
        target = state()
        with_celery(monkeypatch, ActiveLearningLoop, PENDING, record=None)
        assert target._training_status("dead-task")["state"] == "pending"

    def test_progress_reports_are_never_timed_out(self, monkeypatch):
        """A long training that is actively reporting must not be abandoned."""
        target = state(al_task_started_at=(datetime.now() - timedelta(hours=5)).isoformat())
        with_celery(monkeypatch, ActiveLearningLoop, PROCESSING, record=None)
        assert target._training_status("dead-task")["state"] == "processing"

    def test_a_worker_killed_mid_task_is_lost_after_the_stall_deadline(self, monkeypatch):
        """A killed worker leaves its tracking row STARTED for good."""
        record = SimpleNamespace(
            status="STARTED",
            result=None,
            error=None,
            date_started=datetime.now() - timedelta(seconds=TRAINING_STALL_TIMEOUT + 60),
        )
        with_celery(monkeypatch, ActiveLearningLoop, PENDING, record=record)
        assert state()._training_status("dead-task")["state"] == "lost"

    def test_a_started_task_within_the_deadline_is_still_running(self, monkeypatch):
        record = SimpleNamespace(
            status="STARTED", result=None, error=None, date_started=datetime.now()
        )
        with_celery(monkeypatch, ActiveLearningLoop, PENDING, record=record)
        assert state()._training_status("dead-task")["state"] == "pending"


class TestTrackingRowOutlivesTheResult:
    def test_an_expired_success_is_recovered_from_the_tracking_row(self, monkeypatch):
        """result_expires is 1h; after that Celery says PENDING for a task that
        actually succeeded, and its result is only in the database."""
        result = {"success": True, "model_id": 3, "version_id": 9, "metrics": []}
        record = SimpleNamespace(
            status="SUCCESS", result=result, error=None, date_started=datetime.now()
        )
        with_celery(monkeypatch, ActiveLearningLoop, PENDING, record=record)
        status = state()._training_status("dead-task")
        assert status["state"] == "completed"
        assert status["result"] == result

    def test_a_failure_is_recovered_from_the_tracking_row(self, monkeypatch):
        record = SimpleNamespace(
            status="FAILURE", result=None, error="boom", date_started=datetime.now()
        )
        with_celery(monkeypatch, ActiveLearningLoop, PENDING, record=record)
        status = state()._training_status("dead-task")
        assert status["state"] == "failed"
        assert status["error"] == "boom"

    def test_a_revoked_task_is_a_failure_not_a_wait(self, monkeypatch):
        record = SimpleNamespace(
            status="REVOKED", result=None, error=None, date_started=datetime.now()
        )
        with_celery(monkeypatch, ActiveLearningLoop, PENDING, record=record)
        assert state()._training_status("dead-task")["state"] == "failed"


class TestRecovery:
    def test_abandoning_reopens_the_retrain_gate(self):
        target = state()
        target._abandon_training({"age": 900})
        assert "al_task_id" not in target.data
        assert "al_task_started_at" not in target.data
        # The labels collected during the dead training still need a training.
        assert target.data["al_labels_this_round"] == 30
        assert "abandoned" in target.data["al_task_error"]

    def test_labelling_after_a_lost_training_starts_a_new_one(self, monkeypatch):
        """The whole point: one more label must break the deadlock."""
        target = state(
            al_task_started_at=(
                datetime.now() - timedelta(seconds=TRAINING_QUEUE_TIMEOUT + 60)
            ).isoformat()
        )
        with_celery(monkeypatch, ActiveLearningLoop, PENDING, record=None)
        monkeypatch.setattr("olim.learning_tasks.states.add_entry_label", lambda *a, **k: None)
        launched = []
        monkeypatch.setattr(
            ActiveLearningLoop,
            "_launch_training",
            lambda self, lid: launched.append(lid) or self.data.__setitem__("al_task_id", "new"),
            raising=False,
        )

        target.handle("label", {"entry_id": "5", "value": "yes"})

        assert launched == [1], "a fresh training should have been launched"
        assert target.data["al_labels_this_round"] == 0, "counter reset"

    def test_the_ui_stops_claiming_it_is_retraining(self, monkeypatch):
        target = state(
            al_task_started_at=(
                datetime.now() - timedelta(seconds=TRAINING_QUEUE_TIMEOUT + 60)
            ).isoformat()
        )
        with_celery(monkeypatch, ActiveLearningLoop, PENDING, record=None)
        target._abandon_training(target._training_status("dead-task"))
        assert not target.data.get("al_task_id")

    def test_a_live_training_is_not_disturbed_by_fast_labelling(self, monkeypatch):
        """The one-at-a-time gate is correct; only a *dead* task should be cleared."""
        target = state(al_labels_this_round=5)
        with_celery(monkeypatch, ActiveLearningLoop, PROCESSING, record=None)
        monkeypatch.setattr("olim.learning_tasks.states.add_entry_label", lambda *a, **k: None)
        target.handle("label", {"entry_id": "5", "value": "yes"})
        assert target.data["al_task_id"] == "dead-task", "still in flight"
        assert target.data["al_labels_this_round"] == 6
