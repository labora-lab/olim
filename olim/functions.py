## Auxiliary functions
# All functions here must have type hints and docstrings
import hashlib
import json
import os
from typing import Literal

import pandas as pd
from flask import flash, session
from flask_babel import _

from . import entry_types, queue_dir
from .database import get_entry
from .utils.es import get_es_conn


def get_highlights() -> list:
    # Load highlight
    if "highlight" in session:
        return session["highlight"]
    else:
        return []


def render_entry(entry_id: int | None, data: dict | None = None) -> dict:
    if data is None:
        data = {}
    if entry_id is not None:
        entry = get_entry(entry_id)
        if entry is not None:
            try:
                e_type = getattr(entry_types, entry.type)
                data.update(
                    {
                        "entry_id": entry_id,
                        "entry_html": e_type.render(
                            entry_id,
                            highlight=get_highlights(),
                        ),
                        "entry": entry,
                        "labels_values": {
                            label.label_id: label.value
                            for label in entry.labels
                            if not label.is_deleted
                        },
                        "valid_entry": True,
                    }
                )
            except Exception:
                flash(
                    _("Error rendering entry {entry_id}!").format(entry_id=entry_id),
                    category="error",
                )
                data["valid_entry"] = False
        else:
            flash(
                _("Entry {entry_id} not found").format(entry_id=entry_id),
                category="error",
            )
            data["valid_entry"] = False
    return data


def parse_queue(text: str) -> list[str]:
    """Parse a queue input in to a queue list.

    Args:
        text (str): Queue input

    Returns:
        List[str]: Queue list
    """
    return text.replace(";", " ").replace(",", " ").replace("\n", " ").replace("\r\n", " ").split()


def store_queue(
    queue: list[str] | pd.Series, highlight: list[str] | None = None, **extra_data: dict
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
        "highlight": highlight,
        "exta_data": extra_data,
        "lenght": len(queue),
    }
    queue_file = os.path.join(queue_dir, "queue_" + queue_id + ".json")
    with open(queue_file, "w") as f:
        json.dump(queue_data, f)
    return queue_id


def get_queue(queue_id: str) -> str:
    """Load the id of a position in a queue

    Args:
        queue_hash (str): Hash of the queue for access

    Returns:
        str: Queue list
    """
    queue_file = os.path.join(queue_dir, "queue_" + queue_id + ".json")
    with open(queue_file) as f:
        queue = json.load(f)
    if queue["highlight"] is not None:
        session["highlight"] = queue["highlight"]
    return queue["queue"]


def get_all_queues() -> list[dict]:
    queues = []
    for queue_file in os.listdir(queue_dir):
        if queue_file.startswith("queue_") and queue_file.endswith(".json"):
            try:
                with open(os.path.join(queue_dir, queue_file)) as f:
                    queue = json.load(f)
            except Exception:
                flash(
                    _("Failed to read queue file {queue_file}.").format(queue_file=queue_file),
                    category="error",
                )
                queue = None
            if queue is not None:
                queue["frontend_text"] = _("Entries: {queue_length}").format(
                    queue_length=queue["lenght"]
                )
                if queue["highlight"]:
                    queue["frontend_text"] += " - " + _("Highlight: {highlight}").format(
                        highlight=", ".join(h for h in queue["highlight"])
                    )
                queues.append(queue)
    return queues


def get_def_nentries() -> int:
    """Gets the number os entries for the session.

    Returns:
        int: Number of entries.
    """
    if "number_of_entries" not in session:
        session["number_of_entries"] = 1000
    return session["number_of_entries"]


def manage_label_in_session(label: str, mode: Literal["add", "remove"] = "add") -> None:
    """Hide a label in a session

    Args:
        label (str): Label to hide
        session (flask.session): Flask session
    """
    if "hidden_labels" not in session:
        session["hidden_labels"] = []

    if mode == "add":
        session["hidden_labels"].append(label)
    elif mode == "remove":
        try:
            session["hidden_labels"].remove(label)
        except ValueError:
            pass


class ESManager:
    def __init__(self, serverfile="", **params) -> None:
        if len(params) == 0:
            with open(serverfile) as f:
                params = json.load(f)

        self.es = get_es_conn(**params)

    def create_index(self, index, mapping) -> dict:
        return self.es.indices.create(index=index, mappings=mapping)

    def delete_index(self, index) -> dict:
        return self.es.indices.delete(index=index)

    def list_indices(self) -> dict:
        return self.es.indices.get_alias(index="*")

    def get_mapping(self, index) -> dict:
        return self.es.indices.get_mapping(index=index)

    def add_document(self, document, index) -> dict:
        return self.es.index(index=index, document=document)

    def get_all_documents(self, index, size=10000) -> dict:
        return self.es.search(index=index, query={"match_all": {}}, size=size)

    def get_head_documents(self, index, n=10) -> dict:
        return self.es.search(index=index, query={"query": {"match_all": {}}, "from": 0, "size": n})

    def search(self, **kwargs) -> dict:
        return self.es.search(**kwargs)
