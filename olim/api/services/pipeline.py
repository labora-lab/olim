from sqlalchemy.orm import Session

from olim.api.exceptions import (
    BlockNotApplicableError,
    DatasetNotFoundError,
    PipelineNotFoundError,
    SchemeNotFoundError,
)
from olim.api.schemas.pipeline import BlockIn, CandidateOut, config_schema_for
from olim.dto import PipelineBlockSpec, PipelineCreate, PipelineDTO
from olim.pipelines import available_after, candidates, is_applicable, kind_for
from olim.repositories import DatasetRepository, PipelineRepository, SchemeRepository

_list = list


class PipelineService:
    def __init__(self, session: Session) -> None:
        self.repo = PipelineRepository(session)
        self.datasets = DatasetRepository(session)
        self.schemes = SchemeRepository(session)

    def create(self, dataset_id: int, scheme_id: int, name: str) -> PipelineDTO:
        if not self.datasets.exists(dataset_id):
            raise DatasetNotFoundError(dataset_id)
        if not self.schemes.exists(scheme_id):
            raise SchemeNotFoundError(scheme_id)
        pipeline_id = self.repo.create(
            PipelineCreate(dataset_id=dataset_id, scheme_id=scheme_id, name=name),
            commit=True,
        )
        return self.get(pipeline_id)

    def get(self, pipeline_id: int) -> PipelineDTO:
        pipeline = self.repo.get(pipeline_id)
        if pipeline is None:
            raise PipelineNotFoundError(pipeline_id)
        return pipeline

    def list(self, dataset_id: int) -> _list[PipelineDTO]:
        return self.repo.list_by_dataset(dataset_id)

    def candidates(self, pipeline_id: int) -> _list[CandidateOut]:
        pipeline = self.get(pipeline_id)
        available = available_after(b.type for b in pipeline.blocks)
        return [
            CandidateOut(
                type=k.type,
                category=k.category,
                consumes=sorted(k.consumes),
                produces=sorted(k.produces),
                config_schema=config_schema_for(k.type),
            )
            for k in candidates(available)
        ]

    def append_block(self, pipeline_id: int, block: BlockIn) -> PipelineDTO:
        pipeline = self.get(pipeline_id)
        available = available_after(b.type for b in pipeline.blocks)
        kind = kind_for(block.type)
        if not is_applicable(kind, available):
            raise BlockNotApplicableError(block.type, sorted(kind.consumes - available))
        spec = PipelineBlockSpec(
            type=block.type, config=block.model_dump(exclude={"type"})
        )
        self.repo.append_block(pipeline_id, spec, commit=True)
        return self.get(pipeline_id)
