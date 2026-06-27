import pickle  # noqa: S403  artifacts are worker-written, never untrusted input
from dataclasses import dataclass
from typing import Protocol, get_args

from olim.pipelines.artifacts import ArtifactStore
from olim.pipelines.base import BlockType


@dataclass(frozen=True, slots=True)
class BlockContext:
    """What a runner needs to execute one block: its config, the prior block's
    artifact ref (None at position 0), the store, and where it sits in the run."""

    config: dict
    upstream_ref: str | None
    store: ArtifactStore
    run_id: int
    position: int


@dataclass(frozen=True, slots=True)
class RunResult:
    """What a block produced: a ref to its (heavy) artifact on disk, and small
    structured results that land in the DB on BlockRun.metrics."""

    artifact_ref: str | None
    metrics: dict | None


class BlockRunner(Protocol):
    def run(self, ctx: BlockContext) -> RunResult: ...


class StubRunner:
    """Placeholder runner for the scaffold: reads the upstream artifact to prove
    the chain links, writes a placeholder pickle, and reports a stub metric.
    Real runners replace this one BlockType at a time in `_RUNNERS`."""

    def run(self, ctx: BlockContext) -> RunResult:
        if ctx.upstream_ref is not None:
            ctx.store.get(ctx.upstream_ref)  # prove the prior artifact is reachable
        payload = pickle.dumps({"stub": ctx.position, "config": ctx.config})
        ref = ctx.store.put(ctx.run_id, ctx.position, payload)
        return RunResult(artifact_ref=ref, metrics={"stub": True})


# Every block runs as a stub for now. Swap a key for a real runner later.
_RUNNERS: dict[BlockType, BlockRunner] = {t: StubRunner() for t in get_args(BlockType)}


def runner_for(block_type: BlockType) -> BlockRunner:
    return _RUNNERS[block_type]
