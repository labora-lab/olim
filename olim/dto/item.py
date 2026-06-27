from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ItemDTO:
    id: int
    dataset_id: int
    content: str


@dataclass(frozen=True, slots=True)
class ItemCreate:
    dataset_id: int
    content: str
