from dataclasses import dataclass, field

from olim.pipelines import BlockType


@dataclass(frozen=True, slots=True)
class PipelineBlockDTO:
    id: int
    pipeline_id: int
    type: BlockType
    position: int
    config: dict


@dataclass(frozen=True, slots=True)
class PipelineDTO:
    id: int
    dataset_id: int
    scheme_id: int
    name: str
    blocks: list[PipelineBlockDTO] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class PipelineCreate:
    dataset_id: int
    scheme_id: int
    name: str


@dataclass(frozen=True, slots=True)
class PipelineBlockSpec:
    type: BlockType
    config: dict
