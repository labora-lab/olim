"""Render every active learning screen.

These exist because a bare "%" in a translatable string makes Jinja's i18n
extension treat it as a format template and raise at *render* time — ruff, template
compilation and pybabel all pass, so only an actual render catches it.
"""

import re

import pytest
from flask import render_template, session

from olim import app
from olim.learning_tasks.states import ActiveLearningLoop
from olim.ml.orchestrator import DIAGNOSTIC_METRICS, GOAL_METRICS

TEMPLATE = "learning_tasks/active_learning_loop.html"
DETAILS_OPEN = re.compile(r"<details[^>]*\sopen>")


class FakeLabel:
    id = 3
    name = "Suspeita de sepse"


@pytest.fixture(autouse=True)
def request_context():
    with app.test_request_context("/"):
        session["language"] = "en_US"
        yield


@pytest.fixture
def setup_context():
    state = ActiveLearningLoop({}, {"_project_id": 1, "_user_id": 1})
    return {
        "labels": [FakeLabel()],
        "selected_label": FakeLabel(),
        "label_locked": False,
        "settings": state._current_settings(),
        "setting_specs": ActiveLearningLoop.SETTING_SPECS,
        "presets": ActiveLearningLoop.PRESETS,
        "goal_metrics": GOAL_METRICS,
        "errors": {},
        "started": False,
        "round": 0,
        "is_last_step": True,
    }


METRICS = {
    "accuracy": 0.91,
    "accuracy_ci": [0.82, 0.97],
    "macro_f1": 0.74,
    "macro_f1_ci": [0.55, 0.9],
    "auc_roc": 0.88,
    "auc_roc_ci_valid_frac": 0.31,
    "coverage": 0.63,
    "validation_balanced": False,
    "conformal_degenerate": True,
    "conformal_alpha_effective": 0.25,
    "per_class": {
        "não": {"precision": 0.95, "recall": 0.97, "f1": 0.96, "support": 20},
        "sim": {"precision": 0.6, "recall": 0.5, "f1": 0.55, "support": 20},
    },
}
HISTORY = [
    {"round": 1, "n_val_samples": 4, "accuracy": 1.0, "macro_f1": 1.0},
    {"round": 2, "n_val_samples": 12, "accuracy": 0.83, "macro_f1": 0.8, "auc_roc": 0.9},
    {"round": 3, "n_val_samples": 40, "accuracy": 0.91, "macro_f1": 0.74, "auc_roc": 0.88},
]
GOAL = {
    "metric": "macro_f1",
    "threshold": 0.8,
    "direction": "above",
    "window": 3,
    "mean": 0.8467,
    "met": False,
    "blocked": None,
}


class TestSetupScreen:
    @pytest.mark.parametrize("mode", ["select", "settings"])
    def test_renders(self, mode, setup_context):
        html = render_template(TEMPLATE, mode=mode, title="Active Learning", **setup_context)
        for probe in (
            "When to stop",
            "Labeling pace",
            "Model training",
            "Candidate sampling",
            "al-preset-data",
            'name="mg_min_val_samples"',
            'name="certain_rate"',
        ):
            assert probe in html, probe

    def test_start_button_before_the_loop_runs(self, setup_context):
        html = render_template(TEMPLATE, mode="select", title="t", **setup_context)
        assert "Start Active Learning" in html
        assert 'value="cancel_settings"' not in html

    def test_save_and_back_once_started(self, setup_context):
        html = render_template(
            TEMPLATE, mode="settings", title="t", **{**setup_context, "started": True}
        )
        assert "Save settings" in html and 'value="cancel_settings"' in html

    def test_label_locked_by_an_earlier_step(self, setup_context):
        html = render_template(
            TEMPLATE, mode="settings", title="t", **{**setup_context, "label_locked": True}
        )
        assert "bi-lock" in html and '<select id="al-label-select"' not in html

    def test_errors_show_inline_and_open_the_panel(self, setup_context):
        clean = render_template(TEMPLATE, mode="settings", title="t", **setup_context)
        err = render_template(
            TEMPLATE,
            mode="settings",
            title="t",
            **{**setup_context, "errors": {"split": "Must be 0.1 to 0.95."}},
        )
        assert "Must be 0.1 to 0.95." in err and "border-red-500" in err
        assert DETAILS_OPEN.search(err) and not DETAILS_OPEN.search(clean)

    def test_certain_rate_allows_the_papers_configuration(self, setup_context):
        html = render_template(TEMPLATE, mode="settings", title="t", **setup_context)
        bounds = re.search(r'id="al-certain_rate"[^>]*min="([\d.]+)" max="([\d.]+)"', html)
        assert bounds.group(2) == "0.9"  # 0.5 excluded the paper's 30/70 split


