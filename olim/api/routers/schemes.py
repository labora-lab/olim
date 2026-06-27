from fastapi import APIRouter

from olim.api.deps import SchemeServiceDep
from olim.api.schemas.scheme import LabelCreateIn, SchemeCreateIn
from olim.dto import LabelDTO, SchemeDTO

router = APIRouter(tags=["schemes"])


@router.get("/schemes")
def list_schemes(dataset_id: int, service: SchemeServiceDep) -> list[SchemeDTO]:
    return service.list(dataset_id)


@router.post("/schemes", status_code=201)
def create_scheme(
    dataset_id: int, payload: SchemeCreateIn, service: SchemeServiceDep
) -> SchemeDTO:
    return service.create(dataset_id, payload)


@router.get("/labels")
def list_labels(scheme_id: int, service: SchemeServiceDep) -> list[LabelDTO]:
    return service.list_labels(scheme_id)


@router.post("/labels", status_code=201)
def create_label(
    scheme_id: int, payload: LabelCreateIn, service: SchemeServiceDep
) -> LabelDTO:
    return service.create_label(scheme_id, payload)
