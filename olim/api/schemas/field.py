from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class OptionIn(BaseModel):
    name: str


class _FieldInBase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str


class SelectFieldIn(_FieldInBase):
    type: Literal["select"]
    multi: bool = False
    allow_other: bool = False
    options: list[OptionIn] = []


class NumericFieldIn(_FieldInBase):
    type: Literal["numeric"]
    min: float | None = None
    max: float | None = None
    step: float | None = None


class TextFieldIn(_FieldInBase):
    type: Literal["text"]


class BooleanFieldIn(_FieldInBase):
    type: Literal["boolean"]
    nullable: bool = False


FieldIn = Annotated[
    SelectFieldIn | NumericFieldIn | TextFieldIn | BooleanFieldIn,
    Field(discriminator="type"),
]
