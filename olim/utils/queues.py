## Auxiliary functions
# All functions here must have type hints and docstrings
import hashlib
import json
from pathlib import Path

import pandas as pd
from flask import flash, session
from flask_babel import _

from ..settings import QUEUES_PATH


def get_queue_path(queue_id: str | None = None, project_id: int | None = None) -> Path:
    queue_path = Path(QUEUES_PATH) / str(project_id)

    queue_path.mkdir(parents=True, exist_ok=True)

    if queue_id is None:
        return queue_path
    else:
        return queue_path / f"queue_{queue_id}.json"


def parse_queue(text: str) -> list[str]:
    """Parse a queue input in to a queue list.

    Args:
        text (str): Queue input

    Returns:
        List[str]: Queue list
    """
    # TODO: Rewrite this to deal with dataset_id
    return (
        text.replace(";", " ")
        .replace(",", " ")
        .replace("\n", " ")
        .replace("\r\n", " ")
        .split()
    )


def store_queue(
    queue: list[tuple[int, str]] | pd.Series,
    project_id: int,
    highlight: list[str] | None = None,
    **extra_data: dict,
) -> str:
    """Stores a queue in a temporay file.

    Args:
        queue (iterable): Queue list

    Returns:
        str: Hash of the queue for access
    """
    queue = list(queue)
    queue_id = hashlib.md5(json.dumps(queue).encode("utf-8")).hexdigest()
    queue_data = {
        "id": queue_id,
        "queue": queue,
        "project_id": project_id,
        "highlight": highlight,
        "extra_data": extra_data,
        "lenght": len(queue),
    }
    queue_file = get_queue_path(queue_id, project_id)
    with open(queue_file, "w") as f:
        json.dump(queue_data, f)
    return queue_id


def get_queue(queue_id: str, project_id) -> list[tuple[int, str]]:
    """Load the id of a position in a queue

    Args:
        queue_id (str): Hash of the queue for access

    Returns:
        list[tuple[int, str]]: Queue list
    """
    queue_file = get_queue_path(queue_id, project_id)
    with open(queue_file, "r") as f:
        queue = json.load(f)
    if queue["highlight"] is not None:
        session["highlight"] = queue["highlight"]
    return queue["queue"]


def get_all_queues(project_id) -> list[dict]:
    queues = []
    queue_dir = get_queue_path(project_id=project_id)
    for queue_file in queue_dir.iterdir():
        if queue_file.name.startswith("queue_") and queue_file.name.endswith(".json"):
            try:
                with open(queue_file, "r") as f:
                    queue = json.load(f)
            except Exception as e:
                flash(
                    _("Failed to read queue file {queue_file}.").format(
                        queue_file=queue_file
                    ),
                    category="error",
                )
                queue = None
            if queue is not None:
                queue["frontend_text"] = _("Entries: {queue_length}").format(
                    queue_length=queue["lenght"]
                )
                if queue["highlight"]:
                    queue["frontend_text"] += " - " + _(
                        "Highlight: {highlight}"
                    ).format(highlight=", ".join(h for h in queue["highlight"]))
                queues.append(queue)
    return queues
