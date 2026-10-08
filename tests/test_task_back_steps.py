"""Annotators can't move a task back to an earlier step (e.g. a queue's setup)."""

from types import SimpleNamespace

import pytest
from flask import get_flashed_messages, render_template_string, session

import olim.auth
from olim import app, learning_tasks as lt
from olim.learning_tasks.base import BaseState


class Step(BaseState):
    def render(self) -> str:
        return "step"

    def handle(self, action, payload) -> int:
        if action == "back":
            self.data.pop("queue_ids")  # what going back to setup does to a queue
            return -1
        return 1 if action == "next" else 0


@pytest.fixture
def post(monkeypatch):
    saved = []
    task = SimpleNamespace(
        id=7,
        project_id=1,
        assigned_to=5,
        position=1,
        data={"queue_ids": ["a"]},
        initial_setup={"sequence": [{"state": "Step"}, {"state": "Step"}, {"state": "Step"}]},
    )
    monkeypatch.setitem(lt.STATE_REGISTRY, "Step", Step)
    monkeypatch.setattr(lt, "update_session_project", lambda project_id: None)
    monkeypatch.setattr(lt, "get_learning_task", lambda task_id: task)
    monkeypatch.setattr(lt, "get_datasets", lambda project_id: [])
    monkeypatch.setattr(lt, "update_learning_task", lambda task_id, **f: saved.append(f))
    monkeypatch.setattr(olim.auth, "save_session", lambda user_id, data: None)

    def run(role, action):
        with app.test_request_context(
            "/1/task/7", method="POST", data={"action": action}, headers={"HX-Request": "true"}
        ):
            session.update(role=role, user_id=5, language="en_US")
            lt.learning_task_view(1, 7)
            return saved[-1], get_flashed_messages()

    return run


def test_annotator_stays_on_the_step_and_keeps_its_data(post):
    saved, messages = post("annotator", "back")
    assert saved["position"] == 1
    assert saved["data"] == {"queue_ids": ["a"]}
    assert messages == ["You can't go back to a previous step of this task."]


def test_annotator_still_moves_forward(post):
    saved, _messages = post("annotator", "next")
    assert saved["position"] == 2


def test_other_roles_go_back(post):
    saved, messages = post("user", "back")
    assert saved["position"] == 0
    assert saved["data"] == {}
    assert messages == []


@pytest.mark.parametrize(("role", "shown"), [("annotator", False), ("admin", True)])
def test_back_buttons_follow_the_role(role, shown):
    with app.test_request_context("/"):
        session["role"] = role
        html = render_template_string(
            "{% if show_prev and can_go_back_steps() %}prev{% endif %}", show_prev=True
        )
    assert (html == "prev") is shown
