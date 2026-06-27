from dataclasses import dataclass

from olim.models import AnnotationSource


@dataclass(frozen=True, slots=True)
class AnnotationDTO:
    id: int
    item_id: int
    field_id: int
    source: AnnotationSource
    # the single saved value, whichever column the field's type uses (an option
    # id, a number, a string, or a bool). Multi-select yields one row per option.
    value: int | float | str | bool | None


@dataclass(frozen=True, slots=True)
class AnnotationCreate:
    item_id: int
    field_id: int
    source: AnnotationSource = "human"
    option_id: int | None = None
    value_num: float | None = None
    value_text: str | None = None
    value_bool: bool | None = None
