from celery import shared_task

from olim.database import worker_session
from olim.pipelines import BlockContext, get_store, load_training_data, runner_for
from olim.repositories import PipelineRunRepository


@shared_task(name="run_block")
def run_block(run_id: int, position: int) -> None:
    """Execute one block of a run: load its snapshot and the labeled data, run
    its runner over the upstream artifact, persist the result. Re-raises on
    failure so the chain halts and its errback marks the run failed."""
    with worker_session() as session:
        repo = PipelineRunRepository(session)
        block = repo.get_block_run(run_id, position)
        upstream_ref = repo.upstream_ref(run_id, position)
        repo.start_block(block.id, run_id, is_first=position == 0, commit=True)

        dataset_id, scheme_id = repo.training_ids(run_id)
        data = load_training_data(session, dataset_id, scheme_id)
        ctx = BlockContext(
            config=block.config,
            upstream_ref=upstream_ref,
            store=get_store(),
            run_id=run_id,
            position=position,
            data=data,
        )
        try:
            result = runner_for(block.type).run(ctx)
        except Exception as exc:
            repo.fail_block(block.id, str(exc), commit=True)
            raise

        repo.complete_block(
            block.id, run_id, position, result.artifact_ref, result.metrics, commit=True
        )


@shared_task(name="mark_run_failed")
def mark_run_failed(run_id: int) -> None:
    """Chain errback: a block raised, so the run as a whole failed."""
    with worker_session() as session:
        PipelineRunRepository(session).mark_run_failed(run_id, commit=True)
