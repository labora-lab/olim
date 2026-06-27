from celery import chain
from sqlalchemy.orm import Session

from olim.api.exceptions import (
    PipelineNotFoundError,
    PipelineNotRunnableError,
    RunNotFoundError,
)
from olim.dto import PipelineRunDTO
from olim.pipelines import BlockType, kind_for
from olim.repositories import PipelineRepository, PipelineRunRepository
from olim.worker import app as celery_app

_list = list

# Block categories whose real compute belongs on the heavy queue.
_HEAVY: frozenset[str] = frozenset({"model", "split"})


def _queue_for(block_type: BlockType) -> str:
    return "heavy" if kind_for(block_type).category in _HEAVY else "light"


class PipelineRunService:
    def __init__(self, session: Session) -> None:
        self.repo = PipelineRunRepository(session)
        self.pipelines = PipelineRepository(session)

    def create(self, pipeline_id: int) -> PipelineRunDTO:
        pipeline = self.pipelines.get(pipeline_id)
        if pipeline is None:
            raise PipelineNotFoundError(pipeline_id)
        if not pipeline.blocks:
            raise PipelineNotRunnableError(f"pipeline {pipeline_id} has no blocks")

        run_id = self.repo.create_run(pipeline, commit=True)

        # Build the chain AFTER the commit, so the worker never picks up a block
        # before its row is visible. Signatures are addressed by task name (no
        # import of task code) and immutable — they carry only ids, so no heavy
        # data crosses the broker.
        sigs = [
            celery_app.signature(
                "run_block", args=(run_id, block.position), immutable=True
            ).set(queue=_queue_for(block.type))
            for block in pipeline.blocks
        ]
        errback = celery_app.signature(
            "mark_run_failed", args=(run_id,), immutable=True
        )
        chain(*sigs).on_error(errback).apply_async()

        return self.get(run_id)

    def get(self, run_id: int) -> PipelineRunDTO:
        run = self.repo.get(run_id)
        if run is None:
            raise RunNotFoundError(run_id)
        return run

    def list_by_pipeline(self, pipeline_id: int) -> _list[PipelineRunDTO]:
        return self.repo.list_by_pipeline(pipeline_id)
