"""Unit tests for the real ML runners. No broker, no DB, no Celery: a DataBundle
is built by hand, a LocalArtifactStore writes to a tmp dir, and the four runners
are chained manually (each RunResult.artifact_ref becomes the next upstream_ref).
This exercises the whole accumulator data contract in one test."""

import pickle  # noqa: S403  round-trips worker-written artifacts in tests

from olim.pipelines import BlockContext, DataBundle, LocalArtifactStore, runner_for


def _bundle():
    # 20 rows, 2 separable classes: class 0 says "good", class 1 says "bad".
    texts = [("good " * 3) if i % 2 == 0 else ("bad " * 3) for i in range(20)]
    labels = [i % 2 for i in range(20)]
    return DataBundle(
        item_ids=list(range(1, 21)),
        texts=texts,
        labels=labels,
        classes=[10, 20],  # class idx -> option_id
        n_classes=2,
    )


def _ctx(store, position, upstream_ref, bundle, config=None):
    return BlockContext(
        config=config or {},
        upstream_ref=upstream_ref,
        store=store,
        run_id=1,
        position=position,
        data=bundle,
    )


def _metrics(result) -> dict:
    assert result.metrics is not None
    return result.metrics


def _ref(result) -> str:
    assert result.artifact_ref is not None
    return result.artifact_ref


def test_four_block_path_trains_and_scores(tmp_path):
    store = LocalArtifactStore(tmp_path)
    bundle = _bundle()

    tfidf = runner_for("tfidf").run(_ctx(store, 0, None, bundle))
    assert _metrics(tfidf)["n_samples"] == 20
    assert _metrics(tfidf)["n_features"] > 0

    split = runner_for("train_test_split").run(
        _ctx(store, 1, _ref(tfidf), bundle, {"test_size": 0.25})
    )
    assert _metrics(split)["n_train"] + _metrics(split)["n_test"] == 20

    logreg = runner_for("logreg").run(_ctx(store, 2, _ref(split), bundle))
    assert _metrics(logreg)["n_train"] == _metrics(split)["n_train"]

    result = runner_for("classification_metrics").run(
        _ctx(store, 3, _ref(logreg), bundle)
    )
    assert result.artifact_ref is None  # eval produces no heavy artifact
    m = _metrics(result)
    assert 0.0 <= m["accuracy"] <= 1.0
    assert 0.0 <= m["f1_macro"] <= 1.0
    # the two classes are trivially separable, so the model should be ~perfect
    assert m["accuracy"] >= 0.99


def test_accumulator_carries_model_and_vectorizer(tmp_path):
    store = LocalArtifactStore(tmp_path)
    bundle = _bundle()
    a = runner_for("tfidf").run(_ctx(store, 0, None, bundle))
    b = runner_for("train_test_split").run(_ctx(store, 1, _ref(a), bundle))
    c = runner_for("logreg").run(_ctx(store, 2, _ref(b), bundle))

    acc = pickle.loads(store.get(_ref(c)))  # noqa: S301  trusted test data
    expected_keys = {
        "item_ids",
        "labels",
        "features",
        "vectorizer",
        "train_idx",
        "model",
    }
    assert expected_keys <= acc.keys()
    assert acc["item_ids"] == bundle.item_ids