class TestResultsScreen:
    def _render(self, **over):
        ctx = {
            "mode": "results",
            "title": "t",
            "metrics": METRICS,
            "history": HISTORY,
            "diagnostics": DIAGNOSTIC_METRICS,
            "round": 3,
            "n_val_samples": 40,
            "n_train_samples": 160,
            "stop_reason": "max_rounds",
            "goal": GOAL,
            "stop_max_rounds": 3,
            "is_last_step": True,
        }
        return render_template(TEMPLATE, **{**ctx, **over})

    def test_reports_metrics_intervals_and_per_class(self):
        html = self._render()
        for probe in (
            "Per-class Results",
            "Recall",
            "0.820",
            "interval unavailable",
            "40 validation / 160 training examples",
        ):
            assert probe in html, probe

    def test_diagnostics_are_warnings_not_metric_tiles(self):
        html = self._render()
        assert "validation_balanced" not in html
        assert "lean towards the most common answer" in html
        assert "loosened to 0.25" in html

    def test_goal_banner_states_the_mean_and_window(self):
        html = self._render(stop_reason="goal", goal={**GOAL, "met": True})
        assert "macro_f1 averaged 0.847 over the last 3 round(s)" in html


class TestLoopScreens:
    def test_history_columns_align_when_a_metric_is_missing(self):
        html = render_template(
            TEMPLATE,
            mode="train",
            sub="progress",
            title="t",
            round=2,
            progress=40,
            message="training",
            metrics_history=HISTORY,
            is_last_step=False,
        )
        headers = re.findall(r'<th class="[^"]*">\s*(.*?)\s*</th>', html, re.S)
        assert headers == ["Round", "val n", "accuracy", "macro_f1", "auc_roc"]
        body = re.findall(r'<tr class="border-t[^"]*">(.*?)</tr>', html, re.S)
        cells = [
            [re.sub(r"<[^>]+>", "", c).strip() for c in re.findall(r"<td[^>]*>(.*?)</td>", r, re.S)]
            for r in body
        ]
        # Round 1 predates auc_roc; the gap must be a placeholder, not a shift.
        assert cells[0] == ["1", "4", "1.0000", "1.0000", "—"]
        assert cells[1][-1] == "0.9000"

    def test_training_error_offers_a_retry(self):
        html = render_template(
            TEMPLATE,
            mode="train",
            sub="error",
            title="t",
            error="boom",
            round=1,
            is_last_step=False,
        )
        assert "boom" in html and 'value="retry_train"' in html


class TestLabelMode:
    """The screen an annotator actually sits on, and the one whose CI tooltip 500'd.

    Its metrics block was never rendered by a test before, which is why a bare
    percent in `_('95% CI')` reached production.
    """

    def _render(self, **over):
        ctx = {
            "mode": "label",
            "title": "t",
            "entry": None,
            "entry_html": "<p>text</p>",
            "entry_tab_nav": "",
            "valid_entry": False,
            "labels_values": {},
            "label": None,
            "label_options": [],
            "position": 3,
            "total": 100,
            "labels_this_round": 2,
            "retrain_every": 10,
            "round": 1,
            "metrics": METRICS,
            "diagnostics": DIAGNOSTIC_METRICS,
            "n_val_samples": 40,
            "goal": GOAL,
            "retraining": False,
            "task_error": None,
            "entry_score": 0.42,
            "entry_reason": "uncertainty",
            "show_highlights": True,
            "highlight": None,
            "is_last_step": False,
        }
        return render_template(TEMPLATE, **{**ctx, **over})

    def test_renders_with_metrics_and_confidence_intervals(self):
        html = self._render()
        assert "95% CI" in html  # literal percent survives the gettext escape
        assert "0.820" in html and "0.970" in html

    def test_renders_without_metrics(self):
        assert self._render(metrics={}, n_val_samples=None, goal=None)

    def test_goal_progress_is_shown(self):
        assert "macro_f1" in self._render()

    def test_retraining_indicator(self):
        assert "retraining" in self._render(retraining=True)

    def test_settings_gear_is_present(self):
        assert 'value="open_settings"' in self._render()


