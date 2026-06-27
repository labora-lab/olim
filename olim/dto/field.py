from dataclasses import dataclass, field

from olim.dto.option import OptionDTO
from olim.models import FieldType


@dataclass(frozen=True, slots=True)
class FieldDTO:
    id: int
    scheme_id: int
    name: str
    type: FieldType
    min: float | None
    max: float | None
    step: float | None
    multi: bool
    allow_other: bool
    nullable: bool
    options: list[OptionDTO] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class FieldCreate:
    scheme_id: int
    name: str
    type: FieldType
    min: float | None = None
    max: float | None = None
    step: float | None = None
    multi: bool = False
    allow_other: bool = False
    nullable: bool = False


@dataclass(frozen=True, slots=True)
class FieldSpec:
    """A field plus its option names, for creating a scheme in one shot.
    scheme_id is filled in by the repository once the scheme exists."""

    name: str
    type: FieldType
    min: float | None = None
    max: float | None = None
    step: float | None = None
    multi: bool = False
    allow_other: bool = False
    nullable: bool = False
    options: list[str] = field(default_factory=list)
