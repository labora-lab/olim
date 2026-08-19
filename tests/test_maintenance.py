"""Model health checks and the preset catalogue.

The monitoring functions that touch the database are exercised through their pure
parts; the ranking, the preset integrity and the settings validation need no DB.
"""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from flask import session

import olim.ml.monitoring as monitoring
from olim import app
from olim.learning_tasks import (
    CONFIGURATIONS_PATH,
    STATE_REGISTRY,
    build_initial_setup,
    get_available_configurations,
    validate_configuration,
)
from olim.learning_tasks.states import MaintenanceScan
from olim.ml.monitoring import RANK_SIGNALS, ModelHealth, audit_sample, rank_models


def health(**kwargs) -> ModelHealth:
    base = {
        "model_id": 1,
        "model_name": "m",
        "label_id": 1,
        "label_name": "l",
        "version_id": 1,
    }
    return ModelHealth(**{**base, **kwargs})


class TestRanking:
    def test_lowest_measured_accuracy_comes_first(self):
        models = [
            health(model_id=1, audit_accuracy=0.9, n_checked=50),
            health(model_id=2, audit_accuracy=0.4, n_checked=50),
            health(model_id=3, audit_accuracy=0.7, n_checked=50),
        ]
        assert [m.model_id for m in rank_models(models, "audit_accuracy")] == [2, 3, 1]

    def test_thin_evidence_never_outranks_a_real_measurement(self):
        """0.0 measured on two entries must not beat 0.6 measured on fifty."""
        models = [
            health(model_id=1, audit_accuracy=0.6, n_checked=50),
            health(model_id=2, audit_accuracy=0.0, n_checked=2),
        ]
        ranked = rank_models(models, "audit_accuracy", min_audit_samples=10)
        assert [m.model_id for m in ranked] == [1, 2]

    def test_unmeasured_models_sort_last(self):
        models = [
            health(model_id=1, audit_accuracy=None),
            health(model_id=2, audit_accuracy=0.5, n_checked=20),
        ]
        assert rank_models(models, "audit_accuracy")[0].model_id == 2

    def test_largest_confidence_drop_first(self):
        models = [
            health(model_id=1, coverage_drop=0.02),
            health(model_id=2, coverage_drop=0.30),
            health(model_id=3, coverage_drop=None),
        ]
        assert [m.model_id for m in rank_models(models, "coverage_drop")] == [2, 1, 3]

    def test_most_unchecked_predictions_first(self):
        models = [
            health(model_id=1, unchecked_predictions=5),
            health(model_id=2, unchecked_predictions=900),
        ]
        assert rank_models(models, "unchecked_predictions")[0].model_id == 2

    def test_unknown_signal_falls_back_to_accuracy(self):
        models = [
            health(model_id=1, audit_accuracy=0.9, n_checked=20),
            health(model_id=2, audit_accuracy=0.1, n_checked=20),
        ]
        assert rank_models(models, "not_a_signal")[0].model_id == 2

    @pytest.mark.parametrize("signal", RANK_SIGNALS)
    def test_every_declared_signal_is_usable(self, signal):
        assert len(rank_models([health(), health(model_id=2)], signal)) == 2


class TestDegradedVerdict:
    def test_low_accuracy_is_degraded(self):
        assert health(audit_accuracy=0.5).is_degraded(0.8, 0.1) is True

    def test_large_confidence_drop_is_degraded(self):
        assert health(coverage_drop=0.4).is_degraded(0.8, 0.1) is True

    def test_healthy_on_both_signals(self):
        assert health(audit_accuracy=0.95, coverage_drop=0.01).is_degraded(0.8, 0.1) is False

    def test_absent_signals_are_not_evidence_of_damage(self):
        assert health().is_degraded(0.8, 0.1) is False


def _confident(entry_id: int, value: str) -> SimpleNamespace:
    return SimpleNamespace(entry_id=entry_id, value=value)


