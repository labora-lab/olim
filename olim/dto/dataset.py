from dataclasses import dataclass

from olim.models import DataType


@dataclass(frozen=True, slots=True)
class DatasetDTO:
    id: int
    name: str
    data_type: DataType


@dataclass(frozen=True, slots=True)
class DatasetCreate:
    name: str
    data_type: DataType = "text"
