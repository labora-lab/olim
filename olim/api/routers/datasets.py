from fastapi import APIRouter

from olim.api.deps import DatasetServiceDep
from olim.dto import DatasetCreate, DatasetDTO

router = APIRouter(prefix="/datasets", tags=["datasets"])


@router.get("")
def list_datasets(service: DatasetServiceDep) -> list[DatasetDTO]:
    return service.list()


@router.post("", status_code=201)
def create_dataset(payload: DatasetCreate, service: DatasetServiceDep) -> DatasetDTO:
    return service.create(payload)


@router.get("/{dataset_id}")
def get_dataset(dataset_id: int, service: DatasetServiceDep) -> DatasetDTO:
    return service.get(dataset_id)
