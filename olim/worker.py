from celery import Celery

from olim.config import CELERY_BROKER_URL, CELERY_RESULT_BACKEND

app = Celery(
    "olim",
    broker=CELERY_BROKER_URL,
    backend=CELERY_RESULT_BACKEND,
    include=["olim.tasks.runs"],
)
app.conf.update(
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_time_limit=600,
    task_soft_time_limit=540,
    worker_max_tasks_per_child=50,
    task_default_queue="light",
)
