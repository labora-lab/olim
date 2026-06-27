from typing import TYPE_CHECKING, Literal

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from olim.models.base import Base

if TYPE_CHECKING:
    from olim.models.labeling import Annotation, LabelScheme

DataType = Literal["text"]


class Dataset(Base):
    __tablename__ = "datasets"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    data_type: Mapped[DataType] = mapped_column(default="text")

    items: Mapped[list[Item]] = relationship(back_populates="dataset")
    schemes: Mapped[list[LabelScheme]] = relationship(back_populates="dataset")


class Item(Base):
    __tablename__ = "items"

    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id"))
    content: Mapped[str]

    dataset: Mapped[Dataset] = relationship(back_populates="items")
    annotations: Mapped[list[Annotation]] = relationship(back_populates="item")
