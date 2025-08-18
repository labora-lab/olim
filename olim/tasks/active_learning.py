import json
import os  # Added for lock handling
import time  # Added for lock handling
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
from numpy.random import default_rng

from .. import app as flask_app, settings
from ..celery_app import app
from ..database import db, get_label, get_project
from ..learner import ActiveLearningBackend

COMPOSITE_ID = "({dataset_id},{entry_id})"
learners_cache = {}


# ====== LOCK HANDLING MECHANISM ======
class LockTimeoutError(Exception):
    """Exception raised when lock acquisition times out."""

    pass


def acquire_lock(lock_path: Path, timeout: int = 121) -> None:
    """Acquire a lock file with timeout and stale lock detection."""
    start_time = time.time()
    while time.time() - start_time < timeout:
        if lock_path.exists():
            print(f"Waiting for lock: {lock_path}")
            try:
                # Check for stale lock (process no longer running)
                with open(lock_path) as f:
                    pid = int(f.read().strip())
                try:
                    os.kill(pid, 0)  # Check if process exists
                except (ProcessLookupError, PermissionError):
                    lock_path.unlink()  # Remove stale lock
            except (OSError, ValueError, FileNotFoundError):
                pass  # Lock invalid or already removed
        try:
            # Attempt to create lock file
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "w") as f:
                f.write(f"{os.getpid()}\n")
            return
        except FileExistsError:
            time.sleep(5)  # Wait before retrying
    raise LockTimeoutError(
        f"Could not acquire lock after {timeout} seconds: {lock_path}"
    )


def release_lock(lock_path: Path) -> None:
    """Release lock by deleting lock file."""
    try:
        lock_path.unlink()
    except FileNotFoundError:
        pass  # Lock already removed


@contextmanager  # Add this decorator
def learner_lock(learner_path: Path) -> ...:
    """Context manager for learner locking."""
    lock_file = learner_path / "learner.lock"
    try:
        acquire_lock(lock_file)
        yield
    finally:
        release_lock(lock_file)


# ====== END LOCK HANDLING ======


def get_rng() -> np.random.Generator:
    if settings.RANDOM_SEED is None:
        seed = int(time.time())
    else:
        seed = settings.RANDOM_SEED
    print(f"Created generator using seed: {seed}")
    return default_rng(seed=seed)


def get_label_path(project_id: int, label_id: int, check: bool = True) -> Path | None:
    work_path = settings.WORK_PATH / f"project_{project_id}" / f"label_{label_id}"
    if not work_path.is_dir() and check:
        return None
    work_path.mkdir(parents=True, exist_ok=True)
    return work_path.absolute()


def get_data(project_id: int) -> dict[str, str]:
    with flask_app.app_context():
        project = get_project(project_id)
        if project is None:
            raise RuntimeError(f"Error loading project {project_id}.")

        data = {}
        dataset_dir = settings.WORK_PATH / "datasets"
        dataset = None
        try:
            for dataset in project.datasets:
                with open(dataset_dir / f"{dataset.id}.jsonl") as f:
                    for line in f.readlines():
                        line_data = json.loads(line)
                        data[
                            COMPOSITE_ID.format(
                                dataset_id=project_id, entry_id=line_data["id"]
                            )
                        ] = line_data["text"]
        except Exception as e:
            if dataset:
                print(f"Failed loading dataset {dataset.id}: {e}")
            raise
        return data


def get_label_values(label_id: int) -> dict[str, str]:
    with flask_app.app_context():
        label = get_label(label_id)
        if label is None:
            raise RuntimeError(f"Failed to load label {label_id}")

        # TODO: Handle multiple values for same label? Check order?
        values = {}
        for entrylabel in label.entries:
            if not entrylabel.deleted:
                values[
                    COMPOSITE_ID.format(
                        dataset_id=entrylabel.entry.dataset_id,
                        entry_id=entrylabel.entry.entry_id,
                    )
                ] = entrylabel.value

    return values


def instanciate_al(project_id, label_id) -> ActiveLearningBackend:
    data = get_data(project_id)
    learner_path = get_label_path(project_id, label_id, check=False)
    print(f"Instanciating learner for Project {project_id},  Label {label_id}")

    # Get learner parameters from label
    with flask_app.app_context():
        label = get_label(label_id)
        learner_params = (
            label.learner_parameters if label and label.learner_parameters else {}
        )

    labels = [label[0] for label in settings.LABELS]

    # Base parameters for ActiveLearningBackend
    base_params = {
        "original_dataset": data,  # type: ignore
        "label_values": labels,
        # initial_labelled_dataset=values, # type: ignore
        "save_path": learner_path,
        "rng": get_rng(),
    }

    # Merge base parameters with custom learner parameters
    all_params = {**base_params, **learner_params}

    print(f"[INSTANCIATE_AL] Label {label_id} learner parameters from DB: {learner_params}")
    print(f"[INSTANCIATE_AL] Base parameters: {list(base_params.keys())}")
    print(f"[INSTANCIATE_AL] All parameters being passed to ActiveLearningBackend: {list(all_params.keys())}")
    if learner_params:
        print(f"[INSTANCIATE_AL] Custom parameters values: {learner_params}")
    learner = ActiveLearningBackend(**all_params)

    print(f"Storing learner for Project {project_id},  Label {label_id}")
    learner.save()
    learners_cache[label_id] = learner
    return learner


