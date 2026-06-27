from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from olim.models.base import Base
from olim.pipelines import BlockType

if TYPE_CHECKING:
    from olim.models.dataset import Dataset
    from olim.models.labeling import Scheme


class Pipeline(Base):
    """A training recipe over a labeled dataset: an ordered list of blocks the
    user composes."""

    __tablename__ = "pipelines"

    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id"))
    scheme_id: Mapped[int] = mapped_column(ForeignKey("schemes.id"))
    name: Mapped[str]

    dataset: Mapped[Dataset] = relationship()
    scheme: Mapped[Scheme] = relationship()
    blocks: Mapped[list[PipelineBlock]] = relationship(
        back_populates="pipeline", order_by="PipelineBlock.position"
    )


class PipelineBlock(Base):
    """One step in a pipeline. `type` picks the block from the catalog; `config`
    is its heterogeneous, per-type settings — opaque to the DB, never queried, so
    it lives in JSONB rather than typed columns (unlike Annotation values)."""

    __tablename__ = "pipeline_blocks"
    __table_args__ = (UniqueConstraint("pipeline_id", "position"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    pipeline_id: Mapped[int] = mapped_column(ForeignKey("pipelines.id"))
    type: Mapped[BlockType] = mapped_column(String)
    position: Mapped[int]
    config: Mapped[dict] = mapped_column(JSONB, default=dict)

    pipeline: Mapped[Pipeline] = relationship(back_populates="blocks")
