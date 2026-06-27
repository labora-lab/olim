from datetime import datetime  # noqa: TC003 SQLAlchemy resolve Mapped[] em runtime
from typing import TYPE_CHECKING, Literal

from sqlalchemy import ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base

if TYPE_CHECKING:
    from .dataset import Dataset, Item

LabelMode = Literal["single", "multi"]
AnnotationSource = Literal["human", "llm"]


class LabelScheme(Base):
    __tablename__ = "label_schemes"

    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id"))
    name: Mapped[str]
    label_mode: Mapped[LabelMode] = mapped_column(String, default="single")
    allow_extra_label: Mapped[bool] = mapped_column(default=False)

    dataset: Mapped[Dataset] = relationship(back_populates="schemes")
    labels: Mapped[list[Label]] = relationship(back_populates="scheme")
    annotations: Mapped[list[Annotation]] = relationship(back_populates="scheme")


class Label(Base):
    __tablename__ = "labels"

    id: Mapped[int] = mapped_column(primary_key=True)
    scheme_id: Mapped[int] = mapped_column(ForeignKey("label_schemes.id"))
    name: Mapped[str]

    scheme: Mapped[LabelScheme] = relationship(back_populates="labels")


class Annotation(Base):
    __tablename__ = "annotations"

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"))
    scheme_id: Mapped[int] = mapped_column(ForeignKey("label_schemes.id"))
    label_id: Mapped[int | None] = mapped_column(ForeignKey("labels.id"))
    extra_label: Mapped[str | None]
    source: Mapped[AnnotationSource] = mapped_column(String, default="human")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    item: Mapped[Item] = relationship(back_populates="annotations")
    scheme: Mapped[LabelScheme] = relationship(back_populates="annotations")
