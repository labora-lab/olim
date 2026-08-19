"""The reusable label_selector macro used by every task-setup screen that picks labels.

One component backs queue_setup.html, al_label_select.html and maintenance_scan.html
so "create a label without leaving the wizard" behaves identically everywhere. These
tests render the macro directly rather than each host template, since the host
templates only need to supply labels/selected_ids/project_id correctly — already
covered by test_al_templates.py's per-screen render tests.
"""

import pytest
from flask import render_template_string, session

from olim import app

MACRO_CALL = """
{% import "macros/label_selector.html" as selector %}
{{ selector.label_selector(field_name, labels, selected_ids, project_id, mode=mode,
   label_text=label_text, help_text=help_text, required=required, error=error,
   accent=accent, checkbox_class=checkbox_class) }}
"""


class FakeLabel:
    def __init__(self, id, name) -> None:
        self.id = id
        self.name = name


LABELS = [FakeLabel(1, "Sepsis"), FakeLabel(2, "Pet")]


@pytest.fixture(autouse=True)
def request_context():
    with app.test_request_context("/"):
        session["language"] = "en_US"
        yield


def render(**over):
    ctx = {
        "field_name": "labels",
        "labels": LABELS,
        "selected_ids": [],
        "project_id": 1,
        "mode": "multi",
        "label_text": None,
        "help_text": None,
        "required": False,
        "error": None,
        "accent": "teal",
        "checkbox_class": "",
    }
    return render_template_string(MACRO_CALL, **{**ctx, **over})


class TestMultiMode:
    def test_renders_a_checkbox_per_label(self):
        html = render()
        assert html.count('type="checkbox" name="labels"') == 2

    def test_selected_ids_are_checked(self):
        html = render(selected_ids=[2])
        # The Pet checkbox (value="2") must be checked; Sepsis (value="1") must not.
        pet_row = html.split('value="2"')[1].split("</label>")[0]
        sepsis_row = html.split('value="1"')[1].split("</label>")[0]
        assert "checked" in pet_row
        assert "checked" not in sepsis_row

    def test_no_labels_shows_a_hint_instead_of_an_empty_list(self):
        html = render(labels=[])
        assert "No labels yet" in html


class TestSingleMode:
    def test_renders_a_select_with_one_option_per_label(self):
        html = render(mode="single", field_name="label_id")
        assert '<select name="label_id"' in html
        main_select = html.split('<select name="label_id"')[1].split("</select>")[0]
        assert main_select.count("<option") == 3  # placeholder + two labels

    def test_selected_id_is_selected(self):
        html = render(mode="single", field_name="label_id", selected_ids=[2])
        pet_option = html.split('value="2"')[1].split("</option>")[0]
        assert "selected" in pet_option


class TestNewLabelAffordance:
    def test_offers_a_new_label_form_with_the_create_endpoint(self):
        html = render()
        assert "New label" in html
        assert "/1/labels/quick_create" in html

    def test_multiple_choice_is_excluded_from_the_quick_type_picker(self):
        html = render()
        type_select = html.split('name="_new_label_type"')[1].split("</select>")[0]
        assert 'value="multiple_choice"' not in type_select
        assert 'value="yes_no"' in type_select

    def test_carries_selector_context_so_the_response_can_rebuild_it(self):
        html = render(
            field_name="label_ids",
            mode="multi",
            label_text="Labels to check",
            help_text="Leave empty for all",
            required=True,
            accent="purple",
            checkbox_class="label-checkbox",
        )
        for hidden in (
            '<input type="hidden" name="_selector_field" value="label_ids">',
            '<input type="hidden" name="_selector_mode" value="multi">',
            '<input type="hidden" name="_selector_label_text" value="Labels to check">',
            '<input type="hidden" name="_selector_help_text" value="Leave empty for all">',
            '<input type="hidden" name="_selector_required" value="1">',
            '<input type="hidden" name="_selector_accent" value="purple">',
            '<input type="hidden" name="_selector_checkbox_class" value="label-checkbox">',
        ):
            assert hidden in html, hidden


class TestErrorDisplay:
    def test_error_message_is_shown(self):
        html = render(error="Please select at least one label")
        assert "Please select at least one label" in html
