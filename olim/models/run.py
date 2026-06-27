from datetime import datetime
from typing import TYPE_CHECKING, Literal

from sqlalchemy import ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from olim.models.base import Base
from olim.pipelines import BlockType

if TYPE_CHECKING:
    from olim.models.pipeline import Pipeline

RunStatus = Literal["pending", "running", "succeeded", "failed"]


class PipelineRun(Base):
    """One execution of a pipeline. Its blocks are snapshots of what actually
    ran, so editing the pipeline later never rewrites run history."""

    __tablename__ = "pipeline_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    pipeline_id: Mapped[int] = mapped_column(ForeignKey("pipelines.id"))
    status: Mapped[RunStatus] = mapped_column(String, default="pending")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]

    pipeline: Mapped[Pipeline] = relationship()
    blocks: Mapped[list[BlockRun]] = relationship(
        back_populates="run", order_by="BlockRun.position"
    )


class BlockRun(Base):
    """One block's execution within a run. `type`/`position`/`config` are
    snapshotted from the PipelineBlock at run creation (no FK to it). Small
    results live in `metrics`; heavy artifacts live on disk at `artifact_ref`."""

    __tablename__ = "block_runs"
    __table_args__ = (UniqueConstraint("run_id", "position"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("pipeline_runs.id"))
    type: Mapped[BlockType] = mapped_column(String)
    position: Mapped[int]
    config: Mapped[dict] = mapped_column(JSONB, default=dict)

    status: Mapped[RunStatus] = mapped_column(String, default="pending")
    artifact_ref: Mapped[str | None]
    metrics: Mapped[dict | None] = mapped_column(JSONB)
    error: Mapped[str | None]
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]

    run: Mapped[PipelineRun] = relationship(back_populates="blocks")
