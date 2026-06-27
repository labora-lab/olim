from sqlalchemy.orm import Session

from olim.api.exceptions import DatasetNotFoundError
from olim.dto import DatasetCreate, DatasetDTO
from olim.repositories import DatasetRepository

_list = list


class DatasetService:
    def __init__(self, session: Session) -> None:
        self.repo = DatasetRepository(session)

    def list(self) -> _list[DatasetDTO]:
        return self.repo.list()

    def get(self, dataset_id: int) -> DatasetDTO:
        dataset = self.repo.get(dataset_id)
        if dataset is None:
            raise DatasetNotFoundError(dataset_id)
        return dataset

    def create(self, payload: DatasetCreate) -> DatasetDTO:
        dataset_id = self.repo.create(payload, commit=True)
        return DatasetDTO(id=dataset_id, name=payload.name, data_type=payload.data_type)
