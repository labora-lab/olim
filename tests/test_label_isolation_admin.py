"""Admins see and edit every user's label values when values are isolated per user."""

import json
import re
from datetime import datetime
from types import SimpleNamespace

import pytest
from flask import render_template_string, session

from olim import app, commands, functions
from olim.utils import export

ADMIN, ANA, BRUNO = 1, 5, 7


def user(user_id, name):
    return SimpleNamespace(id=user_id, name=name, username=name.lower())


USERS = {ADMIN: user(ADMIN, "Admin"), ANA: user(ANA, "Ana"), BRUNO: user(BRUNO, "Bruno")}


def label_entry(label_id, user_id, value, minute, deleted=False):
    return SimpleNamespace(
        label_id=label_id,
        created_by=user_id,
        creator=USERS[user_id],
        value=value,
        created=datetime(2026, 1, 1, 0, minute),
        is_deleted=deleted,
    )


@pytest.fixture
def as_role(monkeypatch):
    def setup(role, isolation=True):
        monkeypatch.setattr(functions, "is_label_isolation_enabled", lambda: isolation)
        monkeypatch.setattr(commands, "is_label_isolation_enabled", lambda: isolation)
        session["user_id"] = ADMIN
        session["role"] = role
        session["language"] = "en_US"

    with app.test_request_context("/"):
        yield setup
        # Teardown persists the session to the user's record; there is no DB here
        session.pop("user_id", None)


class TestSavingForAnotherUser:
    @pytest.fixture
    def saved(self, monkeypatch):
        calls = []
        monkeypatch.setattr(commands, "get_label", lambda label_id: SimpleNamespace(name="Topic"))
        monkeypatch.setattr(commands, "add_entry_label", lambda *a, **k: calls.append((a, k)))
        return calls

    def test_admin_edits_the_users_value(self, as_role, saved):
        as_role("admin")
        result = commands.add_label(entry_id="3", label_id="12", value="yes", for_user=str(ANA))
        assert result["type"] == "OK"
        args, kwargs = saved[0]
        assert args == ("12", "3", ANA, "yes")
        assert kwargs == {"metadata": {"edited_by": ADMIN}, "acting_user_id": ADMIN}

    def test_own_value_is_unchanged_behaviour(self, as_role, saved):
        as_role("admin")
        commands.add_label(entry_id="3", label_id="12", value="yes")
        args, kwargs = saved[0]
        assert args[2] == ADMIN
        assert kwargs["metadata"] is None

    @pytest.mark.parametrize(
        "role,isolation", [("user", True), ("annotator", True), ("admin", False)]
    )
    def test_refused_unless_admin_with_isolation(self, as_role, saved, role, isolation):
        as_role(role, isolation)
        result = commands.add_label(entry_id="3", label_id="12", value="yes", for_user=str(ANA))
        assert result["type"] == "error"
        assert saved == []


class TestOtherUsersValues:
    ENTRY = SimpleNamespace(
        labels=[
            label_entry(12, ANA, "no", 1),
            label_entry(12, ANA, "yes", 2),  # latest wins
            label_entry(12, BRUNO, "no", 3, deleted=True),
            label_entry(12, ADMIN, "yes", 4),  # the admin's own value is shown above
            label_entry(13, BRUNO, "x", 5),  # another label
        ]
    )

    def test_admin_sees_each_other_users_current_value(self, as_role):
        as_role("admin")
        values = functions.other_users_label_values(self.ENTRY, 12)
        assert [(v["user"].id, v["value"]) for v in values] == [(ANA, "yes")]

    @pytest.mark.parametrize("role,isolation", [("user", True), ("admin", False)])
    def test_nobody_else_sees_them(self, as_role, role, isolation):
        as_role(role, isolation)
        assert functions.other_users_label_values(self.ENTRY, 12) == []


