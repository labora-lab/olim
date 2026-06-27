"""Unit tests for the execution domain (olim/pipelines artifacts + runners) and
the queue routing in the run service. No broker, no database — the store writes
to a tmp dir and the stub runner is pure logic."""

import pickle  # noqa: S403  round-trips worker-written artifacts in tests
from pathlib import Path
from typing import get_args

from olim.api.services.run import _queue_for
from olim.pipelines import BlockContext, LocalArtifactStore, runner_for
from olim.pipelines.base import BlockType


def test_local_store_roundtrips_bytes(tmp_path: Path):
    store = LocalArtifactStore(tmp_path)
    ref = store.put(run_id=7, position=2, payload=b"hello")
    assert ref == "runs/7/2.pkl"
    assert store.get(ref) == b"hello"
    assert (tmp_path / ref).exists()


def test_stub_runner_writes_artifact_and_reads_upstream(tmp_path: Path):
    store = LocalArtifactStore(tmp_path)
    # an upstream artifact the next block must be able to read
    upstream = store.put(1, 0, pickle.dumps({"prev": True}))

    ctx = BlockContext(
        config={"k": "v"}, upstream_ref=upstream, store=store, run_id=1, position=1
    )
    result = runner_for("tfidf").run(ctx)

    assert result.artifact_ref == "runs/1/1.pkl"
    assert result.metrics == {"stub": True}
    loaded = pickle.loads(store.get(result.artifact_ref))  # noqa: S301  trusted test data
    assert loaded["config"] == {"k": "v"}


def test_every_block_type_has_a_runner():
    for block_type in get_args(BlockType):
        assert runner_for(block_type) is not None


def test_queue_routing_sends_compute_to_heavy():
    assert _queue_for("logreg") == "heavy"  # model category
    assert _queue_for("train_test_split") == "heavy"  # split category
    assert _queue_for("tfidf") == "light"  # vectorize
    assert _queue_for("lowercase") == "light"  # clean
    assert _queue_for("pickle_artifact") == "light"  # store
