"""Active learning: validation splitting, class alignment and metric behaviour.

These cover the maths that made the loop stop after one round: a proportional
validation split on imbalanced data, a metric that returned 0 on degenerate input,
and a conformal threshold that went infinite at low sample counts.

Nothing here touches Flask or the database — the units under test are pure.
"""

import numpy as np
import pytest

from olim.label_types import get_class_values, is_open_label, parse_label_value
from olim.ml.classifiers.conformal import BIG_N, ConformalPredictor
from olim.ml.classifiers.tfidf_sklearn import TfidfLogisticRegressionClassifier
from olim.ml.metrics import auc_roc, balanced_accuracy, bootstrap_metric, f1, macro_f1
from olim.ml.orchestrator import AVAILABLE_MODELS, TrainingOrchestrator

#: Distinct vocabulary per class. Single characters would not survive
#: TfidfVectorizer's default token pattern, leaving every document identical.
CLASS_WORDS = ["alpha", "beta", "gamma"]


def make_items(counts: dict[int, int]) -> list[tuple[str, int]]:
    """(text, class) pairs with `counts[c]` examples of each class c."""
    return [
        (f"{CLASS_WORDS[cls]} document filler number{i}", cls)
        for cls, n in counts.items()
        for i in range(n)
    ]


class TestBalancedSplit:
    def test_equal_per_class_validation_on_imbalanced_data(self):
        items = make_items({0: 90, 1: 10})
        train, val = TrainingOrchestrator._balanced_split(items, 0.8, seed=1)

        val_counts = {c: sum(1 for _, lbl in val if lbl == c) for c in (0, 1)}
        # Holdout budget is floor(100 * 0.2 / 2) = 10 per class, capped at half of
        # the rarest class (10 // 2 = 5) so training keeps minority examples.
        assert val_counts[0] == val_counts[1] == 5
        # Majority-class leftovers are not thrown away.
        assert sum(1 for _, lbl in train if lbl == 0) == 85
        assert sum(1 for _, lbl in train if lbl == 1) == 5

    def test_validation_grows_with_the_dataset(self):
        """Sizing the holdout off the rarest class alone kept validation at two
        entries however many labels arrived, which no amount of averaging fixes."""
        sizes = [
            len(
                TrainingOrchestrator._balanced_split(
                    make_items({0: int(n * 0.88), 1: int(n * 0.12)}), 0.8, seed=1
                )[1]
            )
            for n in (50, 100, 200, 400)
        ]
        assert sizes == sorted(sizes) and sizes[-1] > sizes[0] * 3, sizes

    def test_a_balanced_dataset_gets_a_plain_holdout(self):
        _train, val = TrainingOrchestrator._balanced_split(make_items({0: 50, 1: 50}), 0.8, seed=1)
        assert len(val) == 20  # the requested 20%

    def test_every_class_keeps_training_examples(self):
        items = make_items({0: 50, 1: 3})
        train, _val = TrainingOrchestrator._balanced_split(items, 0.8, seed=1)
        assert {lbl for _, lbl in train} == {0, 1}

    def test_split_is_deterministic_for_a_seed(self):
        items = make_items({0: 40, 1: 20})
        first = TrainingOrchestrator._balanced_split(items, 0.8, seed=7)
        second = TrainingOrchestrator._balanced_split(items, 0.8, seed=7)
        assert first == second

    @pytest.mark.parametrize(
        "counts",
        [
            {0: 4, 1: 1},  # a singleton class cannot spare an example
            {0: 10},  # only one class present
        ],
    )
    def test_falls_back_when_a_balanced_holdout_is_impossible(self, counts):
        assert TrainingOrchestrator._balanced_split(make_items(counts), 0.8, seed=1) is None

    def test_holds_out_at_least_one_per_class_when_data_is_thin(self):
        """floor(3 * 0.2) is 0, but a class with no validation examples is worse
        than a slightly larger holdout."""
        train, val = TrainingOrchestrator._balanced_split(make_items({0: 3, 1: 3}), 0.8, seed=1)
        assert sorted(lbl for _, lbl in val) == [0, 1]
        assert sorted(lbl for _, lbl in train) == [0, 0, 1, 1]