class TestLabelsMenu:
    def render(self, label, entry, own_value=None):
        return render_template_string(
            '{% import "macros/labels-menu.html" as m %}'
            "{{ m.labels_menu(label, entry, [], values, [], False, True) }}",
            label=label,
            entry=entry,
            values={label.id: own_value} if own_value else {},
        )

    def test_one_block_per_other_user_with_scoped_controls(self, as_role):
        as_role("admin")
        label = SimpleNamespace(
            id=12,
            name="Topic",
            label_type="multiple_choice",
            label_settings={"options": [{"value": "A"}, {"value": "B"}], "single_select": False},
        )
        entry = SimpleNamespace(
            id=3,
            labels=[label_entry(12, ANA, json.dumps(["B"]), 1), label_entry(12, BRUNO, "A", 2)],
        )
        html = self.render(label, entry, own_value=json.dumps(["A"]))

        # The admin's own buttons keep the plain label scope
        assert "toggleMultipleChoice(3, '12', 'A'" in html
        # Each other user gets their own block, buttons and clear option
        for uid in (ANA, BRUNO):
            assert f'id="label_12-u{uid}"' in html
            assert f"toggleMultipleChoice(3, '12-u{uid}', 'A'" in html
            assert f"clearUserLabel(3, '12-u{uid}')" in html
        assert html.count("Clear this user") == 2
        # Buttons are tied to their scope so one user's clicks don't touch another's
        flat = " ".join(html.split())
        ana_b = re.search(r'data-scope="12-u5" data-option-value="B"[^>]*', flat).group(0)
        ana_a = re.search(r'data-scope="12-u5" data-option-value="A"[^>]*', flat).group(0)
        assert 'data-selected="true"' in ana_b and 'data-selected="false"' in ana_a

    def test_text_labels_get_unique_element_ids(self, as_role):
        as_role("admin")
        label = SimpleNamespace(id=12, name="Note", label_type="short_text", label_settings={})
        entry = SimpleNamespace(id=3, labels=[label_entry(12, ANA, "hello", 1)])
        html = self.render(label, entry, own_value="mine")
        assert 'id="text_input_12"' in html and 'id="text_input_12-u5"' in html
        assert "_submitShortText_12_u5" in html  # valid JS identifier for the user's copy

    def test_non_admin_sees_only_their_own_value(self, as_role):
        as_role("user")
        label = SimpleNamespace(id=12, name="Ok", label_type="yes_no", label_settings=None)
        entry = SimpleNamespace(id=3, labels=[label_entry(12, ANA, "yes", 1)])
        html = self.render(label, entry)
        assert "label_12-u" not in html
        assert "Clear this user" not in html


def test_export_all_has_a_column_per_user(monkeypatch):
    monkeypatch.setattr(
        export,
        "iter_dataset_entries",
        lambda dataset_id, size: iter([[SimpleNamespace(id=1, entry_id="a")]]),
    )
    monkeypatch.setattr(
        export,
        "es_search",
        lambda **k: {"hits": {"hits": [{"_id": "a", "_source": {"text": "t"}}]}},
    )
    monkeypatch.setattr(
        export,
        "get_label_users",
        lambda dataset_ids, label_ids: {1: [USERS[ANA], USERS[BRUNO]]},
    )
    monkeypatch.setattr(
        export,
        "get_label_values_by_user",
        lambda pks, label_ids: {(1, 1, ANA): "yes", (1, 1, BRUNO): "no"},
    )
    labels = [SimpleNamespace(id=1, name="Ok"), SimpleNamespace(id=2, name="Unanswered")]
    ds = SimpleNamespace(id=3, name="D", columns=["id", "body"], id_column="id", text_column="body")

    text = "".join(export.export_csv([ds], labels, per_user=True)).lstrip("﻿")
    lines = text.strip().splitlines()
    assert lines[0] == "id,body,Ok (ana),Ok (bruno),Unanswered"
    assert lines[1] == "a,t,yes,no,"
