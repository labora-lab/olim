import os

from celery import Celery
from dotenv import load_dotenv

load_dotenv()
redis_port = os.getenv("REDIS_PORT", 6379)
redis_host = os.getenv("REDIS_HOST", "localhost")
redis_password = os.getenv("REDIS_PASSWORD", "")


broker_url = f"redis://:{redis_password}@{redis_host}:{redis_port}/0"
backend_url = f"redis://:{redis_password}@{redis_host}:{redis_port}/1"

print(broker_url, backend_url)

celery_app = Celery("olim", broker=broker_url, backend=backend_url, include=["olim.tasks"])


celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="America/Sao_Paulo",
    enable_utc=True,
    result_expires=3600,
)
