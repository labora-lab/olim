from sqlalchemy.orm import Session

from olim.api.exceptions import DatasetNotFoundError, SchemeNotFoundError
from olim.api.schemas.scheme import LabelCreateIn, SchemeCreateIn
from olim.dto import LabelCreate, LabelDTO, SchemeCreate, SchemeDTO
from olim.repositories import DatasetRepository, LabelRepository, SchemeRepository

_list = list


class SchemeService:
    def __init__(self, session: Session) -> None:
        self.repo = SchemeRepository(session)
        self.labels = LabelRepository(session)
        self.datasets = DatasetRepository(session)

    def list(self, dataset_id: int) -> _list[SchemeDTO]:
        return self.repo.list(dataset_id=dataset_id)

    def create(self, dataset_id: int, data: SchemeCreateIn) -> SchemeDTO:
        if not self.datasets.exists(dataset_id):
            raise DatasetNotFoundError(dataset_id)
        payload = SchemeCreate(dataset_id=dataset_id, **data.model_dump())
        scheme_id = self.repo.create(payload, commit=True)
        return SchemeDTO(
            id=scheme_id,
            dataset_id=dataset_id,
            name=payload.name,
            label_mode=payload.label_mode,
            allow_extra_label=payload.allow_extra_label,
        )

    def list_labels(self, scheme_id: int) -> _list[LabelDTO]:
        return self.labels.list(scheme_id=scheme_id)

    def create_label(self, scheme_id: int, data: LabelCreateIn) -> LabelDTO:
        if not self.repo.exists(scheme_id):
            raise SchemeNotFoundError(scheme_id)
        payload = LabelCreate(scheme_id=scheme_id, name=data.name)
        label_id = self.labels.create(payload, commit=True)
        return LabelDTO(id=label_id, scheme_id=scheme_id, name=payload.name)
