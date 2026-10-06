"""Annotators see one task list with their tasks from every project, without the project split."""

from types import SimpleNamespace

import pytest
from flask import render_template, session

import olim.auth
from olim import app


def make_task(task_id, project_id, name, position=0, steps=3):
    return SimpleNamespace(
        id=task_id,
        project_id=project_id,
        name=name,
        position=position,
        initial_setup={"sequence": [{}] * steps},
    )


@pytest.fixture
def render_as(monkeypatch):
    def render(role, my_tasks):
        # The sidebar's permission checks read the role from the user record
        monkeypatch.setattr(olim.auth, "get_user_role", lambda user_id=None: role)
        with app.test_request_context("/1/tasks"):
            session["language"] = "en_US"
            session["role"] = role
            app.jinja_env.globals.update(
                projects=[SimpleNamespace(id=1, name="Alpha"), SimpleNamespace(id=2, name="Beta")],
                project_id=1,
                project_name="Alpha",
            )
            return render_template(
                "learning-tasks.html",
                my_tasks=my_tasks,
                all_tasks=[],
                users=[],
                configurations=[],
                available_states=[],
                is_admin=role == "admin",
            )

    return render


def test_tasks_link_to_their_own_project(render_as):
    """The list can hold tasks of other projects than the one in the URL."""
    html = render_as("annotator", [make_task(10, 1, "Review A"), make_task(20, 2, "Review B", 1)])
    assert "Review A" in html and "Review B" in html
    assert 'href="/1/task/10"' in html
    assert 'href="/2/task/20"' in html
    assert "2 / 3" in html


def test_annotator_sidebar_has_no_project_selector(render_as):
    html = render_as("annotator", [])
    assert 'id="project-dropdown-btn"' not in html
    assert "Project: Alpha" not in html
    assert 'href="/1/tasks"' in html


def test_admin_still_sees_projects(render_as):
    html = render_as("admin", [])
    assert 'id="project-dropdown-btn"' in html
    assert "Project: Alpha" in html
