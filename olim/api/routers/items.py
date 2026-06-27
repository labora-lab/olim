from fastapi import APIRouter

from olim.api.deps import ItemServiceDep
from olim.api.schemas.item import ItemUpload
from olim.dto import ItemDTO

router = APIRouter(prefix="/items", tags=["items"])


@router.get("")
def list_items(dataset_id: int, service: ItemServiceDep) -> list[ItemDTO]:
    return service.list(dataset_id)


@router.post("", status_code=201)
def upload_items(
    dataset_id: int, payload: ItemUpload, service: ItemServiceDep
) -> list[ItemDTO]:
    return service.upload(dataset_id, payload.contents)
