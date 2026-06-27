from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LabelDTO:
    id: int
    scheme_id: int
    name: str


@dataclass(frozen=True, slots=True)
class LabelCreate:
    scheme_id: int
    name: str
