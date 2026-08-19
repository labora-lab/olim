"""Active learning: when the loop is allowed to declare the goal reached.

The regression these guard against: with retrain_every=10 and an 80/20 split, the
first round scored AUC on about two validation rows, and a single lucky round with
mg_consecutive=1 ended the whole run.
"""

import pytest

from olim import app
from olim.label_types import get_abstain_values
from olim.learning_tasks.states import ActiveLearningLoop


@pytest.fixture(autouse=True)
def request_context():
    """The messages go through flask_babel's _(), and this app's locale selector
    reads the session — so a request context, not just an app context, is needed."""
    with app.test_request_context("/"):
        yield


def make_state(history, **settings) -> ActiveLearningLoop:
    data = {
        "al_metrics_history": history,
        "al_metrics": history[-1] if history else {},
        "al_round": history[-1]["round"] if history else 0,
    }
    defaults = {
        "metric_goal": {"macro_f1": 0.8},
        "metric_direction": "above",
        "mg_consecutive": 3,
        "mg_min_val_samples": 20,
        "max_rounds": 10,
    }
    defaults.update(settings)
    for key, value in defaults.items():
        data[f"al_setting_{key}"] = value
    return ActiveLearningLoop(data, {"_project_id": 1, "_user_id": 1})


def rounds(*scores, n_val=40, metric="macro_f1"):
    return [
        {"round": i + 1, "n_val_samples": n_val, metric: score} for i, score in enumerate(scores)
    ]


class TestGoalProgress:
    def test_no_goal_configured(self):
        state = make_state(rounds(0.99), metric_goal={})
        assert state._goal_progress() is None

    def test_partial_window_never_fires(self):
        """One brilliant round is not evidence; the window has to fill first."""
        progress = make_state(rounds(0.99, 0.99))._goal_progress()
        assert progress["met"] is False
        assert "1 more round" in progress["blocked"]
        # The mean is still reported so the UI can show how close the run is.
        assert progress["mean"] == pytest.approx(0.99)

    def test_mean_is_reported_even_while_a_guard_blocks(self):
        progress = make_state(rounds(0.9, 0.9, 0.9, n_val=2))._goal_progress()
        assert progress["met"] is False
        assert progress["val_have"] == 2
        assert progress["mean"] == pytest.approx(0.9)

    def test_tiny_validation_set_blocks_the_goal(self):
        """A perfect score measured on two entries is noise, not achievement."""
        progress = make_state(rounds(1.0, 1.0, 1.0, n_val=2))._goal_progress()
        assert progress["met"] is False
        assert progress["val_have"] == 2
        assert "20" in progress["blocked"]

    def test_mean_over_the_window_decides(self):
        # Last round alone clears 0.8, the three-round mean does not.
        progress = make_state(rounds(0.60, 0.70, 0.95))._goal_progress()
        assert progress["mean"] == pytest.approx(0.75)
        assert progress["met"] is False

        progress = make_state(rounds(0.78, 0.81, 0.85))._goal_progress()
        assert progress["mean"] == pytest.approx(0.8133, abs=1e-4)
        assert progress["met"] is True

    def test_only_the_last_window_counts(self):
        progress = make_state(rounds(0.1, 0.1, 0.9, 0.9, 0.9))._goal_progress()
        assert progress["mean"] == pytest.approx(0.9)
        assert progress["met"] is True

    def test_below_direction(self):
        state = make_state(
            rounds(0.2, 0.3, 0.1, metric="conformal_threshold"),
            metric_goal={"conformal_threshold": 0.25},
            metric_direction="below",
        )
        assert state._goal_progress()["met"] is True

    def test_missing_metric_is_never_treated_as_met(self):
        """metrics.get(key, 0) used to make any "<=" goal true on round one."""
        state = make_state(
            rounds(0.9, 0.9, 0.9),
            metric_goal={"precision": 0.5},
            metric_direction="below",
        )
        progress = state._goal_progress()
        assert progress["met"] is False
        assert "precision" in progress["blocked"]

    def test_a_short_window_still_needs_enough_validation_data(self):
        progress = make_state(rounds(1.0, n_val=5), mg_consecutive=1)._goal_progress()
        assert progress["met"] is False

    def test_window_of_one_with_enough_data_fires(self):
        progress = make_state(rounds(0.9), mg_consecutive=1)._goal_progress()
        assert progress["met"] is True


class TestStopReason:
    def test_goal_stops_the_loop(self):
        state = make_state(rounds(0.9, 0.9, 0.9))
        state._update_stop_reason()
        assert state.data["al_stop_reason"] == "goal"
        assert state._check_goal_reached() is True

    def test_max_rounds_stops_the_loop(self):
        state = make_state(rounds(*[0.1] * 4), max_rounds=4)
        state.data["al_round"] = 4
        state._update_stop_reason()
        assert state.data["al_stop_reason"] == "max_rounds"

    def test_unlimited_rounds(self):
        state = make_state(rounds(*[0.1] * 20), max_rounds=-1)
        state.data["al_round"] = 20
        state._update_stop_reason()
        assert "al_stop_reason" not in state.data

    def test_stop_reason_clears_when_the_metric_falls_back(self):
        state = make_state(rounds(0.9, 0.9, 0.9))
        state._update_stop_reason()
        assert state.data["al_stop_reason"] == "goal"

        state.data["al_metrics_history"] = rounds(0.9, 0.9, 0.2)
        state._update_stop_reason()
        assert "al_stop_reason" not in state.data


