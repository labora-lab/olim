from environs import env

env.read_env()

DATABASE_URL: str = env("DATABASE_URL")
CELERY_BROKER_URL: str = env("CELERY_BROKER_URL", "redis://redis:6379/0")
CELERY_RESULT_BACKEND: str = env("CELERY_RESULT_BACKEND", "redis://redis:6379/1")
ARTIFACT_ROOT: str = env("ARTIFACT_ROOT", "/artifacts")
