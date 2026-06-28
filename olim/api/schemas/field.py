from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


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

    @model_validator(mode="after")
    def _require_options(self) -> SelectFieldIn:
        # a select with no fixed options is only usable if it accepts free text.
        if not self.options and not self.allow_other:
            raise ValueError("a select field needs at least one option")
        return self


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
