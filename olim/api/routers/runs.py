from fastapi import APIRouter

from olim.api.deps import PipelineRunServiceDep
from olim.dto import PipelineRunDTO

router = APIRouter(prefix="/runs", tags=["runs"])


@router.get("/{run_id}")
def get_run(run_id: int, service: PipelineRunServiceDep) -> PipelineRunDTO:
    return service.get(run_id)