class TestMetricsPayload:
    def test_structured_metrics_are_preferred(self):
        metrics = ActiveLearningLoop._parse_metrics(
            {"metrics_dict": {"macro_f1": 0.8, "macro_f1_ci": [0.6, 0.95]}}
        )
        assert metrics["macro_f1_ci"] == [0.6, 0.95]

    def test_legacy_string_metrics_still_parse(self):
        metrics = ActiveLearningLoop._parse_metrics(
            {"metrics": ["accuracy: 0.9000", "accuracy_ci: [0.4, 1.0]"]}
        )
        assert metrics["accuracy"] == 0.9
        # A stringified interval cannot round-trip — the reason metrics_dict exists.
        assert metrics["accuracy_ci"] == "[0.4, 1.0]"


class TestSettingsValidation:
    def _state(self):
        return ActiveLearningLoop({}, {"_project_id": 1, "_user_id": 1})

    def test_zero_certain_rate_is_saved(self):
        """The old "if val > 0" filter silently dropped the documented off value."""
        state = self._state()
        assert state._apply_settings({"certain_rate": "0"}) == {}
        assert state.data["al_setting_certain_rate"] == 0.0

    def test_unlimited_max_rounds_is_allowed(self):
        state = self._state()
        assert state._apply_settings({"max_rounds": "-1"}) == {}
        assert state.data["al_setting_max_rounds"] == -1

    def test_zero_max_rounds_is_rejected_with_a_message(self):
        state = self._state()
        errors = state._apply_settings({"max_rounds": "0"})
        assert "max_rounds" in errors
        assert "al_setting_max_rounds" not in state.data

    def test_out_of_range_value_is_reported(self):
        state = self._state()
        assert "split" in state._apply_settings({"split": "5"})

    def test_unknown_goal_metric_is_rejected(self):
        state = self._state()
        errors = state._apply_settings({"mg_metric": "precision", "mg_threshold": "0.5"})
        assert "mg_metric" in errors

    def test_metric_without_threshold_is_reported(self):
        state = self._state()
        assert "mg_threshold" in state._apply_settings({"mg_metric": "macro_f1"})

    def test_clearing_the_metric_removes_the_goal(self):
        state = self._state()
        state._apply_settings({"mg_metric": "macro_f1", "mg_threshold": "0.8"})
        assert state.data["al_setting_metric_goal"] == {"macro_f1": 0.8}
        state._apply_settings({"mg_metric": "", "mg_threshold": ""})
        assert "al_setting_metric_goal" not in state.data

    def test_unchecked_toggle_is_stored_as_false(self):
        state = self._state()
        state._apply_settings({"balance_classes": "1"})
        assert state.data["al_setting_balance_classes"] is True
        state._apply_settings({})
        assert state.data["al_setting_balance_classes"] is False

    def test_presets_are_valid_settings(self):
        for name, preset in ActiveLearningLoop.PRESETS.items():
            state = self._state()
            errors = state._apply_settings(
                {k: str(v) for k, v in preset.items() if not isinstance(v, bool)}
            )
            assert errors == {}, f"preset {name}: {errors}"

    def test_reset_clears_every_override(self):
        state = self._state()
        state._apply_settings({"split": "0.7", "mg_metric": "macro_f1", "mg_threshold": "0.8"})
        state.data["al_round"] = 3
        state._reset_settings()
        assert not [k for k in state.data if k.startswith("al_setting_")]
        assert state.data["al_round"] == 3  # progress is not settings

    def test_reset_keeps_the_setup_completed_flag(self):
        """al_settings_done is one character away from the al_setting_ prefix the
        reset sweeps; clearing it would bounce a running loop back to setup."""
        state = self._state()
        state.data["al_settings_done"] = True
        state.data["al_setting_split"] = 0.7
        state._reset_settings()
        assert state.data["al_settings_done"] is True
        assert "al_setting_split" not in state.data


class TestAbstainValues:
    @pytest.mark.parametrize(
        ("label_type", "expected"),
        [
            ("sim_nao_ns", {"não sei"}),
            ("yes_no_unknown", {"unknown"}),
            ("yes_no_idk", {"don't know"}),
            ("sim_nao", set()),
            ("yes_no", set()),
        ],
    )
    def test_preset_abstain_values(self, label_type, expected):
        assert get_abstain_values(label_type) == expected

    def test_multiple_choice_reads_the_configured_flag(self):
        class FakeLabel:
            label_settings = {
                "options": [
                    {"value": "yes"},
                    {"value": "no"},
                    {"value": "cannot tell", "abstain": True},
                ]
            }

        assert get_abstain_values("multiple_choice", FakeLabel()) == {"cannot tell"}


class TestActivePresetHighlight:
    """Which preset card is highlighted must reflect the settings in force.

    It was hardcoded to "custom", so the card reset every time the form re-rendered.
    """

    def test_shipped_preset_params_read_as_recommended(self):
        import json
        from pathlib import Path

        config = json.loads(
            Path("olim/learning_tasks/configurations/active_learning.json").read_text()
        )
        params = dict(config["sequence"][0]["params"])
        params |= {"_project_id": 1, "_user_id": 1}
        assert ActiveLearningLoop({}, params)._active_preset() == "recommended"

    @pytest.mark.parametrize("name", ["recommended", "fast", "confident"])
    def test_applying_a_preset_is_detected(self, name):
        state = ActiveLearningLoop({}, {"_project_id": 1, "_user_id": 1})
        preset = ActiveLearningLoop.PRESETS[name]
        payload = {k: str(v) for k, v in preset.items() if not isinstance(v, bool)}
        payload |= {k: "1" for k, v in preset.items() if v is True}
        state._apply_settings(payload)
        assert state._active_preset() == name

    def test_a_hand_edit_falls_back_to_custom(self):
        state = ActiveLearningLoop({}, {"_project_id": 1, "_user_id": 1})
        state._apply_settings({"split": "0.55"})
        assert state._active_preset() == "custom"
