from olim.pipelines.base import BlockType
from olim.pipelines.runners.base import BlockRunner
from olim.pipelines.runners.eval import ClassificationMetricsRunner
from olim.pipelines.runners.model import LogRegRunner
from olim.pipelines.runners.split import TrainTestSplitRunner
from olim.pipelines.runners.vectorize import TfidfRunner


class NoRunnerError(Exception):
    """The block type has no real runner yet (not implemented)."""


# Only implemented blocks are registered. A block without an entry isn't
# executable yet — runner_for raises, the task marks the block failed, the run
# stops there. Add a block = implement its runner and register it here.
_RUNNERS: dict[BlockType, BlockRunner] = {
    "tfidf": TfidfRunner(),
    "train_test_split": TrainTestSplitRunner(),
    "logreg": LogRegRunner(),
    "classification_metrics": ClassificationMetricsRunner(),
}


def runner_for(block_type: BlockType) -> BlockRunner:
    runner = _RUNNERS.get(block_type)
    if runner is None:
        raise NoRunnerError(f"block {block_type!r} is not executable yet")
    return runner


def is_runnable(block_type: BlockType) -> bool:
    """Whether a real runner exists for this block type. The API uses this to
    reject building a pipeline that could never execute."""
    return block_type in _RUNNERS
