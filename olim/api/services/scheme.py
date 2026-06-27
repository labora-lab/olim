from sqlalchemy.orm import Session

from olim.api.exceptions import DatasetNotFoundError, SchemeNotFoundError
from olim.api.schemas.scheme import SchemeCreateIn
from olim.dto import SchemeCreate, SchemeDTO
from olim.dto.field import FieldSpec
from olim.repositories import DatasetRepository, SchemeRepository

_list = list


class SchemeService:
    def __init__(self, session: Session) -> None:
        self.repo = SchemeRepository(session)
        self.datasets = DatasetRepository(session)

    def create(self, dataset_id: int, data: SchemeCreateIn) -> SchemeDTO:
        if not self.datasets.exists(dataset_id):
            raise DatasetNotFoundError(dataset_id)
        specs = [
            FieldSpec(
                **f.model_dump(exclude={"options"}),
                options=[o.name for o in getattr(f, "options", [])],
            )
            for f in data.fields
        ]
        scheme_id = self.repo.create_tree(
            SchemeCreate(dataset_id=dataset_id, name=data.name), specs, commit=True
        )
        return self.get(scheme_id)

    def get(self, scheme_id: int) -> SchemeDTO:
        scheme = self.repo.get(scheme_id)
        if scheme is None:
            raise SchemeNotFoundError(scheme_id)
        return scheme

    def list(self, dataset_id: int) -> _list[SchemeDTO]:
        return self.repo.list_by_dataset(dataset_id)
