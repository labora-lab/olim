"""The configuration picker on the learning tasks page.

A native <select> cannot show an icon or a per-option description, so this is a
custom listbox. The value rides on a hidden input, which is what the form posts —
if that breaks, task creation breaks silently.
"""

from pathlib import Path

import pytest
from flask import render_template, session

from olim import app
from olim.learning_tasks import get_available_configurations, localised

CSS = Path(__file__).resolve().parents[1] / "olim" / "static" / "css" / "output.css"


@pytest.fixture(autouse=True)
def request_context():
    with app.test_request_context("/"):
        session["language"] = "en_US"
        yield


@pytest.fixture
def configs():
    return get_available_configurations()


def render(configurations):
    return render_template(
        "learning-tasks.html",
        project_id=1,
        my_tasks=[],
        all_tasks=[],
        users=[],
        configurations=configurations,
        available_states=[],
        is_admin=True,
    )


class TestPickerMarkup:
    def test_the_form_still_posts_a_configuration(self, configs):
        """The hidden input is the whole contract with create_learning_task."""
        html = render(configs)
        assert 'id="configuration" name="configuration"' in html
        assert f'value="{configs[0]["filename"]}"' in html

    def test_one_option_per_configuration(self, configs):
        html = render(configs)
        assert html.count('role="option"') == len(configs)
        assert 'role="listbox"' in html

    def test_each_option_carries_icon_value_and_description(self, configs):
        html = render(configs)
        for config in configs:
            assert f'data-value="{config["filename"]}"' in html
            assert f"bi-{config['icon']}" in html
            assert config["description"] in html

    def test_description_shows_on_hover_and_below_the_control(self, configs):
        html = render(configs)
        for config in configs:
            assert f'title="{config["description"]}"' in html  # hover helper
        assert 'id="config-description"' in html
        assert configs[0]["description"] in html  # the line under the control

    def test_exactly_one_option_starts_selected(self, configs):
        html = render(configs)
        assert html.count('aria-selected="true"') == 1
        assert html.count("config-check invisible") == len(configs) - 1

    def test_accessible_attributes(self, configs):
        html = render(configs)
        for probe in (
            'aria-haspopup="listbox"',
            'aria-expanded="false"',
            'aria-labelledby="config-label"',
        ):
            assert probe in html, probe

    def test_empty_state_when_nothing_is_installed(self):
        html = render([])
        assert "No configurations available" in html
        assert 'role="listbox"' not in html

    def test_descriptions_never_reach_a_js_literal(self, configs):
        """The old picker built a JS object from descriptions; one apostrophe broke
        the whole page."""
        assert "configDescriptions" not in render(configs)

    def test_hostile_description_is_escaped(self):
        nasty = [
            {
                "filename": "x",
                "name": "It's a Test",
                "icon": "robot",
                "steps": 2,
                "order": 10,
                "description": 'Don\'t break: "quotes" & <b>tags</b>',
            }
        ]
        html = render(nasty)
        assert "<b>tags</b>" not in html
        assert "&lt;b&gt;" in html


class TestPickerStyling:
    """output.css is committed with no build step, so a class only exists if
    `make css` has been run since the template last changed."""

    @pytest.mark.parametrize("utility", ["rotate-180", "z-20", "max-h-80", "invisible", "shrink-0"])
    def test_utilities_are_in_the_compiled_bundle(self, utility):
        assert utility in CSS.read_text(), f"{utility} missing — run `make css`"


class TestLocalisedPresetCopy:
    """Preset names and descriptions live in JSON, which babel does not extract, so
    a preset carries its own translations via name_<locale> keys."""

    @pytest.fixture(autouse=True)
    def request_context(self):
        """Override the module fixture: no ambient request context here.

        These tests push their own, and flask_babel caches the resolved locale — a
        *nested* context inherits the outer one, so switching languages inside an
        existing request silently does nothing.
        """
        yield

    CONFIG = {
        "name": "Labeling Queue",
        "name_pt_BR": "Fila de Rotulagem",
        "name_pt": "Fila (pt)",
        "description": "Label by hand.",
        "description_pt_BR": "Rotule à mão.",
    }

    @staticmethod
    def in_locale(lang, config, key, default=""):
        with app.test_request_context("/"):
            session["language"] = lang
            return localised(config, key, default)

    def test_exact_locale_wins(self):
        assert self.in_locale("pt_BR", self.CONFIG, "name") == "Fila de Rotulagem"

    def test_language_only_key_is_the_next_choice(self):
        config = {k: v for k, v in self.CONFIG.items() if k != "name_pt_BR"}
        assert self.in_locale("pt_BR", config, "name") == "Fila (pt)"

    def test_falls_back_to_the_untagged_key(self):
        assert self.in_locale("en_US", self.CONFIG, "name") == "Labeling Queue"
        assert self.in_locale("pt_BR", {"name": "Only English"}, "name") == "Only English"

    def test_default_when_nothing_matches(self):
        assert self.in_locale("pt_BR", {}, "name", "fallback") == "fallback"

    def test_empty_translation_does_not_win(self):
        """A key present but blank should not blank out the English."""
        assert self.in_locale("pt_BR", {"name": "English", "name_pt_BR": ""}, "name") == "English"

    def test_works_without_a_request_context(self):
        """Called from a Celery worker or a script there is no locale to resolve."""
        assert localised({"name": "Plain"}, "name") == "Plain"

    @staticmethod
    def names_in(lang):
        # A fresh context per locale: flask_babel caches the resolved locale on the
        # request context, so reassigning session["language"] mid-request is ignored.
        with app.test_request_context("/"):
            session["language"] = lang
            return {c["filename"]: c["name"] for c in get_available_configurations()}

    def test_shipped_presets_are_translated(self):
        pt, en = self.names_in("pt_BR"), self.names_in("en_US")
        assert set(pt) == set(en)
        for filename in pt:
            assert pt[filename] != en[filename], f"{filename} has no pt_BR name"

    def test_the_picker_renders_the_translated_copy(self):
        with app.test_request_context("/"):
            session["language"] = "pt_BR"
            configs = get_available_configurations()
            html = render(configs)
        assert "Fila de Rotulagem" in html
        assert "Aprendizado Ativo — Manutenção" in html
        assert "Labeling Queue" not in html

    def test_stored_provenance_stays_canonical(self):
        """The task records which preset built it; that must not read differently
        depending on who opens it."""
        from olim.learning_tasks import build_initial_setup

        config = {"sequence": [], "name": "Active Learning", "name_pt_BR": "Aprendizado Ativo"}
        with app.test_request_context("/"):
            session["language"] = "pt_BR"
            assert build_initial_setup(config)["preset_name"] == "Active Learning"
