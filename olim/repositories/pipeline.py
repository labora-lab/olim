from dataclasses import replace

from repositron import Repository, on, writes

from olim.dto import PipelineBlockDTO, PipelineBlockSpec, PipelineCreate, PipelineDTO
from olim.models import Pipeline, PipelineBlock


class PipelineRepository(Repository[Pipeline, PipelineDTO, PipelineCreate]):
    @on("hydrate", mode="after")
    def with_blocks(self, model: Pipeline, dto: PipelineDTO) -> PipelineDTO:
        """Attach the ordered block list on every read."""
        return replace(dto, blocks=[self._block_dto(b) for b in model.blocks])

    @writes
    def create(
        self,
        payload: PipelineCreate,
        *,
        commit: bool | None = None,  # noqa: ARG002  consumed by @writes
    ) -> int:
        """Create an empty pipeline shell; blocks are appended one at a time."""
        pipeline = Pipeline(
            dataset_id=payload.dataset_id,
            scheme_id=payload.scheme_id,
            name=payload.name,
        )
        self.session.add(pipeline)
        self.session.flush()
        return pipeline.id

    @writes
    def append_block(
        self,
        pipeline_id: int,
        spec: PipelineBlockSpec,
        *,
        commit: bool | None = None,  # noqa: ARG002  consumed by @writes
    ) -> PipelineBlockDTO:
        """Append one block at the next position. Compatibility is checked in the
        service before this is called."""
        position = self._next_position(pipeline_id)
        block = PipelineBlock(
            pipeline_id=pipeline_id,
            type=spec.type,
            position=position,
            config=spec.config,
        )
        self.session.add(block)
        self.session.flush()
        return self._block_dto(block)

    def list_by_dataset(self, dataset_id: int) -> list[PipelineDTO]:
        return self.list(dataset_id=dataset_id)

    def _next_position(self, pipeline_id: int) -> int:
        pipeline = self.session.get(Pipeline, pipeline_id)
        blocks = pipeline.blocks if pipeline else []
        return max((b.position for b in blocks), default=-1) + 1

    def _block_dto(self, block: PipelineBlock) -> PipelineBlockDTO:
        return PipelineBlockDTO(
            id=block.id,
            pipeline_id=block.pipeline_id,
            type=block.type,
            position=block.position,
            config=block.config,
        )
