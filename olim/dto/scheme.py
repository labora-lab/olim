from dataclasses import dataclass

from olim.models import LabelMode


@dataclass(frozen=True, slots=True)
class SchemeDTO:
    id: int
    dataset_id: int
    name: str
    label_mode: LabelMode
    allow_extra_label: bool


@dataclass(frozen=True, slots=True)
class SchemeCreate:
    dataset_id: int
    name: str
    label_mode: LabelMode = "single"
    allow_extra_label: bool = False