class TestClassAlignment:
    def test_predict_proba_spans_the_full_class_space(self):
        """A class missing from the training split must still get a column.

        Downstream code indexes probabilities positionally, so a narrower matrix
        silently attributes one class's probability to another.
        """
        model = TfidfLogisticRegressionClassifier(n_classes=3)
        # Class 1 never appears in training.
        model.train([("alpha text", 0)] * 5 + [("gamma text", 2)] * 5)

        probas = model.predict_proba(["alpha text", "gamma text"])
        assert probas.shape == (2, 3)
        assert np.allclose(probas[:, 1], 0.0)  # unseen class, never predicted
        assert np.allclose(probas.sum(axis=1), 1.0)
        # Column index is the global class id, so argmax returns a global id.
        assert model.predict(["alpha text", "gamma text"]) == [0, 2]

    @pytest.mark.parametrize("algorithm", sorted(AVAILABLE_MODELS))
    def test_every_algorithm_aligns_and_learns_at_al_scale(self, algorithm):
        """All four heads, on the ~20 labels the first rounds actually have.

        LightGBM's stock min_child_samples=20 refuses to split at that size and
        returns a constant probability, which also flattens uncertainty ranking to
        random sampling — hence the low-data defaults in _create_model.
        """
        a = ["alpha document about sepsis", "alpha note mentions sepsis again"]
        c = ["gamma unrelated cardiology text", "gamma another cardiology note"]
        data = [(t, 0) for t in a * 5] + [(t, 2) for t in c * 5]

        model = AVAILABLE_MODELS[algorithm](n_classes=3)
        model.train(data, fit_corpus=[t for t, _ in data] + ["beta never labelled"])

        probas = model.predict_proba([a[0], c[0]])
        assert probas.shape == (2, 3)
        assert np.allclose(probas[:, 1], 0.0)  # class 1 absent from training
        assert np.allclose(probas.sum(axis=1), 1.0)
        assert model.predict([a[0], c[0]]) == [0, 2]

    def test_vectorizer_can_be_fitted_on_a_wider_corpus(self):
        model = TfidfLogisticRegressionClassifier(n_classes=2)
        model.train(
            [("seen word", 0), ("other word", 1)],
            fit_corpus=["seen word", "other word", "unseen vocabulary term"],
        )
        assert "unseen" in model.embedding.vocabulary_


class TestConformalLowData:
    def _fit(self, n_cal: int, alpha: float = 0.1) -> ConformalPredictor:
        inner = TfidfLogisticRegressionClassifier(n_classes=2)
        train = make_items({0: 20, 1: 20})
        cal = [(f"{CLASS_WORDS[i % 2]} document filler number{i}", i % 2) for i in range(n_cal)]
        conformal = ConformalPredictor(model=inner, alpha=alpha, n_classes=2)
        conformal.train(train, cal)
        return conformal

    def test_threshold_stays_finite_with_few_calibration_samples(self):
        """alpha=0.1 needs 9 calibration points; below that the quantile hit BIG_N,
        every class entered every prediction set and the ranking went flat."""
        conformal = self._fit(n_cal=3)
        assert conformal.degenerate is True
        assert conformal.alpha_effective == pytest.approx(0.25)
        assert float(conformal.threshold) < BIG_N

    def test_uncertainty_is_not_constant_at_low_data(self):
        conformal = self._fit(n_cal=3)
        scores = conformal.predict_uncert(
            ["alpha document filler number1", "beta document filler number2", "unrelated wording"]
        )
        assert len(set(np.round(scores, 6))) > 1

    def test_alpha_is_untouched_when_calibration_is_ample(self):
        conformal = self._fit(n_cal=40)
        assert conformal.degenerate is False
        assert conformal.alpha_effective == pytest.approx(0.1)

    def test_uncertainty_is_the_mean_over_the_set_not_the_sum(self):
        """Eq. (4) of arXiv:2502.04372 averages over the prediction set.

        Summing makes a wider set score higher just for having more terms, which
        conflates set size with ambiguity on three-way labels.
        """

        class Stub:
            n_classes = 3

            def predict_proba(self, texts):
                return np.array([[0.2, 0.3, 0.5]])

        conformal = ConformalPredictor(model=Stub(), alpha=0.1, n_classes=3)
        conformal.threshold = 0.75  # scores are [0.8, 0.7, 0.5]; the 0.8 is excluded
        score = conformal.predict_uncert(["x"])[0]

        expected_mean = (0.7 + 0.5) / 2
        expected_sum = 0.7 + 0.5
        margin = 1e-3 * (1 - (0.5 - 0.3))
        assert score == pytest.approx(expected_mean + margin)
        assert score != pytest.approx(expected_sum + margin)

    def test_binary_labels_are_unaffected_by_the_normalisation(self):
        """With a threshold below 0.5 only one class can qualify, so mean == sum."""

        class Stub:
            n_classes = 2

            def predict_proba(self, texts):
                return np.array([[0.85, 0.15]])

        conformal = ConformalPredictor(model=Stub(), alpha=0.1, n_classes=2)
        conformal.threshold = 0.2
        margin = 1e-3 * (1 - (0.85 - 0.15))
        assert conformal.predict_uncert(["x"])[0] == pytest.approx(0.15 + margin)

    def test_empty_prediction_set_ranks_as_most_uncertain(self):
        """Nothing clearing the threshold means an anomalous entry, not a confident
        one — it used to sum to 0 and sort last."""

        class Stub:
            n_classes = 2

            def predict_proba(self, texts):
                # Row 0: confident. Row 1: nothing passes a tight threshold.
                return np.array([[0.99, 0.01], [0.5, 0.5]])

        conformal = ConformalPredictor(model=Stub(), alpha=0.1, n_classes=2)
        conformal.threshold = 0.05  # only a >=0.95 probability qualifies
        scores = conformal.predict_uncert(["a", "b"])
        assert scores[1] > scores[0]


