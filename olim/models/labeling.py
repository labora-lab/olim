from datetime import datetime
from typing import TYPE_CHECKING, Literal

from sqlalchemy import ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from olim.models.base import Base

if TYPE_CHECKING:
    from olim.models.dataset import Dataset, Item

FieldType = Literal["select", "numeric", "text", "boolean"]
AnnotationSource = Literal["human", "llm"]


class Scheme(Base):
    """A labeling job over a dataset; groups the fields to be answered."""

    __tablename__ = "schemes"

    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id"))
    name: Mapped[str]

    dataset: Mapped[Dataset] = relationship(back_populates="schemes")
    fields: Mapped[list[Field]] = relationship(back_populates="scheme")


class Field(Base):
    """A single question within a scheme. Its `type` decides which config
    columns and which annotation value column apply."""

    __tablename__ = "fields"

    id: Mapped[int] = mapped_column(primary_key=True)
    scheme_id: Mapped[int] = mapped_column(ForeignKey("schemes.id"))
    name: Mapped[str]
    type: Mapped[FieldType] = mapped_column(String)

    # numeric config
    min: Mapped[float | None]
    max: Mapped[float | None]
    step: Mapped[float | None]
    # select config
    multi: Mapped[bool] = mapped_column(default=False)
    allow_other: Mapped[bool] = mapped_column(default=False)
    # boolean config
    nullable: Mapped[bool] = mapped_column(default=False)

    scheme: Mapped[Scheme] = relationship(back_populates="fields")
    options: Mapped[list[Option]] = relationship(back_populates="field")
    annotations: Mapped[list[Annotation]] = relationship(back_populates="field")


class Option(Base):
    """A choice belonging to a `select` field."""

    __tablename__ = "options"

    id: Mapped[int] = mapped_column(primary_key=True)
    field_id: Mapped[int] = mapped_column(ForeignKey("fields.id"))
    name: Mapped[str]

    field: Mapped[Field] = relationship(back_populates="options")


class Annotation(Base):
    """An annotator's answer to one field for one item. The value lives in the
    column matching the field's type."""

    __tablename__ = "annotations"
    __table_args__ = (UniqueConstraint("item_id", "field_id", "source", "option_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"))
    field_id: Mapped[int] = mapped_column(ForeignKey("fields.id"))
    source: Mapped[AnnotationSource] = mapped_column(String, default="human")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    option_id: Mapped[int | None] = mapped_column(ForeignKey("options.id"))
    value_num: Mapped[float | None]
    value_text: Mapped[str | None]
    value_bool: Mapped[bool | None]

    item: Mapped[Item] = relationship(back_populates="annotations")
    field: Mapped[Field] = relationship(back_populates="annotations")
