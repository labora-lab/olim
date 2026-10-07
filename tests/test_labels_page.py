"""The labels page counts each option of a choice label and only a total for text labels."""

import json
import re
from types import SimpleNamespace

import pytest
from flask import render_template, session

import olim.auth
from olim import app
from olim.labels import _value_counts


def entry(value, deleted=False):
    return SimpleNamespace(value=value, is_deleted=deleted)


def make_label(label_id, label_type, values, options=None):
    settings = {"options": [{"value": o} for o in options]} if options else None
    return SimpleNamespace(
        id=label_id,
        name=f"Label {label_id}",
        label_type=label_type,
        label_settings=settings,
        entries=[entry(v) for v in values],
        creator=SimpleNamespace(name="Admin"),
    )


def test_multi_select_counts_each_selected_option():
    label = make_label(
        1,
        "multiple_choice",
        [json.dumps(["a", "b"]), json.dumps(["a"]), json.dumps([])],
        options=["a", "b", "c"],
    )
    counts = _value_counts(label)
    # Declared order, with a zero for the option nobody picked
    assert list(counts["options"].items()) == [("a", 2), ("b", 1), ("c", 0)]
    # The cleared entry is not an annotation
    assert counts["total"] == 2


def test_scalar_and_json_values_count_as_the_same_option():
    label = make_label(2, "yes_no", ["yes", json.dumps(["yes"]), json.dumps(["no"])])
    assert _value_counts(label) == {"total": 3, "options": {"yes": 2, "no": 1}}


def test_unconfigured_multiple_choice_hides_placeholder_options():
    label = make_label(3, "multiple_choice", [json.dumps(["x"])])
    assert _value_counts(label)["options"] == {"x": 1}


def test_text_label_only_has_a_total():
    label = make_label(4, "free_text", ["some note", "", "other"])
    label.entries.append(entry("deleted note", deleted=True))
    assert _value_counts(label) == {"total": 2, "options": None}


@pytest.fixture
def render_labels(monkeypatch):
    monkeypatch.setattr(olim.auth, "get_user_role", lambda user_id=None: "admin")

    def render(labels):
        with app.test_request_context("/1/labels"):
            session["language"] = "en_US"
            session["role"] = "admin"
            app.jinja_env.globals.update(project_id=1, project_name="Alpha", projects=[])
            return render_template(
                "labels.html",
                labels=labels,
                values={label.id: _value_counts(label) for label in labels},
                datasets=[SimpleNamespace(id=1, name="Notes")],
            )

    return render


def test_page_shows_option_counts_per_label(render_labels):
    choice = make_label(1, "multiple_choice", [json.dumps(["a", "b"])], options=["a", "b"])
    text = make_label(2, "free_text", ["note"])
    html = re.sub(r"\s+", " ", render_labels([choice, text]))
    assert re.search(r'a<span class="ml-1.5 font-semibold">1</span>', html)
    assert re.search(r'b<span class="ml-1.5 font-semibold">1</span>', html)
    assert "Free text" in html
    # Options of one label do not become columns of every other label
    assert '["a", "b"]' not in html