class TestMetrics:
    def test_macro_f1_exposes_a_majority_class_predictor(self):
        """The case that ended runs early: 0.9 accuracy from a useless model."""
        labels = np.array([0] * 90 + [1] * 10)
        preds = np.zeros(100, dtype=int)

        assert balanced_accuracy(labels, preds, n_classes=2) == pytest.approx(0.5)
        assert macro_f1(labels, preds, n_classes=2) < 0.5
        assert f1(labels, preds, target=1) == 0.0

    def test_auc_returns_nan_not_zero_on_degenerate_input(self):
        """A hard 0 satisfied any "metric <= threshold" goal on round one."""
        labels = np.array([1, 1, 1])
        proba = np.array([[0.2, 0.8]] * 3)
        assert np.isnan(auc_roc(labels, np.array([1, 1, 1]), label_proba=proba))

    def test_bootstrap_withholds_an_interval_it_cannot_support(self):
        labels = np.array([1, 1])
        proba = np.array([[0.3, 0.7]] * 2)
        point, low, high, valid = bootstrap_metric(
            auc_roc, labels, np.array([1, 1]), label_proba=proba, n_iter=50
        )
        assert np.isnan(point)
        assert low is None and high is None
        assert valid == 0.0

    def test_bootstrap_reports_an_interval_when_it_can(self):
        rng = np.random.default_rng(0)
        labels = rng.integers(0, 2, size=200)
        preds = labels.copy()
        preds[:20] = 1 - preds[:20]
        point, low, high, valid = bootstrap_metric(
            balanced_accuracy, labels, preds, n_classes=2, n_iter=200
        )
        assert valid == 1.0
        assert low is not None and low < point < high


class TestCandidatePool:
    """Pool assembly for k-means, per the paper's selection procedure."""

    @staticmethod
    def ranked(n):
        # Descending uncertainty, so id 0 is the least certain and id n-1 the most.
        return [(i, 1.0 - i / n) for i in range(n)]

    def test_low_uncertainty_share_comes_from_the_certain_tail(self):
        pool, low_ids = TrainingOrchestrator._assemble_pool(self.ranked(1000), 100, 0.3)
        assert len(pool) == 100
        ids = [eid for eid, _ in pool]
        assert ids[:70] == list(range(70))  # 70% most uncertain
        assert set(ids[70:]) == set(range(970, 1000))  # 30% most certain
        assert low_ids == set(range(970, 1000))

    def test_the_papers_headline_30_70_split_is_expressible(self):
        """certain_rate used to be clamped at 0.5, excluding the configuration the
        paper reports its best results with."""
        pool, low_ids = TrainingOrchestrator._assemble_pool(self.ranked(1000), 100, 0.7)
        assert len(low_ids) == 70
        assert len(pool) == 100

    def test_zero_rate_is_pure_uncertainty_sampling(self):
        pool, low_ids = TrainingOrchestrator._assemble_pool(self.ranked(500), 50, 0.0)
        assert [eid for eid, _ in pool] == list(range(50))
        assert low_ids == set()

    def test_overlapping_ends_are_deduplicated(self):
        """A pool wider than the dataset makes the head and tail collide."""
        pool, low_ids = TrainingOrchestrator._assemble_pool(self.ranked(30), 100, 0.3)
        ids = [eid for eid, _ in pool]
        assert len(ids) == len(set(ids)) == 30
        # Everything was already reached from the uncertain head.
        assert low_ids == set()


