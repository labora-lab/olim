from fastapi import APIRouter

from olim.api.deps import PipelineRunServiceDep, PipelineServiceDep
from olim.api.schemas.pipeline import BlockIn, CandidateOut, PipelineCreateIn
from olim.dto import PipelineDTO, PipelineRunDTO

router = APIRouter(prefix="/pipelines", tags=["pipelines"])


@router.get("")
def list_pipelines(dataset_id: int, service: PipelineServiceDep) -> list[PipelineDTO]:
    return service.list(dataset_id)


@router.post("", status_code=201)
def create_pipeline(
    dataset_id: int,
    scheme_id: int,
    payload: PipelineCreateIn,
    service: PipelineServiceDep,
) -> PipelineDTO:
    return service.create(dataset_id, scheme_id, payload.name)


@router.get("/{pipeline_id}")
def get_pipeline(pipeline_id: int, service: PipelineServiceDep) -> PipelineDTO:
    return service.get(pipeline_id)


@router.get("/{pipeline_id}/candidates")
def list_candidates(
    pipeline_id: int, service: PipelineServiceDep
) -> list[CandidateOut]:
    return service.candidates(pipeline_id)


@router.post("/{pipeline_id}/blocks", status_code=201)
def append_block(
    pipeline_id: int, payload: BlockIn, service: PipelineServiceDep
) -> PipelineDTO:
    return service.append_block(pipeline_id, payload)


@router.post("/{pipeline_id}/runs", status_code=201)
def start_run(pipeline_id: int, service: PipelineRunServiceDep) -> PipelineRunDTO:
    return service.create(pipeline_id)


@router.get("/{pipeline_id}/runs")
def list_runs(pipeline_id: int, service: PipelineRunServiceDep) -> list[PipelineRunDTO]:
    return service.list_by_pipeline(pipeline_id)
