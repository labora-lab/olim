"""Uploading label values from a file must respect each label's configured options.

A value outside a label's options would be stored as-is and later show up as an
unknown class; for multi-select labels, rows of the same entry have to combine
into the list the labelling screen writes instead of overwriting each other.
"""

import json
from datetime import datetime
from types import SimpleNamespace

import pandas as pd
import pytest

from olim import app
from olim.utils import label as label_utils
from olim.utils.label import label_upload, label_value_policy


def make_label(name, label_type, settings=None, label_id=1):
    return SimpleNamespace(id=label_id, name=name, label_type=label_type, label_settings=settings)


COLOR = make_label(
    "Color", "multiple_choice", {"options": [{"value": "Red"}, {"value": "Blue"}]}, 1
)
SINGLE = make_label(
    "Size",
    "multiple_choice",
    {"options": [{"value": "S"}, {"value": "L"}], "single_select": True},
    2,
)
YES_NO = make_label("Ok", "yes_no", None, 3)
NOTE = make_label("Note", "free_text", None, 4)


class TestPolicy:
    def test_configured_multiple_choice(self):
        allowed, multi = label_value_policy(COLOR)
        assert allowed == {"red": "Red", "blue": "Blue"}
        assert multi

    def test_single_select_multiple_choice(self):
        assert label_value_policy(SINGLE)[1] is False

    def test_preset_type_uses_its_options(self):
        allowed, multi = label_value_policy(YES_NO)
        assert set(allowed) == {"yes", "no"}
        assert not multi

    @pytest.mark.parametrize("label", [NOTE, make_label("X", None), None])
    def test_open_labels_accept_anything(self, label):
        assert label_value_policy(label) == (None, False)

    def test_unconfigured_multiple_choice_accepts_anything_but_stays_multi_select(self):
        assert label_value_policy(make_label("Y", "multiple_choice", {})) == (None, True)


@pytest.fixture
def upload(monkeypatch):
    """Run label_upload against fake storage and return what got stored."""
    stored = []
    flashes = []
    labels = {1: COLOR, 2: SINGLE, 3: YES_NO, 4: NOTE}
    entries = {"e1": 11, "e2": 12, "007": 13}

    monkeypatch.setattr(label_utils, "get_labels", lambda project_id: list(labels.values()))
    monkeypatch.setattr(
        label_utils,
        "check_entries_exist",
        lambda ids, dataset_id: (
            [i for i in ids if i in entries],
            [i for i in ids if i not in entries],
        ),
    )
    monkeypatch.setattr(
        label_utils,
        "get_entry",
        lambda idt: SimpleNamespace(id=entries[idt[1]]) if idt[1] in entries else None,
    )
    monkeypatch.setattr(
        label_utils,
        "new_label",
        lambda name, user_id, project_id: make_label(name, None, None, 99),
    )
    monkeypatch.setattr(
        label_utils,
        "add_entry_label",
        lambda label_id, entry_id, user_id, value, created=None: stored.append(
            (label_id, entry_id, value)
        ),
    )
    monkeypatch.setattr(
        label_utils, "flash", lambda msg, category=None: flashes.append((category, msg))
    )

    def run(rows, **columns):
        df = pd.DataFrame(rows, columns=["entry_id", "label", "value", *columns])
        with app.test_request_context("/"):
            count = label_upload(df, user_id=1, project_id=1, dataset_id=1)
        return count, stored, flashes

    return run


class TestUpload:
    def test_values_are_stored_as_the_declared_option(self, upload):
        _count, stored, _flashes = upload([("e1", "Ok", "YES"), ("e2", "Size", "l")])
        assert (3, 11, "yes") in stored
        assert (2, 12, "L") in stored

    def test_values_outside_the_options_are_skipped_and_reported(self, upload):
        count, stored, flashes = upload([("e1", "Color", "Green"), ("e2", "Ok", "yes")])
        assert count == 1
        assert stored == [(3, 12, "yes")]
        warning = next(m for c, m in flashes if c == "warning")
        assert "Color: Green" in warning

    def test_multi_select_rows_combine_into_a_list(self, upload):
        _count, stored, _flashes = upload(
            [("e1", "Color", "Red"), ("e1", "Color", "blue"), ("e1", "Color", "red")]
        )
        assert stored == [(1, 11, json.dumps(["Red", "Blue"]))]

    def test_single_select_keeps_the_latest_row(self, upload):
        rows = [
            ("e1", "Size", "L", datetime(2026, 1, 2)),
            ("e1", "Size", "S", datetime(2026, 1, 1)),
        ]
        _count, stored, _flashes = upload(rows, created=None)
        assert stored == [(2, 11, "L")]

    def test_free_text_and_new_labels_accept_anything(self, upload):
        _count, stored, _flashes = upload([("e1", "Note", "whatever"), ("e2", "Brand new", "x")])
        assert (4, 11, "whatever") in stored
        assert (99, 12, "x") in stored

    def test_ids_are_matched_as_text(self, upload):
        _count, stored, _flashes = upload([("007", "Ok", "no")])
        assert stored == [(3, 13, "no")]

    def test_missing_columns_are_reported(self, monkeypatch):
        df = pd.DataFrame([("e1", "x")], columns=["id", "lbl"])
        flashes = []
        monkeypatch.setattr(
            label_utils, "flash", lambda msg, category=None: flashes.append((category, msg))
        )
        with app.test_request_context("/"):
            assert label_upload(df, user_id=1, project_id=1, dataset_id=1) == 0
        assert flashes[0][0] == "error"
        assert "entry_id, label, value" in flashes[0][1]
