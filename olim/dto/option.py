from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class OptionDTO:
    id: int
    field_id: int
    name: str


@dataclass(frozen=True, slots=True)
class OptionCreate:
    field_id: int
    name: str
