import pickle  # noqa: S403  artifacts are worker-written, never untrusted input
from abc import ABC, abstractmethod
from dataclasses import dataclass

from olim.pipelines.artifacts import ArtifactStore
from olim.pipelines.data import DataBundle


@dataclass(frozen=True, slots=True)
class BlockContext:
    """What a runner needs to execute one block: its config, the prior block's
    artifact ref (None at position 0), the store, where it sits in the run, and
    the labeled training data (loaded once by the task)."""

    config: dict
    upstream_ref: str | None
    store: ArtifactStore
    run_id: int
    position: int
    data: DataBundle | None = None


@dataclass(frozen=True, slots=True)
class RunResult:
    """What a block produced: a ref to its (heavy) artifact on disk, and small
    structured results that land in the DB on BlockRun.metrics."""

    artifact_ref: str | None
    metrics: dict | None


class BlockRunner(ABC):
    """One block's real execution. Subclass per block type and implement `run`;
    the registry maps a BlockType to an instance. The accumulator dict is read
    from the upstream artifact, grown, and written back via `load`/`save`."""

    @abstractmethod
    def run(self, ctx: BlockContext) -> RunResult: ...

    def load(self, ctx: BlockContext) -> dict:
        """The accumulator from the prior block, or a fresh one at position 0."""
        if ctx.upstream_ref is None:
            if ctx.position > 0:
                # the prior block produced no artifact (e.g. an eval block) but
                # this one needs the accumulator: a None ref past position 0 is a
                # broken chain, not a fresh start. Fail loudly, don't reset to {}.
                raise ValueError(
                    f"block at position {ctx.position} has no upstream accumulator;"
                    " the previous block produced no artifact"
                )
            return {}
        return pickle.loads(ctx.store.get(ctx.upstream_ref))  # noqa: S301  trusted

    def save(self, ctx: BlockContext, acc: dict) -> str:
        return ctx.store.put(ctx.run_id, ctx.position, pickle.dumps(acc))