class TestMacroBundle:
    """The confusion-matrix fast path must agree with the sklearn-backed metrics.

    _compute_metrics runs on every retrain with an annotator waiting, and the
    per-metric bootstrap over sklearn scorers cost ~10s a round; this replaced it.
    """

    @pytest.mark.parametrize("seed", range(5))
    @pytest.mark.parametrize("n_classes", [2, 3, 4])
    def test_matches_the_sklearn_implementations(self, seed, n_classes):
        from olim.ml.metrics import (
            accuracy,
            balanced_accuracy,
            macro_bundle,
            macro_f1,
            macro_precision,
            macro_recall,
        )

        rng = np.random.default_rng(seed)
        labels = rng.integers(0, n_classes, size=120)
        preds = np.where(rng.random(120) < 0.7, labels, rng.integers(0, n_classes, size=120))

        got = macro_bundle(labels, preds, n_classes)
        assert got["accuracy"] == pytest.approx(accuracy(labels, preds))
        assert got["macro_precision"] == pytest.approx(
            macro_precision(labels, preds, n_classes=n_classes)
        )
        assert got["macro_recall"] == pytest.approx(
            macro_recall(labels, preds, n_classes=n_classes)
        )
        assert got["macro_f1"] == pytest.approx(macro_f1(labels, preds, n_classes=n_classes))
        assert got["balanced_accuracy"] == pytest.approx(
            balanced_accuracy(labels, preds, n_classes=n_classes)
        )

    def test_handles_a_class_that_never_appears(self):
        from olim.ml.metrics import macro_bundle

        got = macro_bundle(np.array([0, 0, 1]), np.array([0, 0, 1]), n_classes=3)
        assert got["accuracy"] == pytest.approx(1.0)
        # Class 2 has no support and no predictions: scores 0, dragging the macro down.
        assert got["macro_recall"] == pytest.approx(2 / 3)

    def test_bootstrap_bundle_shares_resamples_across_metrics(self):
        from olim.ml.metrics import bootstrap_bundle, macro_bundle

        rng = np.random.default_rng(0)
        labels = rng.integers(0, 2, size=200)
        preds = labels.copy()
        preds[:30] = 1 - preds[:30]

        out = bootstrap_bundle(
            lambda lab, pr, proba: macro_bundle(lab, pr, 2), labels, preds, n_iter=200
        )
        assert set(out) == {
            "accuracy",
            "macro_precision",
            "macro_recall",
            "balanced_accuracy",
            "macro_f1",
        }
        for name, (point, low, high, valid) in out.items():
            assert valid == 1.0, name
            assert low < point < high, name


class TestSingleClassTrainingData:
    """Every label so far is the same answer — the normal early state of a rare-label
    campaign, and the one the paper reports needing most help with (2 positives in
    100). XGBoost and LogisticRegression both raise on it, which used to fail the
    whole training round and stall the loop.
    """

    @pytest.mark.parametrize("algorithm", sorted(AVAILABLE_MODELS))
    def test_training_survives_with_no_positives(self, algorithm):
        data = [(f"review number{i} about a product", 0) for i in range(40)]
        model = AVAILABLE_MODELS[algorithm](n_classes=2)
        model.train(data)

        probas = model.predict_proba(["another review", "and one more"])
        assert probas.shape == (2, 2)
        assert np.allclose(probas[:, 0], 1.0)  # constant: nothing to discriminate
        assert np.allclose(probas.sum(axis=1), 1.0)
        assert model.predict(["another review"]) == [0]

    @pytest.mark.parametrize("algorithm", sorted(AVAILABLE_MODELS))
    def test_conformal_and_ranking_survive_too(self, algorithm):
        data = [(f"review number{i} about a product", 0) for i in range(40)]
        conformal = ConformalPredictor(
            model=AVAILABLE_MODELS[algorithm](n_classes=2), alpha=0.1, n_classes=2
        )
        conformal.train(data[:32], data[32:])
        scores = conformal.predict_uncert(["a", "b", "c"])
        assert len(scores) == 3
        assert np.all(np.isfinite(scores))

    def test_the_minority_class_is_learned_once_it_appears(self):
        """The constant predictor must not stick around after a positive arrives."""
        model = AVAILABLE_MODELS["TfidfXGBoostClassifier"](n_classes=2)
        model.train([(f"boring review number{i}", 0) for i in range(20)])
        assert model._single_class == 0

        model.train(
            [(f"boring review number{i}", 0) for i in range(20)]
            + [(f"excellent splendid review number{i}", 1) for i in range(20)]
        )
        assert model._single_class is None
        assert model.predict(["excellent splendid review number99"]) == [1]


