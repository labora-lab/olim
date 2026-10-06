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


class TestListValues:
    """The export writes the stored value, a JSON list; uploading it must round-trip."""

    def test_multi_select_list_in_one_cell(self, upload):
        _count, stored, _flashes = upload([("e1", "Color", '["Red", "blue"]')])
        assert stored == [(1, 11, json.dumps(["Red", "Blue"]))]

    def test_list_and_single_rows_combine(self, upload):
        _count, stored, _flashes = upload(
            [("e1", "Color", '["Red"]'), ("e1", "Color", "Blue"), ("e1", "Color", '["Red"]')]
        )
        assert stored == [(1, 11, json.dumps(["Red", "Blue"]))]

    def test_single_choice_accepts_a_one_item_list(self, upload):
        """The labelling screen stores ["yes"] even for yes/no labels."""
        _count, stored, _flashes = upload([("e1", "Ok", '["yes"]'), ("e2", "Size", '["S"]')])
        assert (3, 11, "yes") in stored
        assert (2, 12, "S") in stored

    def test_single_choice_rejects_several_options(self, upload):
        count, stored, flashes = upload([("e1", "Size", '["S", "L"]')])
        assert count == 0
        assert stored == []
        assert any(c == "warning" and "Size" in m for c, m in flashes)

    def test_one_bad_option_skips_the_row(self, upload):
        count, stored, _flashes = upload([("e1", "Color", '["Red", "Green"]')])
        assert count == 0
        assert stored == []

    def test_empty_list_is_skipped(self, upload):
        assert upload([("e1", "Color", "[]")])[0] == 0

    def test_free_text_keeps_the_value_as_written(self, upload):
        _count, stored, _flashes = upload([("e1", "Note", '["not", "a list"]')])
        assert stored == [(4, 11, '["not", "a list"]')]

    def test_exported_csv_uploads_unchanged(self, upload, tmp_path, monkeypatch):
        exported = pd.DataFrame(
            [("2026-10-01 09:00", "e1", "Color", json.dumps(["Red", "Blue"]), "ana")],
            columns=["created", "entry_id", "label", "value", "created_by"],
        )
        path = tmp_path / "Color.csv"
        exported.to_csv(path, index=False)
        assert '"[""Red"", ""Blue""]"' in path.read_text()

        df = pd.read_csv(path, dtype=str)
        stored = []
        monkeypatch.setattr(label_utils, "add_entry_label", lambda *a, **k: stored.append(a[3]))
        with app.test_request_context("/"):
            label_upload(df, user_id=1, project_id=1, dataset_id=1)
        assert stored == [json.dumps(["Red", "Blue"])]


class TestMatching:
    """Options typed on another system must still match the file's values."""

    def test_option_key_ignores_spacing_case_and_accent_encoding(self):
        import unicodedata

        from olim.utils.label import option_key

        typed = unicodedata.normalize("NFD", "Paulo       Verdasca  Codeço")
        assert option_key(typed) == option_key(" paulo verdasca CODEÇO ")

    def test_upload_stores_the_option_as_configured(self, monkeypatch, upload):
        odd = make_label(
            "People",
            "multiple_choice",
            {"options": [{"value": "Paulo       Verdasca Amorim"}, {"value": "Flávio"}]},
            5,
        )
        monkeypatch.setattr(label_utils, "get_labels", lambda project_id: [odd])
        _count, stored, _flashes = upload([("e1", "People", '["Paulo Verdasca Amorim", "flávio"]')])
        assert stored == [(5, 11, json.dumps(["Paulo       Verdasca Amorim", "Flávio"]))]

    def test_entry_id_with_trailing_space_matches_as_written(self, upload):
        """Dataset IDs are stored verbatim, so "007 " must not be trimmed away."""
        _count, stored, _flashes = upload([("007 ", "Ok", "no")])
        assert stored == [(3, 13, "no")]

    def test_reasons_are_reported_separately(self, upload):
        _count, _stored, flashes = upload([("e1", "Size", '["S", "L"]'), ("e2", "Color", "Green")])
        warnings = [m for c, m in flashes if c == "warning"]
        assert any("single-select" in m and "Size" in m for m in warnings)
        assert any("not options" in m and "Color: Green" in m for m in warnings)


class TestNewLabels:
    def test_new_label_names(self, monkeypatch):
        monkeypatch.setattr(label_utils, "get_labels", lambda project_id: [COLOR])
        df = pd.DataFrame(
            [("e1", "Color", "Red"), ("e1", " Reviewers ", "A"), ("e2", "Reviewers", "B")],
            columns=["entry_id", "label", "value"],
        )
        assert label_utils.new_label_names(df, 1) == ["Reviewers"]

    def test_suggestion_collects_options_and_detects_multi_select(self):
        df = pd.DataFrame(
            [
                ("e1", "Reviewers", '["Ana", "Bruno"]'),
                ("e2", "Reviewers", "ana"),
                ("e3", "Reviewers", "Carla  Dias"),
                ("e1", "Other", "x"),
            ],
            columns=["entry_id", "label", "value"],
        )
        suggestion = label_utils.suggest_label_config(df, "Reviewers")
        assert suggestion == {
            "options": ["Ana", "Bruno", "Carla Dias"],
            "multi_select": True,
            "rows": 3,
        }

    def test_one_value_per_entry_suggests_single_select(self):
        df = pd.DataFrame(
            [("e1", "Ok", "yes"), ("e2", "Ok", "no")], columns=["entry_id", "label", "value"]
        )
        assert label_utils.suggest_label_config(df, "Ok")["multi_select"] is False


class TestReadFile:
    def test_utf8_with_bom_and_cp1252(self):
        from olim.labels import read_label_file

        bom = "﻿entry_id,label,value\n007,Ok,Codeço\n".encode()
        df = read_label_file(bom)
        assert list(df.columns) == ["entry_id", "label", "value"]
        assert df.loc[0, "entry_id"] == "007"

        cp = "entry_id,label,value\n1,Ok,Codeço\n".encode("cp1252")
        assert read_label_file(cp).loc[0, "value"] == "Codeço"


class TestConfigurePage:
    def test_two_new_labels_get_separate_prefilled_editors(self):
        from flask import render_template, session

        from olim.labels import _new_label_form

        df = pd.DataFrame(
            [("e1", "Reviewers", '["Ana", "Bruno"]'), ("e2", "Notes", "free words")],
            columns=["entry_id", "label", "value"],
        )
        with app.test_request_context("/"):
            session["language"] = "en_US"
            html = render_template(
                "label-upload-configure.html",
                project_id=1,
                token="a" * 24,
                new_labels=[_new_label_form(0, "Reviewers", df), _new_label_form(1, "Notes", df)],
                dataset=None,
            )
        # Each label posts its own type and settings
        assert 'name="type_0"' in html and 'name="type_1"' in html
        assert 'name="settings_0" id="mc_cfg_up_0_hidden"' in html
        assert 'name="settings_1" id="mc_cfg_up_1_hidden"' in html
        assert 'value="Ana"' in html and 'value="Bruno"' in html
        assert 'value="multiple_choice" selected' in html
