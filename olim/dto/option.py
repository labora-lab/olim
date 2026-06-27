from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class OptionDTO:
    id: int
    field_id: int
    name: str
