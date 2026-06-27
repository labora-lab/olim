from fastapi import APIRouter

from olim.api.deps import SchemeServiceDep
from olim.api.schemas.scheme import SchemeCreateIn
from olim.dto import SchemeDTO

router = APIRouter(prefix="/schemes", tags=["schemes"])


@router.get("")
def list_schemes(dataset_id: int, service: SchemeServiceDep) -> list[SchemeDTO]:
    return service.list(dataset_id)


@router.post("", status_code=201)
def create_scheme(
    dataset_id: int, payload: SchemeCreateIn, service: SchemeServiceDep
) -> SchemeDTO:
    return service.create(dataset_id, payload)
