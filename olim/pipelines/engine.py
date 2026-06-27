from collections.abc import Iterable

from olim.pipelines.base import BlockKind, BlockType, PipelineCapability
from olim.pipelines.catalog import all_kinds, kind_for

_TEXT_SEED: frozenset[PipelineCapability] = frozenset({
    "raw_text",
    "clean_text",
    "labels",
})


def seed_capabilities() -> frozenset[PipelineCapability]:
    """The capabilities available before any block, from the dataset + scheme.
    Today only text datasets exist; extend by data_type when others land."""
    return _TEXT_SEED


def available_after(block_types: Iterable[BlockType]) -> frozenset[PipelineCapability]:
    """Fold the placed blocks into the set of currently-available capabilities.
    Monotonic union — a block only ever adds; nothing is consumed away."""
    available = set(seed_capabilities())
    for block_type in block_types:
        available |= kind_for(block_type).produces
    return frozenset(available)


def is_applicable(kind: BlockKind, available: frozenset[PipelineCapability]) -> bool:
    return kind.consumes <= available


def candidates(available: frozenset[PipelineCapability]) -> list[BlockKind]:
    """The catalog blocks whose inputs are all available now. On an empty
    pipeline (available == seed) these are the valid starters."""
    return [k for k in all_kinds() if is_applicable(k, available)]
