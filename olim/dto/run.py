from dataclasses import dataclass, field
from datetime import datetime

from olim.models import RunStatus
from olim.pipelines import BlockType


@dataclass(frozen=True, slots=True)
class BlockRunDTO:
    id: int
    run_id: int
    type: BlockType
    position: int
    config: dict
    status: RunStatus
    artifact_ref: str | None
    metrics: dict | None
    error: str | None


@dataclass(frozen=True, slots=True)
class PipelineRunDTO:
    id: int
    pipeline_id: int
    status: RunStatus
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    blocks: list[BlockRunDTO] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class PipelineRunCreate:
    pipeline_id: int
