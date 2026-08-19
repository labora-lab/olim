"""Assert the structural claims of arXiv:2502.04372 against the current code.

Absolute numbers are not comparable (see README.md) — these check the relationships
the paper reports, which is what survives the change of labelling oracle.
"""

import numpy as np
import pytest

from .harness import repeat, run_active_learning, summarise


class TestMixedUncertainty:
    """Paper: a 50/50 or 70/30 high/low mix lifted Pet product AUC from 0.79 to 0.95.

    This is the behaviour the pool assembly was realigned to — low-uncertainty points
    now enter the candidate pool before clustering, as the paper specifies.
    """

    @pytest.fixture(scope="class")
    def runs(self, corpus):
        common = {"corpus": corpus, "label": "pet_product", "budget": 150, "seed_labels": 20}
        return {
            "high_only": repeat(2, certain_rate=0.0, **common),
            "mixed": repeat(2, certain_rate=0.3, **common),
        }

    def test_mixing_does_not_hurt_auc(self, runs):
        high = summarise(runs["high_only"])["auc_roc"][0]
        mixed = summarise(runs["mixed"])["auc_roc"][0]
        assert mixed >= high - 0.05, f"mixed {mixed:.3f} vs high-only {high:.3f}"

    def test_mixing_surfaces_at_least_as_many_positives(self, runs):
        high = summarise(runs["high_only"])["positives"][0]
        mixed = summarise(runs["mixed"])["positives"][0]
        assert mixed >= high * 0.8, f"mixed {mixed:.0f} vs high-only {high:.0f}"


class TestActiveVersusRandom:
    """Paper: active ≈ random on common labels, but far ahead on rare ones."""

    def test_rare_label_finds_more_positives_than_random(self, corpus):
        common = {"corpus": corpus, "label": "damaged", "budget": 150, "seed_labels": 20}
        active = summarise(repeat(2, strategy="active", certain_rate=0.3, **common))
        random = summarise(repeat(2, strategy="random", **common))
        assert active["positives"][0] > random["positives"][0], (
            f"active {active['positives'][0]:.0f} vs random {random['positives'][0]:.0f}"
        )

    def test_common_label_is_competitive_with_random(self, corpus):
        common = {"corpus": corpus, "label": "pet_product", "budget": 150, "seed_labels": 20}
        active = summarise(repeat(2, strategy="active", certain_rate=0.3, **common))
        random = summarise(repeat(2, strategy="random", **common))
        assert active["auc_roc"][0] >= random["auc_roc"][0] - 0.10


class TestSeedingRareLabels:
    """Paper: 40 pre-labelled texts took Damaged from AUC 0.50 to 0.88."""

    def test_seed_positives_improve_a_rare_label(self, corpus):
        common = {"corpus": corpus, "label": "damaged", "budget": 150, "certain_rate": 0.3}
        cold = summarise(repeat(2, seed_labels=20, **common))
        seeded = summarise(repeat(2, seed_labels=40, seed_positives=20, **common))
        assert seeded["positives"][0] > cold["positives"][0]
        assert np.isfinite(seeded["auc_roc"][0])


class TestLabelEfficiency:
    """Paper: usable models from 100-200 manual labels."""

    @pytest.mark.parametrize("label", ["pet_product", "low_quality"])
    def test_beats_chance_within_the_papers_budget(self, corpus, label):
        result = run_active_learning(
            corpus, label, budget=200, seed_labels=20, certain_rate=0.3, seed=0
        )
        assert result.auc_roc > 0.60, f"{label}: AUC {result.auc_roc:.3f} at 200 labels"

    def test_auc_improves_over_the_campaign(self, corpus):
        result = run_active_learning(
            corpus, "pet_product", budget=200, seed_labels=20, certain_rate=0.3, seed=0
        )
        early = result.history[0]["test_auc_roc"]
        late = result.history[-1]["test_auc_roc"]
        assert late > early, f"AUC went {early:.3f} -> {late:.3f}"
