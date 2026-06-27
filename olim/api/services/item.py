from sqlalchemy.orm import Session

from olim.api.exceptions import DatasetNotFoundError
from olim.dto import ItemCreate, ItemDTO
from olim.repositories import DatasetRepository, ItemRepository

_list = list


class ItemService:
    def __init__(self, session: Session) -> None:
        self.repo = ItemRepository(session)
        self.datasets = DatasetRepository(session)

    def list(self, dataset_id: int) -> _list[ItemDTO]:
        return self.repo.list(dataset_id=dataset_id)

    def upload(self, dataset_id: int, contents: _list[str]) -> _list[ItemDTO]:
        if not self.datasets.exists(dataset_id):
            raise DatasetNotFoundError(dataset_id)
        payloads = [ItemCreate(dataset_id=dataset_id, content=c) for c in contents]
        ids = self.repo.bulk_create(payloads, commit=True)
        return [
            ItemDTO(id=i, dataset_id=dataset_id, content=c)
            for i, c in zip(ids, contents, strict=True)
        ]
