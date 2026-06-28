from dataclasses import replace

from repositron import Repository, on, writes
from sqlalchemy import func, select, update

from olim.dto import BlockRunDTO, PipelineDTO, PipelineRunCreate, PipelineRunDTO
from olim.models import BlockRun, Pipeline, PipelineRun


class PipelineRunRepository(Repository[PipelineRun, PipelineRunDTO, PipelineRunCreate]):
    @on("hydrate", mode="after")
    def with_block_runs(
        self, model: PipelineRun, dto: PipelineRunDTO
    ) -> PipelineRunDTO:
        """Attach the ordered block runs on every read."""
        return replace(dto, blocks=[self._block_run_dto(b) for b in model.blocks])

    @writes
    def create_run(
        self,
        pipeline: PipelineDTO,
        *,
        commit: bool | None = None,  # noqa: ARG002  consumed by @writes
    ) -> int:
        """Create a run plus one block run per pipeline block, snapshotting each
        block's type/position/config so run history is independent of later edits."""
        run = PipelineRun(pipeline_id=pipeline.id)
        self.session.add(run)
        self.session.flush()  # need run.id for the block runs
        for block in pipeline.blocks:
            self.session.add(
                BlockRun(
                    run_id=run.id,
                    type=block.type,
                    position=block.position,
                    config=block.config,
                )
            )
        return run.id

    def list_by_pipeline(self, pipeline_id: int) -> list[PipelineRunDTO]:
        return self.list(pipeline_id=pipeline_id, order_by=PipelineRun.id.desc())

    # --- worker-side reads (own session, called from Celery tasks) ---

    def get_block_run(self, run_id: int, position: int) -> BlockRun:
        return self.session.execute(
            select(BlockRun).where(
                BlockRun.run_id == run_id, BlockRun.position == position
            )
        ).scalar_one()

    def upstream_ref(self, run_id: int, position: int) -> str | None:
        if position == 0:
            return None
        return self.session.execute(
            select(BlockRun.artifact_ref).where(
                BlockRun.run_id == run_id, BlockRun.position == position - 1
            )
        ).scalar_one()

    def training_ids(self, run_id: int) -> tuple[int, int]:
        """The (dataset_id, scheme_id) for a run, via its pipeline — what the
        runners need to load the labeled training set."""
        row = self.session.execute(
            select(Pipeline.dataset_id, Pipeline.scheme_id)
            .join(PipelineRun, PipelineRun.pipeline_id == Pipeline.id)
            .where(PipelineRun.id == run_id)
        ).one()
        return (row.dataset_id, row.scheme_id)

    @writes
    def start_block(
        self,
        block_run_id: int,
        run_id: int,
        *,
        is_first: bool,
        commit: bool | None = None,  # noqa: ARG002  consumed by @writes
    ) -> None:
        self._update_block(block_run_id, status="running", started_at=func.now())
        if is_first:
            self.update_where(
                PipelineRun.id == run_id, status="running", started_at=func.now()
            )

    @writes
    def complete_block(
        self,
        block_run_id: int,
        run_id: int,
        position: int,
        artifact_ref: str | None,
        metrics: dict | None,
        *,
        commit: bool | None = None,  # noqa: ARG002  consumed by @writes
    ) -> None:
        self._update_block(
            block_run_id,
            status="succeeded",
            artifact_ref=artifact_ref,
            metrics=metrics,
            finished_at=func.now(),
        )
        if self._is_last_position(run_id, position):
            self.update_where(
                PipelineRun.id == run_id, status="succeeded", finished_at=func.now()
            )

    @writes
    def fail_block(
        self,
        block_run_id: int,
        error: str,
        *,
        commit: bool | None = None,  # noqa: ARG002  consumed by @writes
    ) -> None:
        self._update_block(
            block_run_id, status="failed", error=error, finished_at=func.now()
        )

    @writes
    def mark_run_failed(
        self,
        run_id: int,
        *,
        commit: bool | None = None,  # noqa: ARG002  consumed by @writes
    ) -> None:
        self.update_where(
            PipelineRun.id == run_id, status="failed", finished_at=func.now()
        )

    def _is_last_position(self, run_id: int, position: int) -> bool:
        last = self.session.execute(
            select(func.max(BlockRun.position)).where(BlockRun.run_id == run_id)
        ).scalar_one()
        return position == last

    def _update_block(self, block_run_id: int, **values: object) -> None:
        self.session.execute(
            update(BlockRun).where(BlockRun.id == block_run_id).values(**values)
        )

    def _block_run_dto(self, block: BlockRun) -> BlockRunDTO:
        return BlockRunDTO(
            id=block.id,
            run_id=block.run_id,
            type=block.type,
            position=block.position,
            config=block.config,
            status=block.status,
            artifact_ref=block.artifact_ref,
            metrics=block.metrics,
            error=block.error,
        )