def get_learner(project_id: int, label_id: int) -> ActiveLearningBackend:
    if label_id in learners_cache:
        return learners_cache[label_id]
    else:
        data = get_data(project_id)
        print(
            f"Learner for Project {project_id},  Label {label_id} not on cache, loading."
        )
        learner_path = get_label_path(project_id, label_id)
        if learner_path is None:
            return instanciate_al(project_id, label_id)

        # Get current learner parameters from database
        with flask_app.app_context():
            label = get_label(label_id)
            learner_params = (
                label.learner_parameters if label and label.learner_parameters else {}
            )

        print(f"[GET_LEARNER] Label {label_id} learner parameters from DB: {learner_params}")
        if learner_params:
            print(f"[GET_LEARNER] Loading learner with updated parameters: {learner_params}")
            print(f"[GET_LEARNER] Parameters keys: {list(learner_params.keys())}")
            print(f"[GET_LEARNER] Parameters values: {list(learner_params.values())}")
        else:
            print(f"[GET_LEARNER] No custom parameters found for label {label_id}")

        learner = ActiveLearningBackend.load(
            learner_path,
            data,  # type: ignore
            rng=get_rng(),
            **learner_params,  # Pass current parameters to override saved ones
        )
        learners_cache[label_id] = learner
        return learner


def update_label(label_id: int, **to_update) -> None:
    """Helper to update label metrics and cache"""
    with flask_app.app_context():
        # Get label
        label = get_label(label_id)
        if not label:
            raise ValueError(f"Label {label_id} not found")

        for col, value in to_update.items():
            setattr(label, col, value)

        db.session.commit()


@app.task(bind=True, name="learner.create_label_al")
def create_label_al(
    self,
    project_id: int,
    label_id: int,
    **__,
) -> dict[str, Any]:
    """Create new active learning for label"""
    learner_path = get_label_path(project_id, label_id, check=False)
    with learner_lock(learner_path):  # type: ignore
        learner = instanciate_al(project_id, label_id)

        update_label(
            label_id, metrics=[], cache=learner._cached_subsample, al_key=str(label_id)
        )

        # Fix to avoid old control
        learner._given_nexts = learner._cached_subsample

        learner.save()
    return {"success": True, "errors": None}


@app.task(bind=True, name="learner.train_model")
def train_model(
    self,
    project_id: int,
    label_id: int,
    **__,
) -> dict[str, Any]:
    """Train model and store results in label"""
    learner_path = get_label_path(project_id, label_id)
    with learner_lock(learner_path):  # type: ignore
        # Get learner
        learner = get_learner(project_id, label_id)

        # Load and subimmit cached entries # TODO: Get this from db kill add_label_value task
        learner_path = get_label_path(project_id, label_id, check=False)
        subs_file = learner_path / "submissions.jsonl"  # type: ignore
        with open(subs_file) as f:
            submissions = []
            for line in f.readlines():
                submissions.append(json.loads(line))
        subs_file.unlink()
        for subm in submissions:
            print(f"Submitting {subm.get('label_value')} for {subm.get('entry_id')}")
            learner.submit_labelling(**subm, check_given=False)

        # Sync previously laballed
        values = get_label_values(label_id)
        learner.sync_labelling(values)  # type: ignore

        # Train and get metrics
        learner._train()
        metrics = learner.metrics_strs
        new_cache = learner._cached_subsample

        # Update label with metrics and cache
        update_label(
            label_id,
            metrics=metrics,
            cache=new_cache,  # type: ignore
        )

        # Fix to avoid old control
        learner._given_nexts = learner._cached_subsample

        learner.save()
    return {"success": True, "metrics": metrics}


@app.task(bind=True, name="learner.add_label_value")
def add_label_value(
    self,
    project_id: int,
    label_id: int,
    user_id: int,
    dataset_id: int,
    entry_id: str,
    value: str,
    **__,
) -> dict[str, Any]:
    """Submit a labeled value and update metrics"""
    learner_path = get_label_path(project_id, label_id, check=False)
    with open(learner_path / "submissions.jsonl", "a") as f:  # type: ignore
        f.write(
            json.dumps(
                {
                    "entry_id": COMPOSITE_ID.format(
                        dataset_id=dataset_id, entry_id=entry_id
                    ),
                    "label_value": value,
                    "user_id": user_id,
                    "timestamp": datetime.now(UTC).timestamp(),
                }
            )
            + "\n"
        )
    return {"success": True}


@app.task(bind=True, name="learner.export_predictions")
def export_predictions(
    self,
    project_id: int,
    label_id: int,
    alpha: float = 0.95,
    **__,
) -> dict[str, Any]:
    """Export model predictions"""
    learner_path = get_label_path(project_id, label_id)
    with learner_lock(learner_path):  # type: ignore
        # Get learner
        learner = get_learner(project_id, label_id)

        learner._train()
        preds = learner.export_preditictions(alpha=alpha)

        metrics = learner.metrics_strs
        new_cache = learner._cached_subsample

        # Update label with metrics and cache
        update_label(
            label_id,
            metrics=metrics,
            cache=new_cache,  # type: ignore
        )

        learner.save()
    return {"success": True, "predictions": preds}
