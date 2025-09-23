## Auxiliary functions
# All functions here must have type hints and docstrings
import json
from pathlib import Path
from typing import Literal

from flask import flash, session
from flask_babel import _

from . import entry_types
from .database import get_entry, get_setup_step
from .utils.es import get_es_conn


def ensure_dir(path) -> None:
    Path(path).mkdir(parents=True, exist_ok=True)


def check_is_setup() -> bool:
    """Check if server is configured."""
    # Check actual setup status from database, not just session
    setup_step = get_setup_step()
    is_setup = setup_step is None

    # Update session with current status
    session["is_setup"] = is_setup
    return is_setup


def get_highlights() -> list | dict:
    # Load highlight data from session
    if "highlight" in session:
        highlight_data = session["highlight"]

        # Handle both old format (list of terms) and new format (object with color data)
        if isinstance(highlight_data, list):
            # Legacy format: return as-is for backward compatibility
            return highlight_data
        elif isinstance(highlight_data, dict) and "terms" in highlight_data:
            # New format: return the full object with color assignments
            return highlight_data
        else:
            # Invalid format
            return []
    else:
        return []


def render_entry(entry_id: str | None, dataset_id: int | None, data: dict | None = None) -> dict:
    if data is None:
        data = {}
    if entry_id is not None and dataset_id is not None:
        entry = get_entry((dataset_id, entry_id), "composite")
        if entry is not None:
            try:
                e_type = getattr(entry_types, entry.type)
                data.update(
                    {
                        "entry_html": e_type.render(
                            entry_id,
                            dataset_id,
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
        session["hidden_labels"].append(int(label))
    elif mode == "remove":
        try:
            session["hidden_labels"].remove(int(label))
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