class TestAuditSample:
    """audit_sample() balances the audit queue across predicted answers.

    A model that predicts the majority class far more often than the minority ones
    would otherwise fill the whole audit with majority-class entries, and the
    resulting accuracy figure would say nothing about the classes that matter most.
    """

    def _patched(self, monkeypatch, predictions):
        monkeypatch.setattr(
            monitoring, "_unchecked_confident_predictions", lambda label_id, version_id: predictions
        )

    def test_round_robins_across_predicted_values(self, monkeypatch):
        # Ten "yes" (most recent first) against two "no".
        predictions = [_confident(i, "yes") for i in range(110, 100, -1)] + [
            _confident(i, "no") for i in range(20, 18, -1)
        ]
        self._patched(monkeypatch, predictions)

        sample = audit_sample(label_id=1, version_id=1, n=4)

        values = [p.value for e in sample for p in predictions if p.entry_id == e]
        assert values.count("no") == 2
        assert values.count("yes") == 2

    def test_never_returns_more_than_available(self, monkeypatch):
        self._patched(monkeypatch, [_confident(1, "yes"), _confident(2, "no")])
        assert len(audit_sample(label_id=1, version_id=1, n=20)) == 2

    def test_exhausted_class_stops_contributing_but_others_continue(self, monkeypatch):
        predictions = [_confident(1, "no")] + [_confident(i, "yes") for i in range(10, 4, -1)]
        self._patched(monkeypatch, predictions)

        sample = audit_sample(label_id=1, version_id=1, n=4)
        assert len(sample) == 4
        assert 1 in sample  # the lone "no" is never starved out by round-robin

    def test_zero_or_negative_n_returns_nothing(self, monkeypatch):
        self._patched(monkeypatch, [_confident(1, "yes")])
        assert audit_sample(label_id=1, version_id=1, n=0) == []
        assert audit_sample(label_id=1, version_id=1, n=-5) == []


class TestMaintenanceSettings:
    def _state(self):
        return MaintenanceScan({}, {"_project_id": 1, "_user_id": 1})

    @pytest.fixture(autouse=True)
    def request_context(self):
        with app.test_request_context("/"):
            session["language"] = "en_US"
            yield

    def test_valid_settings_are_stored(self):
        state = self._state()
        errors = state._apply_settings({"audit_sample_size": "30", "accuracy_threshold": "0.75"})
        assert errors == {}
        assert state.data["maint_setting_audit_sample_size"] == 30
        assert state.data["maint_setting_accuracy_threshold"] == 0.75

    def test_out_of_range_is_rejected(self):
        assert "accuracy_threshold" in self._state()._apply_settings({"accuracy_threshold": "5"})

    def test_unknown_rank_signal_is_rejected(self):
        assert "rank_by" in self._state()._apply_settings({"rank_by": "vibes"})

    def test_unchecked_toggle_stores_false(self):
        state = self._state()
        state._apply_settings({"measure_coverage": "1"})
        assert state.data["maint_setting_measure_coverage"] is True
        state._apply_settings({})
        assert state.data["maint_setting_measure_coverage"] is False

    def test_preset_params_are_the_default_when_nothing_is_overridden(self):
        state = MaintenanceScan({}, {"_project_id": 1, "_user_id": 1, "audit_sample_size": 5})
        assert state._current_settings()["audit_sample_size"] == 5

    def test_label_ids_default_to_empty_meaning_every_model(self):
        state = self._state()
        assert state._current_settings()["label_ids"] == []

    def test_label_ids_are_stored_as_ints(self):
        state = self._state()
        state._apply_settings({"label_ids": ["3", "7"]})
        assert state.data["maint_setting_label_ids"] == [3, 7]
        assert state._current_settings()["label_ids"] == [3, 7]

    def test_label_ids_clear_when_none_are_checked_again(self):
        state = self._state()
        state._apply_settings({"label_ids": ["3"]})
        state._apply_settings({})
        assert state.data["maint_setting_label_ids"] == []