class TestClassValueResolution:
    """Class values come from the label's own configuration, not from the data.

    Reading them off whatever is in the database would let a typo or a stale value
    become a class; consulting the declaration also keeps a class nobody has
    annotated yet in the space, without which the encoder maps predictions onto the
    wrong class name.
    """

    @staticmethod
    def label(label_type, settings=None):
        return type("L", (), {"id": 1, "label_type": label_type, "label_settings": settings})()

    def test_preset_type_declares_its_own_classes(self):
        assert get_class_values(self.label("yes_no")) == ["no", "yes"]
        assert get_class_values(self.label("sim_nao")) == ["não", "sim"]

    def test_abstain_is_excluded_unless_asked_for(self):
        assert get_class_values(self.label("sim_nao_ns")) == ["não", "sim"]
        assert get_class_values(self.label("sim_nao_ns"), include_abstain=True) == [
            "não",
            "não sei",
            "sim",
        ]
        assert get_class_values(self.label("yes_no_unknown")) == ["no", "yes"]

    def test_multiple_choice_reads_its_configured_options(self):
        settings = {"options": [{"value": "red"}, {"value": "green"}, {"value": "blue"}]}
        assert get_class_values(self.label("multiple_choice", settings)) == [
            "blue",
            "green",
            "red",
        ]

    def test_only_configurable_types_are_open(self):
        assert is_open_label("multiple_choice") is True
        for fixed in ("yes_no", "sim_nao", "sim_nao_ns", "check", None):
            assert is_open_label(fixed) is False, fixed

    def test_unknown_type_declares_nothing(self):
        """A label with no usable type must not silently inherit sim_nao's classes —
        that is what made an English yes/no label train on zero of its 79
        annotations."""
        assert get_class_values(self.label(None)) == []
        assert get_class_values(self.label("not_a_real_type")) == []

    def test_ordering_is_sorted_and_single(self):
        """value_to_idx and the LabelEncoder both depend on this exact ordering."""
        values = get_class_values(
            self.label("multiple_choice", {"options": [{"value": "zebra"}, {"value": "apple"}]})
        )
        assert values == sorted(values) == ["apple", "zebra"]


class TestStoredValueDecoding:
    """LabelEntry.value holds two formats and readers must accept both.

    The manual UI serialises the selected options as a JSON array because
    multiple_choice is multi-select and every non-free-text type renders through it;
    the active learning loop, the legacy /al route and the LLM auto-labeller each
    write a plain scalar. Treating them as distinct gave a binary label four classes
    — '["yes"]', '["no"]', 'yes', 'no' — split by whichever screen recorded it.
    """

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ('["yes"]', ["yes"]),  # manual UI
            ("yes", ["yes"]),  # active learning / LLM
            ('["não sei"]', ["não sei"]),
            ("não sei", ["não sei"]),
            ('["a", "b"]', ["a", "b"]),  # genuine multi-select
            ("[]", []),  # cleared
            (None, []),
            ("5", ["5"]),  # valid JSON, but still just the value written
            ("true", ["true"]),
            ('{"not": "a list"}', ['{"not": "a list"}']),
        ],
    )
    def test_both_storage_formats_decode_to_the_same_classes(self, raw, expected):
        assert parse_label_value(raw) == expected

    def test_the_two_writers_agree(self):
        """The point of the whole exercise: one answer, one class."""
        assert parse_label_value('["yes"]') == parse_label_value("yes")
        assert parse_label_value('["no"]') == parse_label_value("no")
