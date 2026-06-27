"""
Unit tests for the pipeline "what fits next" engine (olim/pipelines).

Pure logic: the available-set is the seed unioned with each placed block's
`produces`; a candidate fits iff its `consumes` is a subset. No database.
"""

from olim.pipelines import (
    available_after,
    candidates,
    is_applicable,
    kind_for,
    seed_capabilities,
)


def candidate_types(block_types):
    return {k.type for k in candidates(available_after(block_types))}


def test_seed_starts_with_clean_and_vectorize():
    # An empty pipeline: only blocks consuming the seed (raw_text/clean_text).
    starters = candidate_types([])
    assert "lowercase" in starters  # consumes raw_text
    assert "tfidf" in starters  # consumes clean_text
    # A model needs a split; a split needs features — neither is available yet.
    assert "logreg" not in starters
    assert "train_test_split" not in starters


def test_split_unlocks_after_features():
    after_tfidf = candidate_types(["tfidf"])
    assert "train_test_split" in after_tfidf
    assert "train_calib_test_split" in after_tfidf
    assert "logreg" not in after_tfidf  # still no split placed


def test_model_unlocks_after_split():
    assert "logreg" in candidate_types(["tfidf", "train_test_split"])


def test_conformal_needs_a_calibration_split():
    # A plain 2-way split + model does NOT make conformal applicable.
    two_way = available_after(["tfidf", "train_test_split", "logreg"])
    assert not is_applicable(kind_for("conformal"), two_way)
    # The 3-way split produces `calibration`, which conformal requires.
    three_way = available_after(["tfidf", "train_calib_test_split", "logreg"])
    assert is_applicable(kind_for("conformal"), three_way)


def test_available_is_monotonic_union():
    # Placing blocks only ever adds capabilities; the seed is never lost.
    available = available_after(["lowercase", "tfidf", "train_test_split"])
    assert seed_capabilities() <= available
    assert {"features", "split"} <= available
