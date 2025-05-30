import os
import warnings
from datetime import datetime

from celery import Celery
from celery.app.task import Task
from celery.result import AsyncResult
from celery.signals import task_failure, task_postrun, task_prerun, task_retry, task_success
from dotenv import load_dotenv
from flask import Flask
from flask_sqlalchemy import SQLAlchemy

from olim.database import CeleryTask

Task.__class_getitem__ = classmethod(lambda cls, *args, **kwargs: cls)  # type: ignore[attr-defined]

load_dotenv()
redis_port = os.getenv("REDIS_PORT", 6379)
redis_host = os.getenv("REDIS_HOST", "localhost")
redis_password = os.getenv("REDIS_PASSWORD", "")

broker_url = f"redis://:{redis_password}@{redis_host}:{redis_port}/0"
backend_url = f"redis://:{redis_password}@{redis_host}:{redis_port}/1"

app = Celery("olim", broker=broker_url, backend=backend_url, include=["olim.tasks"])

app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="America/Sao_Paulo",
    enable_utc=True,
    result_expires=3600,
)


def get_flask_app() -> Flask:
    """Import Flask app lazily to avoid circular imports"""
    try:
        from . import app as flask_app

        return flask_app
    except ImportError:
        from olim import app as flask_app

        return flask_app


def get_db() -> SQLAlchemy:
    """Import database lazily to avoid circular imports"""
    try:
        from . import db

        return db
    except ImportError:
        from olim import db

        return db


def get_celery_task_model() -> type[CeleryTask]:
    """Import CeleryTask model lazily to avoid circular imports"""
    try:
        from .database import CeleryTask

        return CeleryTask
    except ImportError:
        from olim.database import CeleryTask

        return CeleryTask


def should_track_task(kwargs) -> bool:
    """Check if task should be tracked based on track_progress parameter"""
    return kwargs.get("track_progress", True)


def extract_user_id(kwargs) -> int:
    """Extract user_id from task kwargs with fallback"""
    user_id = kwargs.get("user_id")
    if user_id is None:
        warnings.warn(
            f"Task launched without user_id. Using fallback user_id=0. "
            f"Task kwargs: {list(kwargs.keys())}",
            UserWarning,
            stacklevel=2,
        )
        return 0
    return user_id


@task_prerun.connect
def task_prerun_handler(
    sender=None, task_id=None, task=None, args=None, kwargs=None, **kwds
) -> None:
    """Handler called before task execution starts"""
    if not should_track_task(kwargs or {}):
        return

    try:
        flask_app = get_flask_app()
        db = get_db()
        CeleryTask = get_celery_task_model()  # noqa: N806

        with flask_app.app_context():
            # Check if task already exists (in case of retry)
            existing_task = db.session.get(CeleryTask, task_id)

            if existing_task:
                # Update existing task status
                existing_task.update_status("STARTED")
                existing_task.date_started = datetime.utcnow()
            else:
                # Create new task record
                user_id = extract_user_id(kwargs or {})

                task_record = CeleryTask.create_task(
                    task_id=task_id,  # type: ignore
                    task_name=sender.name if sender else "unknown_task",
                    user_id=user_id,
                    args=args,
                    kwargs=kwargs,
                )
                task_record.update_status("STARTED")
                task_record.date_started = datetime.utcnow()

                db.session.add(task_record)

            db.session.commit()

    except Exception as e:
        print(f"Error in task_prerun_handler for task {task_id}: {e}")


@task_postrun.connect
def task_postrun_handler(
    sender=None, task_id=None, task=None, args=None, kwargs=None, retval=None, state=None, **kwds
) -> None:
    """Handler called after task execution completes"""
    if not should_track_task(kwargs or {}):
        return

    try:
        flask_app = get_flask_app()
        db = get_db()
        CeleryTask = get_celery_task_model()  # noqa: N806

        with flask_app.app_context():
            task_record = db.session.get(CeleryTask, task_id)
            if task_record:
                # Update completion timestamp
                task_record.date_completed = datetime.utcnow()

                # Store result if available
                if retval is not None:
                    task_record.result = retval

                db.session.commit()

    except Exception as e:
        print(f"Error in task_postrun_handler for task {task_id}: {e}")


@task_success.connect
def task_success_handler(sender=None, task_id=None, result=None, **kwargs) -> None:
    """Handler called when task completes successfully"""
    # Extract kwargs from the task context if available
    task_kwargs = getattr(sender.request, "kwargs", {}) if hasattr(sender, "request") else {}  # type: ignore [sender.request attr]

    if not should_track_task(task_kwargs):
        return

    try:
        flask_app = get_flask_app()
        db = get_db()
        CeleryTask = get_celery_task_model()  # noqa: N806

        with flask_app.app_context():
            task_record = db.session.get(CeleryTask, task_id)
            if task_record:
                task_record.update_status("SUCCESS")
                if result is not None:
                    task_record.result = result
                db.session.commit()

    except Exception as e:
        print(f"Error in task_success_handler for task {task_id}: {e}")


@task_failure.connect
def task_failure_handler(sender=None, task_id=None, exception=None, einfo=None, **kwargs) -> None:
    """Handler called when task fails"""
    # Extract kwargs from the task context if available
    task_kwargs = getattr(sender.request, "kwargs", {}) if hasattr(sender, "request") else {}  # type: ignore [sender.request attr]

    if not should_track_task(task_kwargs):
        return

    try:
        flask_app = get_flask_app()
        db = get_db()
        CeleryTask = get_celery_task_model()  # noqa: N806

        with flask_app.app_context():
            task_record = db.session.get(CeleryTask, task_id)
            if task_record:
                task_record.update_status("FAILURE")
                task_record.error = str(exception) if exception else "Unknown error"
                task_record.traceback = str(einfo) if einfo else None
                db.session.commit()

    except Exception as e:
        print(f"Error in task_failure_handler for task {task_id}: {e}")


@task_retry.connect
def task_retry_handler(sender=None, task_id=None, reason=None, einfo=None, **kwargs) -> None:
    """Handler called when task is being retried"""
    # Extract kwargs from the task context if available
    task_kwargs = getattr(sender.request, "kwargs", {}) if hasattr(sender, "request") else {}  # type: ignore [sender.request attr]

    if not should_track_task(task_kwargs):
        return

    try:
        flask_app = get_flask_app()
        db = get_db()
        CeleryTask = get_celery_task_model()  # noqa: N806

        with flask_app.app_context():
            task_record = db.session.get(CeleryTask, task_id)
            if task_record:
                task_record.update_status("RETRY")
                # Store retry reason
                if reason:
                    task_record.error = str(reason)
                if einfo:
                    task_record.traceback = str(einfo)
                db.session.commit()

    except Exception as e:
        print(f"Error in task_retry_handler for task {task_id}: {e}")


# Utility function to launch tasks with tracking
def launch_task_with_tracking(
    task_func: Task, user_id, track_progress=True, *args, **kwargs
) -> AsyncResult:
    """
    Utility function to launch tasks with automatic user tracking

    Args:
        task_func: The Celery task function to execute
        user_id: ID of the user launching the task
        track_progress: Whether to track this task in the database
        *args: Positional arguments for the task
        **kwargs: Keyword arguments for the task

    Returns:
        AsyncResult: The Celery task result object
    """
    kwargs["user_id"] = user_id
    kwargs["track_progress"] = track_progress

    # Launch the task
    return task_func.delay(*args, **kwargs)