class TestMaintenanceScreens:
    """Every mode of the maintenance screens, for the same reason as above."""

    TEMPLATE = "learning_tasks/maintenance_scan.html"
    REVIEW = "learning_tasks/maintenance_review.html"

    REPORTS = [
        {
            "model_id": 1,
            "model_name": "Sepse Model",
            "label_id": 1,
            "label_name": "Suspeita de sepse",
            "version_id": 4,
            "version_number": 4,
            "trained_at": "2026-06-01T10:00:00",
            "n_checked": 32,
            "n_agree": 20,
            "audit_accuracy": 0.625,
            "per_class": {},
            "coverage_at_training": 0.9,
            "coverage_now": 0.61,
            "coverage_drop": 0.29,
            "unchecked_predictions": 1420,
            "reasons": [],
        },
        {
            "model_id": 2,
            "model_name": "Pet Model",
            "label_id": 2,
            "label_name": "Pet",
            "version_id": 9,
            "version_number": 9,
            "trained_at": "2026-08-01T10:00:00",
            "n_checked": 3,
            "n_agree": 0,
            "audit_accuracy": 0.0,
            "per_class": {},
            "coverage_at_training": 0.8,
            "coverage_now": 0.79,
            "coverage_drop": 0.01,
            "unchecked_predictions": 12,
            "reasons": [],
        },
    ]

    def _findings(self, **over):
        from olim.ml.monitoring import RANK_SIGNALS  # noqa: F401

        ctx = {
            "mode": "findings",
            "title": "t",
            "reports": self.REPORTS,
            "selected": self.REPORTS[0],
            "audit_size": 20,
            "rank_by": "audit_accuracy",
            "min_audit_samples": 10,
            "may_configure": True,
            "is_last_step": False,
        }
        return render_template(self.TEMPLATE, **{**ctx, **over})

    def test_setup_renders_every_control(self):
        from olim.learning_tasks.states import MaintenanceScan
        from olim.ml.monitoring import RANK_SIGNALS

        state = MaintenanceScan({}, {"_project_id": 1, "_user_id": 1})
        html = render_template(
            self.TEMPLATE,
            mode="setup",
            title="t",
            settings=state._current_settings(),
            setting_specs=MaintenanceScan.SETTING_SPECS,
            rank_signals=RANK_SIGNALS,
            errors={},
            may_configure=True,
            scanned=False,
            is_last_step=False,
        )
        for probe in (
            'name="rank_by"',
            'name="audit_sample_size"',
            'name="accuracy_threshold"',
            'name="measure_coverage"',
        ):
            assert probe in html, probe

    def test_scanning_polls(self):
        html = render_template(
            self.TEMPLATE,
            mode="scanning",
            title="t",
            progress=40,
            message="Checking",
            may_configure=True,
            is_last_step=False,
        )
        assert "poll_scan" in html

    def test_error_offers_a_retry(self):
        html = render_template(
            self.TEMPLATE,
            mode="error",
            title="t",
            error="boom",
            may_configure=False,
            is_last_step=False,
        )
        assert "boom" in html and 'value="rescan"' in html

    def test_findings_name_the_selected_model_and_its_evidence(self):
        html = self._findings()
        assert "Working on: Sepse Model" in html
        assert "right on 20 of the 32" in html
        assert "0.625" in html

    def test_settings_control_is_role_gated(self):
        assert 'value="open_settings"' in self._findings(may_configure=True)
        assert 'value="open_settings"' not in self._findings(may_configure=False)

    def test_no_trained_model_is_stated_plainly(self):
        html = self._findings(selected=None, reports=[], audit_size=0)
        assert "nothing to maintain yet" in html

    @pytest.mark.parametrize(
        ("name", "degraded", "enough", "probe"),
        [
            ("degraded", True, True, "needs more labels"),
            ("healthy", False, True, "is holding up"),
            ("thin", False, False, "Not enough evidence"),
        ],
    )
    def test_review_verdicts(self, name, degraded, enough, probe):
        verdict = {
            "degraded": degraded,
            "enough_evidence": enough,
            "min_samples": 10,
            "accuracy_threshold": 0.8,
            "before": 0.9,
            "model_name": "Sepse Model",
            "n_checked": 32 if enough else 2,
            "n_agree": 20 if enough else 1,
            "audit_accuracy": 0.625 if degraded else 0.95,
            "per_class": {"sim": {"n": 12, "agree": 4, "accuracy": 0.333}},
        }
        html = render_template(self.REVIEW, title="t", verdict=verdict, is_last_step=True)
        assert probe in html, name


