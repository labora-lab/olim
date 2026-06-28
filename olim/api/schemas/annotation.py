from typing import Annotated, Any

from pydantic import BaseModel, Field


class AnswerIn(BaseModel):
    # One answer for one field. `value` is interpreted by the field's type:
    #   select  -> an option id, or a list of ids (or free text if allow_other)
    #   numeric -> a number
    #   text    -> a string
    #   boolean -> true/false (or null if nullable)
    field_id: int
    value: Any = None


class AnnotateIn(BaseModel):
    # A batch of answers for one item. May be partial (some fields) or a single
    # answer (a one-element list) — same path either way, but never empty.
    answers: Annotated[list[AnswerIn], Field(min_length=1)]
