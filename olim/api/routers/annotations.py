from fastapi import APIRouter

from olim.api.deps import AnnotationServiceDep
from olim.api.schemas.annotation import AnnotateIn
from olim.dto import AnnotationDTO

router = APIRouter(prefix="/annotations", tags=["annotations"])


@router.get("")
def list_annotations(
    item_id: int, service: AnnotationServiceDep
) -> list[AnnotationDTO]:
    return service.list(item_id)


@router.post("", status_code=201)
def annotate(
    item_id: int, payload: AnnotateIn, service: AnnotationServiceDep
) -> list[AnnotationDTO]:
    return service.set_answers(item_id, payload.answers)