class TestPresetCardHighlight:
    def _render(self, active):
        from olim.learning_tasks.states import ActiveLearningLoop
        from olim.ml.orchestrator import GOAL_METRICS

        state = ActiveLearningLoop({}, {"_project_id": 1, "_user_id": 1})
        return render_template(
            TEMPLATE,
            mode="settings",
            title="t",
            labels=[FakeLabel()],
            selected_label=FakeLabel(),
            label_locked=False,
            settings=state._current_settings(),
            setting_specs=ActiveLearningLoop.SETTING_SPECS,
            presets=ActiveLearningLoop.PRESETS,
            active_preset=active,
            goal_metrics=GOAL_METRICS,
            errors={},
            started=False,
            round=0,
            is_last_step=True,
        )

    @pytest.mark.parametrize("active", ["recommended", "fast", "confident", "custom"])
    def test_exactly_the_active_card_is_checked(self, active):
        html = self._render(active)
        checked = re.findall(r'name="al_preset" value="(\w+)"[^>]*?\s+checked', html, re.S)
        assert checked == [active], checked

    def test_the_highlight_classes_exist_in_the_compiled_bundle(self):
        """peer-checked:* only styles anything if it survived the Tailwind build —
        output.css is committed with no build step, so a new utility silently does
        nothing until `make css` is run."""
        from pathlib import Path

        css = Path("olim/static/css/output.css").read_text()
        for utility in (r"peer-checked\:border-blue-600", r"peer-checked\:bg-blue-50"):
            assert utility in css, f"{utility} missing — run `make css`"


class TestHighlighting:
    """The highlighter marks text inside `.highlightable`.

    Without that class the chips still render and the term list still populates —
    it just never marks anything, which looks like the feature loading and then
    doing nothing. Only the flexible_text entry type supplies its own container;
    every other type depends on the page wrapper.
    """

    class FakeEntry:
        id = 1
        entry_id = "e1"
        type = "single_text"
        dataset_id = 1

    def _render(self, **over):
        ctx = {
            "mode": "label",
            "title": "t",
            "entry": self.FakeEntry(),
            "entry_html": "<p>patient has fever</p>",
            "entry_tab_nav": "",
            "valid_entry": True,
            "labels_values": {},
            "label": None,
            "label_options": [],
            "position": 1,
            "total": 10,
            "labels_this_round": 0,
            "retrain_every": 10,
            "round": 1,
            "metrics": {},
            "diagnostics": DIAGNOSTIC_METRICS,
            "n_val_samples": None,
            "goal": None,
            "retraining": False,
            "task_error": None,
            "entry_score": None,
            "entry_reason": None,
            "show_highlights": True,
            "highlight": [{"term": "fever"}],
            "is_last_step": False,
        }
        return render_template(TEMPLATE, **{**ctx, **over})

    def test_the_entry_body_is_highlightable(self):
        assert "highlightable" in self._render()

    def test_the_chip_ui_and_the_initialiser_are_both_present(self):
        html = self._render()
        assert 'id="highlights-list"' in html  # where chips go
        assert 'id="highlight-input"' in html  # where terms are typed
        assert "initEntryHighlight" in html  # what wires them together

    def test_saved_terms_reach_the_page(self):
        assert "fever" in self._render()


@pytest.mark.parametrize(
    "template",
    [
        "learning_tasks/active_learning_loop.html",
        "learning_tasks/label_entry.html",
        "entry.html",
        "al-entry.html",
    ],
)
def test_every_labelling_screen_marks_its_entry_body(template):
    """A screen that renders entry_html must also declare the highlight target."""
    from pathlib import Path

    source = Path("olim/templates") / template
    text = source.read_text()
    if "entry_html" not in text:
        pytest.skip(f"{template} does not render an entry body")
    assert "highlightable" in text, f"{template} renders entry_html but has no .highlightable"
