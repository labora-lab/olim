from dataclasses import dataclass, field

from olim.dto.field import FieldDTO


@dataclass(frozen=True, slots=True)
class SchemeDTO:
    id: int
    dataset_id: int
    name: str
    fields: list[FieldDTO] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class SchemeCreate:
    dataset_id: int
    name: str
