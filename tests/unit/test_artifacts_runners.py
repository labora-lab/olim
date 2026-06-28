"""Unit tests for the artifact store, the runner registry, and the run-service
queue routing. No broker, no database."""

from pathlib import Path

import pytest

from olim.api.services.run import _queue_for
from olim.pipelines import LocalArtifactStore, runner_for
from olim.pipelines.runners import NoRunnerError


def test_local_store_roundtrips_bytes(tmp_path: Path):
    store = LocalArtifactStore(tmp_path)
    ref = store.put(run_id=7, position=2, payload=b"hello")
    assert ref == "runs/7/2.pkl"
    assert store.get(ref) == b"hello"
    assert (tmp_path / ref).exists()


def test_runner_for_implemented_block_returns_a_runner():
    assert runner_for("tfidf") is not None


def test_runner_for_unimplemented_block_raises():
    # the 8 not-yet-real blocks have no runner; the task turns this into a
    # failed block run rather than a silent stub.
    with pytest.raises(NoRunnerError):
        runner_for("lowercase")


def test_queue_routing_sends_compute_to_heavy():
    assert _queue_for("logreg") == "heavy"  # model category
    assert _queue_for("train_test_split") == "heavy"  # split category
    assert _queue_for("tfidf") == "light"  # vectorize
    assert _queue_for("lowercase") == "light"  # clean
    assert _queue_for("pickle_artifact") == "light"  # store