class TestPresetCatalogue:
    """Guards the cleanup: every shipped preset must be loadable and coherent."""

    @staticmethod
    def presets():
        return [json.loads(p.read_text()) for p in sorted(CONFIGURATIONS_PATH.glob("*.json"))]

    def test_the_expected_six_are_shipped(self):
        names = {c["name"] for c in self.presets()}
        assert names == {
            "Labeling Queue",
            "LLM Auto-Labeling",
            "Active Learning",
            "Active Learning — Queue Start",
            "Active Learning — LLM Cold Start",
            "Active Learning — Maintenance",
        }

    def test_every_preset_validates(self):
        for config in self.presets():
            valid, error = validate_configuration(config)
            assert valid, f"{config.get('name')}: {error}"

    def test_every_state_is_registered(self):
        for config in self.presets():
            for step in config["sequence"]:
                assert step["state"] in STATE_REGISTRY, step["state"]

    def test_presentation_keys_are_present_and_unique(self):
        configs = self.presets()
        orders = [c["order"] for c in configs]
        assert len(set(orders)) == len(orders), "duplicate order values reorder the picker"
        for config in configs:
            assert config.get("name") and config.get("description") and config.get("icon")

    def test_dead_params_are_gone(self):
        """These are documented but never read; leaving them implies they do something."""
        dead = {"dataset_id", "project_id", "id_separator", "auto_start", "is_last_step"}
        for config in self.presets():
            for step in config["sequence"]:
                assert not (dead & set(step.get("params", {}))), f"{config['name']}/{step['state']}"

    def test_queue_producers_precede_label_entry(self):
        producers = {"QueueSetup", "ColdStartSearchSetup", "OllamaQueueSetup", "MaintenanceScan"}
        for config in self.presets():
            states = [s["state"] for s in config["sequence"]]
            for i, state in enumerate(states):
                if state == "LabelEntry":
                    assert producers & set(states[:i]), f"{config['name']}: nothing fills the queue"

    def test_ollama_states_are_adjacent_and_ordered(self):
        """OllamaAutoLabel's back_to_setup jumps -2, which assumes this exact layout."""
        for config in self.presets():
            states = [s["state"] for s in config["sequence"]]
            if "OllamaAutoLabel" not in states:
                continue
            i = states.index("OllamaAutoLabel")
            assert states[i - 2 : i] == ["OllamaQueueSetup", "OllamaModelConfig"], config["name"]

    def test_the_retired_search_preset_is_gone_but_its_state_survives(self):
        """Tasks created before the cleanup still name it; an unregistered state 500s."""
        assert not (CONFIGURATIONS_PATH / "active_learning_search_cold_start.json").exists()
        assert "ColdStartSearchSetup" in STATE_REGISTRY

    def test_picker_payload_carries_an_icon_and_sorts_by_order(self):
        configs = get_available_configurations()
        assert configs and all(c["icon"] for c in configs)
        assert [c["order"] for c in configs] == sorted(c["order"] for c in configs)


class TestInitialSetup:
    def test_show_progress_survives_task_creation(self):
        """Presets have always set it; create_learning_task used to drop it on the
        floor, so the progress bar never appeared for any of them."""
        setup = build_initial_setup(
            {"sequence": [{"state": "LabelEntry"}], "show_progress": True, "name": "X"}
        )
        assert setup["show_progress"] is True
        assert setup["preset_name"] == "X"

    def test_sequence_is_always_present(self):
        assert build_initial_setup({})["sequence"] == []

    def test_every_shipped_preset_keeps_its_progress_setting(self):
        for path in Path(CONFIGURATIONS_PATH).glob("*.json"):
            config = json.loads(path.read_text())
            expected = config.get("show_progress", False)
            assert build_initial_setup(config)["show_progress"] == expected
