"""Hiding labels: the choice is saved, and hidden labels can always be shown again.

Hidden labels used to vanish from the task labeling screen with no way back, and
unhiding edited the session list in place, which Flask doesn't see as a change.
"""

from types import SimpleNamespace

import pytest
from flask import render_template_string, session

from olim import app
from olim.commands import manage_label
from olim.functions import manage_label_in_session

LABELS = [SimpleNamespace(id=12, name="Diagnosis"), SimpleNamespace(id=15, name='Size "cm"')]
NOTICE = (
    '{% import "macros/labels-menu.html" as m %}{{ m.hidden_labels_notice(labels, hidden_labels) }}'
)


@pytest.fixture(autouse=True)
def request_context():
    with app.test_request_context("/"):
        session["language"] = "en_US"
        yield


class TestSession:
    def test_hiding_marks_the_session_modified(self):
        session["hidden_labels"] = [12]
        session.modified = False
        manage_label_in_session([15], "add")
        assert session["hidden_labels"] == [12, 15]
        assert session.modified

    def test_hiding_twice_keeps_one_entry(self):
        manage_label_in_session([12], "add")
        manage_label_in_session([12], "add")
        assert session["hidden_labels"] == [12]

    def test_showing_removes_every_copy(self):
        session["hidden_labels"] = [12, 15, 12]
        session.modified = False
        manage_label_in_session([12], "remove")
        assert session["hidden_labels"] == [15]
        assert session.modified

    def test_command_shows_several_labels_at_once(self):
        session["hidden_labels"] = [12, 15, 20]
        result = manage_label(label="all", label_id="12,15", mode="remove")
        assert session["hidden_labels"] == [20]
        assert result["text"] == "2 labels shown"


class TestNotice:
    def test_lists_only_hidden_labels_of_the_page(self):
        html = render_template_string(NOTICE, labels=LABELS, hidden_labels=[15, 99])
        assert "Hidden labels (1)" in html
        assert 'data-title="Hidden labels ({count})"' in html
        # Every label gets a button so hiding one later can reveal it; only 15 is shown
        button_12 = html.split('data-hidden-label="12"')[1].split(">")[0]
        assert 'class="hidden inline-flex' in button_12
        button_15 = html.split('data-hidden-label="15"')[1].split(">")[0]
        assert 'data-name="Size &#34;cm&#34;"' in button_15
        assert 'class="hidden ' not in button_15

    def test_hidden_when_nothing_on_the_page_is_hidden(self):
        html = render_template_string(NOTICE, labels=LABELS, hidden_labels=[99])
        assert 'id="hidden-labels-notice"' in html
        assert 'class="hidden p-3' in html
