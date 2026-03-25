import json
import re
from typing import Any

import requests
from flask import flash, render_template, session
from flask_babel import _

from .. import settings
from ..celery_app import app as celery_app, launch_task_with_tracking
from ..database import (
    add_entry_label,
    get_dataset_entry_type,
    get_entry,
    get_label,
    get_labeled_entry_ids,
    get_labels,
    new_queue,
    random_entries,
)
from ..entry_types.registry import get_entry_type_instance
from ..functions import render_entry
from ..label_types import get_label_type_module
from ..ml.services import MLModelService
from ..tasks.active_learning import train_model
from ..tasks.learning_tasks import label_queue_with_llm
from . import register_state
from .base import BaseState
from .entry_selector import resolve_sources


@register_state
class StaticContent(BaseState):
    """Static content state that displays HTML content with navigation.

    Params:
        title: Page title (required)
        body: HTML content to display (optional)
        show_prev: Show previous button (default: True)
        show_next: Show next button (default: True)
        prev_label: Custom label for previous button (default: "Previous")
        next_label: Custom label for next button (default: "Next")

    Example initial_setup:
    {
        "sequence": [
            {
                "state": "StaticContent",
                "params": {
                    "title": "Welcome",
                    "body": "<p>Welcome to this learning task!</p>",
                    "show_prev": false
                }
            },
            {
                "state": "StaticContent",
                "params": {
                    "title": "Instructions",
                    "body": "<p>Here are the instructions...</p>"
                }
            },
            {
                "state": "StaticContent",
                "params": {
                    "title": "Complete",
                    "body": "<p>You have completed the task!</p>",
                    "show_next": false
                }
            }
        ]
    }
    """

    def render(self) -> str:
        return render_template(
            "learning_tasks/static_content.html",
            title=self.params.get("title", "Untitled"),
            body=self.params.get("body", ""),
            show_prev=self.params.get("show_prev", True),
            show_next=self.params.get("show_next", True),
            prev_label=self.params.get("prev_label", "Previous"),
            next_label=self.params.get("next_label", "Next"),
            is_last_step=self.params.get("is_last_step", False),
        )

    def handle(self, action: str, payload: dict[str, Any]) -> int:
        if action == "next":
            return 1
        elif action == "prev":
            return -1
        return 0


@register_state
class ReadData(BaseState):
    """State that collects user input with validation.

    Params:
        title: Page title (required)
        description: Optional description text shown above the form
        fields: List of field definitions (required)
        submit_label: Label for submit button (default: "Continue")

    Field definition:
        name: Field key to store in data (required)
        label: Display label (required)
        type: Input type - text, number, email, textarea, select (default: text)
        required: Whether field is required (default: False)
        min: Minimum value for number, min length for text
        max: Maximum value for number, max length for text
        pattern: Regex pattern for validation
        placeholder: Placeholder text
        options: List of options for select type [{"value": "...", "label": "..."}]
        default: Default value

    Example:
    {
        "state": "ReadData",
        "params": {
            "title": "Personal Information",
            "description": "Please fill in your details",
            "fields": [
                {"name": "name", "label": "Full Name", "type": "text", "required": true},
                {"name": "age", "label": "Age", "type": "number", "min": 18, "max": 120},
                {"name": "email", "label": "Email", "type": "email", "required": true},
                {"name": "level", "label": "Experience Level", "type": "select",
                 "options": [{"value": "beginner", "label": "Beginner"},
                            {"value": "intermediate", "label": "Intermediate"},
                            {"value": "advanced", "label": "Advanced"}]}
            ]
        }
    }
    """

    def __init__(self, data: dict[str, Any], params: dict[str, Any] | None = None) -> None:
        super().__init__(data, params)
        self.errors: dict[str, str] = {}

    def render(self) -> str:
        fields = self.params.get("fields", [])
        # Pre-populate field values from data
        for field in fields:
            field_name = field.get("name")
            if field_name and field_name in self.data:
                field["value"] = self.data[field_name]
            elif "default" in field and field_name not in self.data:
                field["value"] = field["default"]

        return render_template(
            "learning_tasks/read_data.html",
            title=self.params.get("title", _("Input")),
            description=self.params.get("description", ""),
            fields=fields,
            errors=self.errors,
            submit_label=self.params.get("submit_label", _("Continue")),
            show_prev=self.params.get("show_prev", True),
            is_last_step=self.params.get("is_last_step", False),
        )

    def validate_field(self, field: dict, value: Any) -> str | None:  # noqa: ANN401
        """Validate a single field. Returns error message or None if valid."""
        field_name = field.get("name", "")
        field_type = field.get("type", "text")
        required = field.get("required", False)
        label = field.get("label", field_name)

        # Check required
        if required and (value is None or str(value).strip() == ""):
            return _("{label} is required").format(label=label)

        # Skip further validation if empty and not required
        if value is None or str(value).strip() == "":
            return None

        # Type-specific validation
        if field_type == "number":
            try:
                num_value = float(value)
                if "min" in field and num_value < field["min"]:
                    return _("{label} must be at least {min}").format(label=label, min=field["min"])
                if "max" in field and num_value > field["max"]:
                    return _("{label} must be at most {max}").format(label=label, max=field["max"])
            except (ValueError, TypeError):
                return _("{label} must be a valid number").format(label=label)

        elif field_type == "email":
            if not re.match(r"^[^@]+@[^@]+\.[^@]+$", str(value)):
                return _("{label} must be a valid email address").format(label=label)

        elif field_type in ("text", "textarea"):
            str_value = str(value)
            if "min" in field and len(str_value) < field["min"]:
                return _("{label} must be at least {min} characters").format(
                    label=label, min=field["min"]
                )
            if "max" in field and len(str_value) > field["max"]:
                return _("{label} must be at most {max} characters").format(
                    label=label, max=field["max"]
                )
            if "pattern" in field:
                if not re.match(field["pattern"], str_value):
                    pattern_msg = field.get("pattern_message", _("Invalid format"))
                    return f"{label}: {pattern_msg}"

        return None

    def handle(self, action: str, payload: dict[str, Any]) -> int:
        if action == "prev":
            return -1

        if action == "submit":
            fields = self.params.get("fields", [])
            self.errors = {}
            valid = True

            for field in fields:
                field_name = field.get("name")
                if not field_name:
                    continue

                value = payload.get(field_name)

                # Convert number types
                if field.get("type") == "number" and value:
                    try:
                        value = float(value)
                        if value == int(value):
                            value = int(value)
                    except (ValueError, TypeError):
                        pass

                error = self.validate_field(field, value)
                if error:
                    self.errors[field_name] = error
                    valid = False
                else:
                    # Store valid value in data
                    if value is not None and str(value).strip() != "":
                        self.data[field_name] = value

            if valid:
                return 1

        return 0


@register_state
class ShowData(BaseState):
    """Debug state that displays the current task data.

    Params:
        title: Page title (default: "Debug Data")
        show_keys: List of specific keys to show (default: show all)
        format: Display format - "json" or "table" (default: "table")

    Example:
    {
        "state": "ShowData",
        "params": {
            "title": "Collected Information",
            "show_keys": ["name", "email", "age"],
            "format": "table"
        }
    }
    """

    def render(self) -> str:
        show_keys = self.params.get("show_keys")
        display_format = self.params.get("format", "table")

        if show_keys:
            display_data = {k: self.data.get(k) for k in show_keys if k in self.data}
        else:
            display_data = self.data

        json_data = json.dumps(display_data, indent=2, ensure_ascii=False)

        return render_template(
            "learning_tasks/show_data.html",
            title=self.params.get("title", _("Debug Data")),
            data=display_data,
            json_data=json_data,
            display_format=display_format,
            show_prev=self.params.get("show_prev", True),
            show_next=self.params.get("show_next", True),
            is_last_step=self.params.get("is_last_step", False),
        )

    def handle(self, action: str, payload: dict[str, Any]) -> int:
        if action == "next":
            return 1
        elif action == "prev":
            return -1
        return 0


@register_state
class QueueSetup(BaseState):
    """State for setting up a labeling queue.

    Collects entry IDs and optionally lets user select which labels to use.

    Params:
        title: Page title (default: "Queue Setup")
        description: Optional description text
        dataset_id: Dataset ID to validate entries against (optional)
        labels: List of available labels [{"id": 1, "name": "Label A"}, ...]
                If not provided, will use project labels
        project_id: Project ID to get labels from (required if labels not provided)
        allow_label_selection: Let user select which labels to use (default: True)
        id_separator: Separator for parsing IDs - "newline", "comma", or "space"
                      (default: "newline")

    Stores in data:
        queue_ids: List of entry IDs to label
        queue_labels: List of selected labels [{"id": ..., "name": ...}, ...]
        queue_position: Current position in queue (starts at 0)
        queue_results: Dict mapping entry_id to label_id

    Example:
    {
        "state": "QueueSetup",
        "params": {
            "title": "Setup Labeling Queue",
            "description": "Enter the entry IDs you want to label",
            "project_id": 1,
            "allow_label_selection": true
        }
    }
    """

    def __init__(self, data: dict[str, Any], params: dict[str, Any] | None = None) -> None:
        super().__init__(data, params)
        self.errors: dict[str, str] = {}

    def _get_available_labels(self) -> list[dict]:
        """Get available labels from params or project context."""
        if "labels" in self.params:
            return self.params["labels"]

        # Use injected project context
        project_id = self.params.get("_project_id")
        if project_id:
            labels = get_labels(project_id)
            return [{"id": lbl.id, "name": lbl.name} for lbl in labels]

        return []

    def _default_sources(self) -> list[dict]:
        """Return current sources list for the widget, restoring last state."""
        if self.data.get("_sources"):
            return self.data["_sources"]
        # Check for legacy automation param
        if "entry_source" in self.params:
            return [{
                "type": self.params.get("entry_source", "manual"),
                "count": self.params.get("random_count", 10),
                "term": "",
                "pattern": "",
                "ids_text": "",
            }]
        return [{"type": "manual", "count": 10, "term": "", "pattern": "", "ids_text": ""}]

    def render(self) -> str:
        available_labels = self._get_available_labels()
        label_from_data = self.params.get("label_from_data", False)
        prefilled_label = None

        if label_from_data:
            label_id = self.data.get("al_label_id")
            prefilled_label = next((lbl for lbl in available_labels if lbl["id"] == label_id), None)
            selected_label_ids = [label_id] if label_id else []
        else:
            selected_label_ids = self.data.get("queue_labels", [])
            if selected_label_ids:
                selected_label_ids = [lbl["id"] for lbl in selected_label_ids]

        required_label_ids = self.data.get("queue_required_labels", [])
        if required_label_ids:
            required_label_ids = [lbl["id"] for lbl in required_label_ids]

        return render_template(
            "learning_tasks/queue_setup.html",
            title=self.params.get("title", _("Queue Setup")),
            description=self.params.get("description", ""),
            available_labels=available_labels,
            selected_label_ids=selected_label_ids,
            required_label_ids=required_label_ids,
            allow_label_selection=self.params.get("allow_label_selection", True),
            sources=self._default_sources(),
            completion_mode=self.data.get("queue_completion_mode", "any"),
            errors=self.errors,
            show_prev=self.params.get("show_prev", True),
            is_last_step=self.params.get("is_last_step", False),
            label_from_data=label_from_data,
            prefilled_label=prefilled_label,
        )

    def handle(self, action: str, payload: dict[str, Any]) -> int:
        if action == "prev":
            return -1

        if action == "submit":
            self.errors = {}
            project_id = self.params.get("_project_id")
            datasets = self.params.get("_datasets", [])

            # Parse multi-source blocks
            try:
                num_sources = int(payload.get("num_sources", 0))
            except (ValueError, TypeError):
                num_sources = 0

            if num_sources < 1:
                self.errors["sources"] = _("Please add at least one entry source")
                return 0

            sources_state: list[dict] = []
            for i in range(num_sources):
                try:
                    count = max(1, int(payload.get(f"source_{i}_count") or 10))
                except (ValueError, TypeError):
                    count = 10
                sources_state.append({
                    "type": payload.get(f"source_{i}_type", "manual"),
                    "count": count,
                    "term":    (payload.get(f"source_{i}_term")    or "").strip(),
                    "pattern": (payload.get(f"source_{i}_pattern") or "").strip(),
                    "ids_text": payload.get(f"source_{i}_ids") or "",
                })
            self.data["_sources"] = sources_state

            entry_ids = resolve_sources(sources_state, project_id, datasets)
            if not entry_ids:
                self.errors["sources"] = _("No entries found from the configured sources")
                return 0

            # Get selected labels
            available_labels = self._get_available_labels()
            if self.params.get("label_from_data"):
                label_id = self.data.get("al_label_id")
                selected_labels = [lbl for lbl in available_labels if lbl["id"] == label_id]
            elif self.params.get("allow_label_selection", True):
                selected_ids = (
                    payload.getlist("labels")
                    if hasattr(payload, "getlist")
                    else payload.get("labels", [])
                )
                if isinstance(selected_ids, str):
                    selected_ids = [selected_ids]
                selected_ids = [int(x) for x in selected_ids if x]

                if not selected_ids:
                    self.errors["labels"] = _("Please select at least one label")
                    return 0

                selected_labels = [lbl for lbl in available_labels if lbl["id"] in selected_ids]
            else:
                selected_labels = available_labels

            if not selected_labels:
                self.errors["labels"] = _("No labels available")
                return 0

            # Get required labels (subset of selected labels)
            required_ids = (
                payload.getlist("required_labels")
                if hasattr(payload, "getlist")
                else payload.get("required_labels", [])
            )
            if isinstance(required_ids, str):
                required_ids = [required_ids]
            required_ids = [int(x) for x in required_ids if x]
            required_labels = [lbl for lbl in selected_labels if lbl["id"] in required_ids]

            # Get completion mode
            completion_mode = payload.get("completion_mode", "any")
            if completion_mode not in ("any", "all"):
                completion_mode = "any"

            # Store queue data
            self.data["queue_ids"] = entry_ids
            self.data["queue_labels"] = selected_labels
            self.data["queue_required_labels"] = required_labels
            self.data["queue_completion_mode"] = completion_mode
            self.data["queue_position"] = 0
            self.data["queue_completed"] = []

            return 1

        return 0


@register_state
class LabelEntry(BaseState):
    """State for labeling entries in a queue.

    Loops through entries stored in data by QueueSetup, displaying each one
    and collecting labels until the queue is complete. Supports a list view
    to see all entries and jump to specific positions.

    Reads from data:
        queue_ids: List of entry IDs to label
        queue_labels: List of available labels
        queue_required_labels: List of required labels
        queue_completion_mode: "any" or "all" (default: "any")
        queue_position: Current position in queue
        queue_completed: List of entry IDs that meet completion criteria
        queue_view_mode: "label" or "list" (default: "label")
    """

    def _check_entry_complete(
        self,
        labels_values: dict,
        label_ids: list[int],
        required_label_ids: list[int],
        completion_mode: str,
    ) -> bool:
        """Check if an entry meets the completion criteria."""
        # Determine which labels to check
        check_ids = required_label_ids if required_label_ids else label_ids
        if not check_ids:
            return True

        filled = [lid for lid in check_ids if labels_values.get(lid)]

        if completion_mode == "all":
            return len(filled) == len(check_ids)
        else:  # "any"
            return len(filled) > 0

    def _get_labels_context(self) -> tuple[list, list[int], list[int], str]:
        """Get labels, required_label_ids, label_ids, and completion_mode."""
        queue_labels = self.data.get("queue_labels", [])
        project_id = self.params.get("_project_id")

        label_ids = [lbl["id"] for lbl in queue_labels]
        if label_ids:
            labels = [lbl for lbl in get_labels(project_id) if lbl.id in label_ids]
        else:
            labels = list(get_labels(project_id)) if project_id else []

        required_labels = self.data.get("queue_required_labels", [])
        required_label_ids = [lbl["id"] for lbl in required_labels]
        completion_mode = self.data.get("queue_completion_mode", "any")

        return labels, label_ids, required_label_ids, completion_mode

    def _update_completion(
        self,
        entry_id: str,
        labels_values: dict,
        label_ids: list[int],
        required_label_ids: list[int],
        completion_mode: str,
    ) -> None:
        """Update completion tracking for an entry."""
        completed = set(self.data.get("queue_completed", []))
        if self._check_entry_complete(
            labels_values, label_ids, required_label_ids, completion_mode
        ):
            completed.add(entry_id)
        else:
            completed.discard(entry_id)
        self.data["queue_completed"] = list(completed)

    def render(self) -> str:
        queue_ids = self.data.get("queue_ids", [])
        queue_position = self.data.get("queue_position", 0)
        queue_completed = self.data.get("queue_completed", [])
        view_mode = self.data.get("queue_view_mode", "label")

        total = len(queue_ids)
        position = queue_position + 1  # 1-indexed for display

        labels, label_ids, required_label_ids, completion_mode = self._get_labels_context()

        # List view mode
        if view_mode == "list":
            return render_template(
                "learning_tasks/queue_list.html",
                title=_("Queue Overview"),
                queue=queue_ids,
                labels=labels,
                required_label_ids=required_label_ids,
                current_position=queue_position,
                completed_entries=set(queue_completed),
                completed_count=len(queue_completed),
                completion_mode=completion_mode,
                is_last_step=self.params.get("is_last_step", False),
            )

        # Check if queue is complete
        if queue_position >= total:
            return render_template(
                "learning_tasks/queue_complete.html",
                title=_("Queue Complete"),
                total_labeled=len(queue_completed),
                total=total,
                is_last_step=self.params.get("is_last_step", False),
            )

        # Get current entry using render_entry helper
        current_id = queue_ids[queue_position]
        datasets = self.params.get("_datasets", [])

        # Try to find the entry in any of the project's datasets
        entry_data = {"valid_entry": False}
        for dataset in datasets:
            entry_data = render_entry(current_id, dataset.id)
            if entry_data.get("valid_entry"):
                break

        labels_values = entry_data.get("labels_values", {})

        # Update completion tracking for current entry
        self._update_completion(
            current_id,
            labels_values,
            label_ids,
            required_label_ids,
            completion_mode,
        )

        # Compute missing labels for warning
        check_ids = required_label_ids if required_label_ids else label_ids
        filled_ids = [lid for lid in check_ids if labels_values.get(lid)]
        missing_labels = [
            lbl
            for lbl in (
                self.data.get("queue_required_labels", [])
                if required_label_ids
                else self.data.get("queue_labels", [])
            )
            if lbl["id"] not in filled_ids
        ]

        # Get hidden labels from session
        hidden_labels = session.get("hidden_labels", [])

        return render_template(
            "learning_tasks/label_entry.html",
            # Entry data
            entry=entry_data.get("entry"),
            entry_html=entry_data.get("entry_html", ""),
            valid_entry=entry_data.get("valid_entry", False),
            labels_values=labels_values,
            # Labels
            labels=labels,
            required_label_ids=required_label_ids,
            missing_labels=missing_labels,
            completion_mode=completion_mode,
            hidden_labels=hidden_labels,
            show_hidden=False,
            # Queue navigation
            position=position,
            total=total,
            show_back=(self.params.get("show_back", True) and queue_position > 0),
            is_last_step=self.params.get("is_last_step", False),
        )

    def handle(self, action: str, payload: dict[str, Any]) -> int:
        queue_ids = self.data.get("queue_ids", [])
        queue_position = self.data.get("queue_position", 0)
        total = len(queue_ids)

        if action == "view_list":
            self.data["queue_view_mode"] = "list"
            return 0

        if action == "continue":
            self.data["queue_view_mode"] = "label"
            return 0

        if action == "goto":
            try:
                new_pos = int(payload.get("position", 0))
                if 0 <= new_pos < total:
                    self.data["queue_position"] = new_pos
            except (ValueError, TypeError):
                pass
            self.data["queue_view_mode"] = "label"
            return 0

        if action == "back_to_setup":
            self.data["queue_view_mode"] = "label"
            return -1

        if action == "prev_entry":
            if queue_position >= total:
                self.data["queue_position"] = total - 1
            elif queue_position > 0:
                self.data["queue_position"] = queue_position - 1
            return 0

        if action == "skip":
            new_position = queue_position + 1
            self.data["queue_position"] = new_position
            return 0

        if action in ("finish_queue", "finish"):
            return 1

        if action == "prev":
            return -1

        return 0


@register_state
class OllamaQueueSetup(BaseState):
    """State for setting up auto-labeling with Ollama LLM.

    Collects entry IDs (manual or random) and Ollama API configuration.

    Params:
        title: Page title (default: "Setup Auto-Labeling Queue")
        description: Optional description text
        entry_source: "manual" or "random" (can be hardcoded for automation)
        random_count: Number of random entries (default: 10)
        ollama_url: Ollama API URL (default: http://localhost:11434/v1)
        labels: Pre-selected label IDs for automation (optional)

    Stores in data:
        queue_ids: List of entry IDs to label
        queue_labels: List of selected labels [{"id": ..., "name": ...}, ...]
        ollama_url: Ollama API endpoint
        _entry_source: "manual" or "random"
        _queue_ids_text: Original text input (for manual mode)
        _random_count: Count if using random mode

    Example:
    {
        "state": "OllamaQueueSetup",
        "params": {
            "title": "Select Entries",
            "entry_source": "random",
            "random_count": 20,
            "ollama_url": "http://localhost:11434/v1",
            "labels": [1, 2]
        }
    }
    """

    def __init__(self, data: dict[str, Any], params: dict[str, Any] | None = None) -> None:
        super().__init__(data, params)
        self.errors: dict[str, str] = {}

    def _get_available_labels(self) -> list[dict]:
        """Get available labels from params or project context."""
        if "labels" in self.params:
            # If labels are provided as IDs, convert to full label info
            label_ids = self.params["labels"]
            project_id = self.params.get("_project_id")
            if project_id:
                all_labels = get_labels(project_id)
                return [
                    {"id": lbl.id, "name": lbl.name} for lbl in all_labels if lbl.id in label_ids
                ]
            return []

        # Use injected project context
        project_id = self.params.get("_project_id")
        if project_id:
            labels = get_labels(project_id)
            return [{"id": lbl.id, "name": lbl.name} for lbl in labels]

        return []

    def _default_sources(self) -> list[dict]:
        """Return the initial sources list for display."""
        if self.data.get("_sources"):
            return self.data["_sources"]
        # Automation mode: pre-populate from params
        if "entry_source" in self.params:
            return [{
                "type": self.params.get("entry_source", "random"),
                "count": self.params.get("random_count", 10),
                "term": "",
                "pattern": "",
                "ids_text": "",
            }]
        return [{"type": "random", "count": 10, "term": "", "pattern": "", "ids_text": ""}]

    def render(self) -> str:
        available_labels = self._get_available_labels()
        label_from_data = self.params.get("label_from_data", False)
        prefilled_label = None

        # Build label_descriptions from stored queue_labels or _label_descriptions
        stored_labels = self.data.get("queue_labels", [])
        label_descriptions: dict[str, str] = {
            str(lbl["id"]): lbl.get("description", "")
            for lbl in stored_labels
            if lbl.get("description")
        }
        label_descriptions.update(self.data.get("_label_descriptions", {}))

        if label_from_data:
            label_id = self.data.get("al_label_id")
            prefilled_label = next((lbl for lbl in available_labels if lbl["id"] == label_id), None)
            if prefilled_label:
                prefilled_label = dict(prefilled_label)
                prefilled_label.setdefault("description", label_descriptions.get(str(label_id), ""))
            selected_label_ids = [label_id] if label_id else []
        else:
            selected_label_ids = stored_labels
            if selected_label_ids:
                selected_label_ids = [lbl["id"] for lbl in selected_label_ids]
            if not selected_label_ids and "labels" in self.params:
                selected_label_ids = (
                    self.params["labels"] or [lbl["id"] for lbl in available_labels]
                )

        # Auto-submit when all required params are hardcoded (automation mode)
        auto_submit = (
            not label_from_data
            and "entry_source" in self.params
            and "ollama_url" in self.params
            and "labels" in self.params
            and not self.data.get("_auto_submitted_queue_setup")
        )

        return render_template(
            "learning_tasks/ollama_queue_setup.html",
            title=self.params.get("title", _("Setup Auto-Labeling Queue")),
            description=self.params.get("description", ""),
            available_labels=available_labels,
            selected_label_ids=selected_label_ids,
            sources=self._default_sources(),
            ollama_url=self.data.get("ollama_url", self.params.get("ollama_url", "http://localhost:11434/v1")),
            errors=self.errors,
            show_prev=self.params.get("show_prev", True),
            is_last_step=self.params.get("is_last_step", False),
            auto_submit=auto_submit,
            label_from_data=label_from_data,
            prefilled_label=prefilled_label,
            label_descriptions=label_descriptions,
        )

    def handle(self, action: str, payload: dict[str, Any]) -> int:
        if action == "prev":
            return -1

        if action == "submit":
            self.errors = {}
            self.data["_auto_submitted_queue_setup"] = True

            # ── Collect entries from multi-source blocks ─────────────────────
            try:
                num_sources = int(payload.get("num_sources", 0))
            except (ValueError, TypeError):
                num_sources = 0

            if num_sources < 1:
                self.errors["sources"] = _("Please add at least one entry source")
                return 0

            sources_state: list[dict] = []
            project_id = self.params.get("_project_id")
            datasets = self.params.get("_datasets", [])

            for i in range(num_sources):
                stype = payload.get(f"source_{i}_type", "random")
                try:
                    count = max(1, int(payload.get(f"source_{i}_count") or 10))
                except (ValueError, TypeError):
                    count = 10
                sources_state.append({
                    "type": stype,
                    "count": count,
                    "term": (payload.get(f"source_{i}_term") or "").strip(),
                    "pattern": (payload.get(f"source_{i}_pattern") or "").strip(),
                    "ids_text": payload.get(f"source_{i}_ids") or "",
                })

            self.data["_sources"] = sources_state
            entry_ids = resolve_sources(sources_state, project_id, datasets)

            if not entry_ids:
                self.errors["sources"] = _("No entries found from the configured sources")
                return 0

            # ── Labels ───────────────────────────────────────────────────────
            available_labels = self._get_available_labels()

            if self.params.get("label_from_data"):
                label_id = self.data.get("al_label_id")
                selected_labels = [lbl for lbl in available_labels if lbl["id"] == label_id]
            elif "labels" in self.params:
                selected_ids = self.params["labels"] or [lbl["id"] for lbl in available_labels]
                selected_labels = [lbl for lbl in available_labels if lbl["id"] in selected_ids]
            else:
                raw = (
                    payload.getlist("labels")
                    if hasattr(payload, "getlist")
                    else payload.get("labels", [])
                )
                if isinstance(raw, str):
                    raw = [raw]
                selected_ids = [int(x) for x in raw if x]
                selected_labels = [lbl for lbl in available_labels if lbl["id"] in selected_ids]

            if not selected_labels:
                self.errors["labels"] = _("Please select at least one label")
                return 0

            # ── Ollama URL ───────────────────────────────────────────────────
            ollama_url = (
                payload.get("ollama_url", self.params.get("ollama_url", "http://localhost:11434/v1"))
                .strip()
            )
            if not ollama_url:
                self.errors["ollama_url"] = _("Ollama URL is required")
                return 0
            if not (ollama_url.startswith("http://") or ollama_url.startswith("https://")):
                self.errors["ollama_url"] = _("URL must start with http:// or https://")
                return 0

            # ── Per-label descriptions (required) ───────────────────────────
            label_descriptions: dict[str, str] = {}
            missing_desc: list[str] = []
            for lbl in selected_labels:
                desc = (payload.get(f"description_{lbl['id']}", "") or "").strip()
                lbl["description"] = desc
                if desc:
                    label_descriptions[str(lbl["id"])] = desc
                else:
                    missing_desc.append(lbl["name"])
            if missing_desc:
                self.errors["labels"] = _("Description is required for: %(names)s", names=", ".join(missing_desc))
                return 0

            self.data["queue_ids"] = entry_ids
            self.data["queue_labels"] = selected_labels
            self.data["_label_descriptions"] = label_descriptions
            self.data["ollama_url"] = ollama_url
            return 1

        return 0


@register_state
class OllamaModelConfig(BaseState):
    """State for configuring LLM model and prompts.

    Allows selection of Ollama model and customization of prompts.

    Params:
        title: Page title (default: "Configure LLM")
        description: Optional description text
        model: Pre-selected model name (for automation)
        system_prompt: Pre-configured system prompt (for automation)
        prompt_template: Pre-configured prompt template (for automation)

    Reads from data:
        ollama_url: Ollama API URL (from OllamaQueueSetup)
        queue_labels: Selected labels
        queue_ids: Queue size

    Stores in data:
        llm_model: Selected model name
        llm_system_prompt: System prompt
        llm_prompt_template: Prompt template

    Example:
    {
        "state": "OllamaModelConfig",
        "params": {
            "title": "Configure LLM",
            "model": "llama3.2",
            "system_prompt": "You are an expert labeling assistant.",
            "prompt_template": "Label this text: {text}"
        }
    }
    """

    def __init__(self, data: dict[str, Any], params: dict[str, Any] | None = None) -> None:
        super().__init__(data, params)
        self.errors: dict[str, str] = {}

    def _fetch_ollama_models(self, ollama_url: str) -> list[str]:
        """Fetch available models from Ollama API.

        Args:
            ollama_url: Ollama API URL

        Returns:
            List of model names
        """
        try:
            # Remove /v1 suffix if present, add /api/tags
            base_url = ollama_url.replace("/v1", "")
            response = requests.get(f"{base_url}/api/tags", timeout=5)
            if response.ok:
                models = response.json().get("models", [])
                return [m["name"] for m in models]
        except Exception as e:
            self.errors["ollama_api"] = f"Failed to fetch models: {e!s}"
        return []

    def render(self) -> str:
        ollama_url = self.data.get("ollama_url", "http://localhost:11434/v1")
        queue_labels = self.data.get("queue_labels", [])
        queue_ids = self.data.get("queue_ids", [])

        # Fetch available models from Ollama
        available_models = self._fetch_ollama_models(ollama_url)

        # Default prompts
        default_system_prompt = (
            "You are a precise labeling assistant. You MUST respond with ONLY the exact"
            " label value - nothing else. No explanations, no punctuation, no formatting."
        )
        default_prompt_template = """Classify the following text for the label '{label_name}'.
Definition of '{label_name}': {label_description}

Text:
{text}

--- VALID OPTIONS (choose one exactly as shown) ---
{label_options}

IMPORTANT: Return ONLY the exact value from the options above. Copy it character-for-character.
Do not add any other text, explanation, punctuation, or formatting.

Your response:"""

        # Get current values or use params/defaults
        selected_model = self.data.get("llm_model", self.params.get("model", ""))
        system_prompt = self.data.get(
            "llm_system_prompt", self.params.get("system_prompt", default_system_prompt)
        )
        prompt_template = self.data.get(
            "llm_prompt_template", self.params.get("prompt_template", default_prompt_template)
        )

        # Detect automation mode - auto-submit if all required params are provided
        # and we haven't already attempted auto-submit
        auto_submit = (
            "model" in self.params
            and "prompt_template" in self.params
            and not self.data.get("_auto_submitted_model_config")  # Only auto-submit once
        )

        return render_template(
            "learning_tasks/ollama_model_config.html",
            title=self.params.get("title", _("Configure LLM")),
            description=self.params.get("description", ""),
            available_models=available_models,
            selected_model=selected_model,
            system_prompt=system_prompt,
            prompt_template=prompt_template,
            thinking=self.data.get("llm_thinking", self.params.get("thinking", False)),
            queue_labels=queue_labels,
            queue_size=len(queue_ids),
            errors=self.errors,
            show_prev=self.params.get("show_prev", True),
            is_last_step=self.params.get("is_last_step", False),
            auto_submit=auto_submit,
        )

    def handle(self, action: str, payload: dict[str, Any]) -> int:
        if action == "prev":
            return -1

        if action == "submit":
            self.errors = {}

            # Mark that we've attempted auto-submit (prevents infinite loop)
            self.data["_auto_submitted_model_config"] = True

            # Get model (from payload or params)
            model = payload.get("model", self.params.get("model", "")).strip()
            if not model:
                self.errors["model"] = _("Please select a model")
                return 0

            # Get prompts (from payload or params)
            default_sp = "You are a helpful assistant that accurately labels text data."
            system_prompt = payload.get(
                "system_prompt", self.params.get("system_prompt", default_sp)
            ).strip()
            prompt_template = payload.get(
                "prompt_template", self.params.get("prompt_template", "")
            ).strip()

            if not prompt_template:
                self.errors["prompt_template"] = _("Prompt template is required")
                return 0

            # Validate prompt template has required placeholders
            if "{text}" not in prompt_template:
                self.errors["prompt_template"] = _(
                    "Prompt template must contain {text} placeholder"
                )
                return 0

            # Store LLM configuration
            self.data["llm_model"] = model
            self.data["llm_system_prompt"] = system_prompt
            self.data["llm_prompt_template"] = prompt_template
            self.data["llm_thinking"] = payload.get("thinking") == "1"

            return 1

        return 0


@register_state
class OllamaAutoLabel(BaseState):
    """State for running LLM auto-labeling task.

    Launches a Celery task and tracks progress until completion.

    Params:
        title: Page title (default: "Auto-Labeling Progress")
        description: Optional description text
        auto_start: Auto-launch task on first render (default: True)

    Reads from data:
        queue_ids: Entries to label
        queue_labels: Labels to apply
        ollama_url: API endpoint
        llm_model: Model name
        llm_system_prompt: System prompt
        llm_prompt_template: Prompt template

    Stores in data:
        llm_task_id: Celery task ID
        llm_results: Results after completion

    Example:
    {
        "state": "OllamaAutoLabel",
        "params": {
            "title": "Auto-Labeling",
            "auto_start": true
        }
    }
    """

    def _get_task_status(self, task_id: str) -> dict[str, Any]:
        """Get Celery task status.

        Args:
            task_id: Celery task ID

        Returns:
            Dictionary with state, progress, message, result, error
        """
        task = celery_app.AsyncResult(task_id)

        if task.state == "PENDING":
            return {"state": "pending", "progress": 0, "message": "Task pending..."}
        elif task.state == "PROCESSING":
            meta = task.info or {}
            return {
                "state": "processing",
                "progress": meta.get("progress", 0),
                "message": meta.get("status", "Processing..."),
                "debug_conversations": meta.get("debug_conversations", []),
            }
        elif task.state == "SUCCESS":
            return {"state": "completed", "result": task.result}
        elif task.state == "FAILURE":
            return {"state": "failed", "error": str(task.info)}
        else:
            return {"state": "unknown", "progress": 0, "message": f"State: {task.state}"}

    def render(self) -> str:
        task_id: str | None = self.data.get("llm_task_id")

        # If no task yet, show start button
        if not task_id:
            return render_template(
                "learning_tasks/ollama_auto_label.html",
                title=self.params.get("title", _("Ready to Start Auto-Labeling")),
                mode="ready",
                queue_size=len(self.data.get("queue_ids", [])),
                label_count=len(self.data.get("queue_labels", [])),
                model=self.data.get("llm_model", ""),
                is_last_step=self.params.get("is_last_step", False),
            )

        # Poll task status (task_id should not be None here)
        if not task_id:
            return render_template(
                "learning_tasks/ollama_auto_label.html",
                title=self.params.get("title", _("Auto-Labeling Error")),
                mode="error",
                error="No task ID found",
                task_id="",
                is_last_step=self.params.get("is_last_step", False),
            )

        status = self._get_task_status(task_id)

        if status["state"] == "completed":
            self.data["llm_results"] = status["result"]

            # Calculate labeled entry IDs (all entries minus errors)
            all_entry_ids = set(self.data.get("queue_ids", []))
            error_entry_ids = {str(err["entry_id"]) for err in status["result"].get("errors", [])}
            labeled_entry_ids = sorted(all_entry_ids - error_entry_ids)

            result = status["result"]
            early_stop = result.get("early_stop", False)
            return render_template(
                "learning_tasks/ollama_auto_label.html",
                title=self.params.get(
                    "title",
                    _("Auto-Labeling Stopped Early") if early_stop else _("Auto-Labeling Complete"),
                ),
                mode="results",
                results=result,
                early_stop=early_stop,
                early_stop_error=result.get("early_stop_error"),
                debug_conversations=result.get("debug_conversations", []),
                labeled_entry_ids=labeled_entry_ids,
                created_queue_id=self.data.get("created_queue_id"),
                project_id=self.params.get("_project_id"),
                is_last_step=self.params.get("is_last_step", False),
            )
        elif status["state"] == "failed":
            return render_template(
                "learning_tasks/ollama_auto_label.html",
                title=self.params.get("title", _("Auto-Labeling Error")),
                mode="error",
                error=status.get("error", "Unknown error"),
                task_id=task_id,
                is_last_step=self.params.get("is_last_step", False),
            )
        else:
            return render_template(
                "learning_tasks/ollama_auto_label.html",
                title=self.params.get("title", _("Auto-Labeling in Progress")),
                mode="progress",
                progress=status.get("progress", 0),
                message=status.get("message", "Processing..."),
                debug_conversations=status.get("debug_conversations", []),
                task_id=task_id,
                is_last_step=self.params.get("is_last_step", False),
            )

    def handle(self, action: str, payload: dict[str, Any]) -> int:
        if action == "start":
            # Launch the Celery task
            queue_labels = self.data["queue_labels"]
            label_names = ", ".join(lc["name"] for lc in queue_labels if lc.get("name"))
            task = launch_task_with_tracking(
                label_queue_with_llm,
                user_id=self.params["_user_id"],
                queue_ids=self.data["queue_ids"],
                label_configs=queue_labels,
                datasets=[d.id for d in self.params["_datasets"]],
                project_id=self.params["_project_id"],
                ollama_url=self.data["ollama_url"],
                model=self.data["llm_model"],
                system_prompt=self.data["llm_system_prompt"],
                prompt_template=self.data["llm_prompt_template"],
                thinking=self.data.get("llm_thinking", False),
                description=f"LLM Auto-Labeling — {label_names}" if label_names else "LLM Auto-Labeling",
            )
            self.data["llm_task_id"] = task.id
            return 0  # Stay on this step to show progress

        if action == "cancel":
            task_id = self.data.get("llm_task_id")
            if task_id:
                celery_app.control.revoke(task_id, terminate=True)
            self.data.pop("llm_task_id", None)
            self.data.pop("llm_results", None)
            return 0

        if action == "retry":
            # Clear task ID to trigger re-launch
            self.data.pop("llm_task_id", None)
            self.data.pop("llm_results", None)
            return 0

        if action == "back_to_setup":
            # Go back to OllamaQueueSetup (2 steps back)
            self.data.pop("llm_task_id", None)
            self.data.pop("llm_results", None)
            return -2

        if action == "create_queue":
            # Create a queue from labeled entries
            task_id = self.data.get("llm_task_id")
            if not task_id:
                return 0

            status = self._get_task_status(task_id)
            if status["state"] != "completed":
                return 0

            # Calculate labeled entry IDs (all entries minus errors)
            all_entry_ids = self.data.get("queue_ids", [])
            error_entry_ids = {str(err["entry_id"]) for err in status["result"].get("errors", [])}
            labeled_entry_ids = [eid for eid in all_entry_ids if eid not in error_entry_ids]

            if not labeled_entry_ids:
                return 0

            # Build queue_data by looking up dataset_id for each entry
            queue_data = []
            datasets = self.params.get("_datasets", [])
            dataset_ids = [d.id for d in datasets]

            for entry_id in labeled_entry_ids:
                # Try to find entry in available datasets
                for ds_id in dataset_ids:
                    entry_obj = get_entry((ds_id, entry_id), by="composite")
                    if entry_obj:
                        queue_data.append((ds_id, entry_id))
                        break

            if not queue_data:
                return 0

            # Create queue
            queue = new_queue(
                queue_data=queue_data,
                name=f"LLM Labeled - {self.data.get('llm_model', 'Unknown Model')}",
                project_id=self.params["_project_id"],
                user_id=self.params["_user_id"],
                highlight=None,
            )

            # Store queue ID in data for display
            self.data["created_queue_id"] = queue.id

            # Flash success message
            flash(
                _("Queue created successfully with {count} entries").format(count=len(queue_data)),
                "success",
            )

            return 0  # Stay on this step to show the queue was created

        if action == "next":
            # Save results before moving to next step
            task_id = self.data.get("llm_task_id")
            if task_id:
                status = self._get_task_status(task_id)
                if status["state"] == "completed":
                    self.data["llm_results"] = status["result"]
            return 1

        if action == "prev":
            return -1

        return 0


@register_state
class ALLabelSelect(BaseState):
    """Picks a label for the subsequent active learning pipeline.

    Params:
        title: Page title (default: "Select Label")

    Stores in data:
        al_label_id: Selected label ID (int)
    """

    def render(self) -> str:
        return render_template(
            "learning_tasks/al_label_select.html",
            title=self.params.get("title", _("Select Label")),
            labels=get_labels(self.params["_project_id"]),
            selected_id=self.data.get("al_label_id"),
            is_last_step=self.params.get("is_last_step", False),
        )

    def handle(self, action: str, payload: dict[str, Any]) -> int:
        if action == "select":
            selected = payload.get("label_id")
            if selected:
                self.data["al_label_id"] = int(selected)
                return 1
        if action == "prev":
            return -1
        return 0


@register_state
class ColdStartSearchSetup(BaseState):
    """Search-per-class cold start setup.

    Reads al_label_id from data, shows one search field per class value.
    On submit, searches each dataset and populates queue_ids / queue_labels
    so the following LabelEntry step can proceed unchanged.

    Params:
        title: Page title (default: "Search per Class")
        cache_size: Max entries to collect (default: 100)
        retrain_every: Fallback sample size = retrain_every * 2 (default: 10)

    Reads from data:
        al_label_id: Label ID set by ALLabelSelect

    Stores in data:
        queue_ids: List of string entry IDs
        queue_labels: [{"id": ..., "name": ...}]
        queue_position: 0
        queue_completed: []
        queue_required_labels: []
        queue_completion_mode: "any"
    """

    def __init__(self, data: dict[str, Any], params: dict[str, Any] | None = None):
        super().__init__(data, params)
        self.errors: dict[str, str] = {}

    def _get_class_values(self, label_id: int | None) -> tuple[Any, list[str]]:
        """Return (label_obj, class_values) for the given label_id."""
        if not label_id:
            return None, []
        label_obj = next(
            (lb for lb in get_labels(self.params["_project_id"]) if lb.id == label_id),
            None,
        )
        class_values: list[str] = []
        if label_obj:
            try:
                module = get_label_type_module(label_obj.label_type)
                class_values = [opt[0] for opt in module.get_label_options()]
            except Exception:
                pass
        return label_obj, class_values

    def render(self) -> str:
        label_id = self.data.get("al_label_id")
        label_obj, class_values = self._get_class_values(label_id)
        return render_template(
            "learning_tasks/cold_start_search_setup.html",
            title=self.params.get("title", _("Search per Class")),
            label=label_obj,
            class_values=class_values,
            errors=self.errors,
            show_prev=self.params.get("show_prev", True),
            is_last_step=self.params.get("is_last_step", False),
        )

    def handle(self, action: str, payload: dict[str, Any]) -> int:
        if action == "prev":
            return -1

        if action == "submit":
            label_id = self.data.get("al_label_id")
            _, class_values = self._get_class_values(label_id)
            datasets = self.params.get("_datasets", [])
            cache_size = self.params.get("cache_size", 100)

            found_ids: list[str] = []
            seen: set[str] = set()
            if class_values and datasets:
                per_class = max(1, cache_size // max(len(class_values), 1))
                for class_val in class_values:
                    search_term = payload.get(f"search_{class_val}", "").strip()
                    if not search_term:
                        continue
                    for ds in datasets:
                        ds_entry_type = get_dataset_entry_type(ds.id) or "single_text"
                        instance = get_entry_type_instance(ds_entry_type)
                        if instance is not None and hasattr(instance, "search"):
                            try:
                                results = instance.search(
                                    must_terms=[search_term],
                                    must_phrases=[],
                                    not_must_terms=[],
                                    not_must_phrases=[],
                                    number=per_class,
                                    dataset_id=ds.id,
                                )
                                for r in results:
                                    eid = r["entry_id"]
                                    if eid not in seen:
                                        seen.add(eid)
                                        found_ids.append(eid)
                            except Exception:
                                pass

            if not found_ids:
                retrain_every = self.params.get("retrain_every", 10)
                fallback = list(random_entries(retrain_every * 2, self.params.get("_project_id")))
                found_ids = [e.entry_id for e in fallback]

            # Build queue_labels from the selected label
            all_labels = get_labels(self.params["_project_id"])
            label_obj = next((lb for lb in all_labels if lb.id == label_id), None)
            queue_labels = [
                {"id": label_id, "name": label_obj.name if label_obj else str(label_id)}
            ]

            self.data["queue_ids"] = found_ids
            self.data["queue_labels"] = queue_labels
            self.data["queue_position"] = 0
            self.data["queue_completed"] = []
            self.data["queue_required_labels"] = []
            self.data["queue_completion_mode"] = "any"
            return 1

        return 0


@register_state
class ActiveLearningLoop(BaseState):
    """Active learning loop state: train → label uncertain entries → retrain.

    Manages the full active learning cycle with automatic retraining after N labels.
    Entries are selected by uncertainty ranking from the model's cache.

    Params:
        label_id: Label to train on (optional; if omitted, user picks at runtime)
        title: Page title (default: "Active Learning")
        metric_goal: {metric: threshold} — stop when any is exceeded (default: {})
        max_rounds: Stop after N retraining rounds (default: 10)
        retrain_every: Auto-retrain after this many entries advanced (default: 10)
        cache_size: Max entries to take from version.cache_entries (default: 100)

    Stores in data:
        al_label_id: Selected label ID
        al_task_id: Current Celery task ID
        al_task_error: Error message if task failed
        al_model_id: MLModel DB id
        al_version_id: MLModelVersion DB id
        al_round: Round index (starts at 0, increments after each retrain)
        al_cache: Entry DB primary keys from version.cache_entries
        al_cache_position: Current position in cache
        al_labels_this_round: Labels advanced since last retrain
        al_metrics: Metrics from most recent training
        al_metrics_history: [{round, accuracy, auc_roc, ...}] per round
        al_setting_*: Runtime overrides for retrain_every / cache_size / max_rounds
    """

    def _get_setting(self, key: str, default: Any) -> Any:
        """Return a runtime override from data if set, otherwise fall back to params."""
        override = self.data.get(f"al_setting_{key}")
        return override if override is not None else self.params.get(key, default)

    def _get_task_status(self, task_id: str) -> dict[str, Any]:
        """Poll Celery task status."""
        task = celery_app.AsyncResult(task_id)
        if task.state == "PENDING":
            return {"state": "pending", "progress": 0, "message": "Task pending..."}
        elif task.state == "PROCESSING":
            meta = task.info or {}
            return {
                "state": "processing",
                "progress": meta.get("progress", 0),
                "message": meta.get("status", "Processing..."),
            }
        elif task.state == "SUCCESS":
            return {"state": "completed", "result": task.result}
        elif task.state == "FAILURE":
            return {"state": "failed", "error": str(task.info)}
        else:
            return {"state": "unknown", "progress": 0, "message": f"State: {task.state}"}

    def _get_training_overrides(self) -> dict:
        """Build the training_overrides dict from runtime settings stored in data."""
        overrides: dict = {}
        for key in ("split", "alpha", "pool_size", "n_clusters", "cache_size", "certain_rate"):
            val = self.data.get(f"al_setting_{key}")
            if val is not None:
                overrides[key] = val
        return overrides

    def _launch_training(self, label_id: int) -> None:
        """Launch the train_model Celery task and store task ID."""
        label_obj = get_label(label_id)
        label_name = label_obj.name if label_obj else str(label_id)
        task = launch_task_with_tracking(
            train_model,
            user_id=self.params["_user_id"],
            label_id=label_id,
            project_id=self.params["_project_id"],
            training_overrides=self._get_training_overrides(),
            description=f"Model Training — {label_name}",
        )
        self.data["al_task_id"] = task.id
        self.data.pop("al_task_error", None)

    def _trigger_retrain(self, label_id: int) -> None:
        """Increment round counter and launch background training.

        Keeps the existing cache so labeling continues uninterrupted.
        New cache is loaded when training completes via _on_training_complete.
        """
        self.data["al_round"] = self.data.get("al_round", 0) + 1
        self.data["al_labels_this_round"] = 0
        self.data.pop("al_metrics", None)
        self._launch_training(label_id)

    def _on_training_complete(self, result: dict[str, Any]) -> None:
        """Handle training completion: parse metrics and populate entry cache."""
        self.data["al_model_id"] = result["model_id"]
        self.data["al_version_id"] = result["version_id"]
        self.data.pop("al_task_id", None)

        metrics: dict[str, float | str] = {}
        for m in result.get("metrics", []):
            key, val = m.split(": ", 1)
            try:
                metrics[key] = float(val)
            except ValueError:
                metrics[key] = val
        self.data["al_metrics"] = metrics

        # Update consecutive goal streak (used by stability check)
        metric_goal = self._get_setting("metric_goal", {})
        if metric_goal:
            direction = self._get_setting("metric_direction", "above")
            goal_met = False
            for mg_key, mg_thr in metric_goal.items():
                try:
                    val = float(metrics.get(mg_key, 0))
                except (TypeError, ValueError):
                    continue
                if direction == "below" and val <= float(mg_thr):
                    goal_met = True
                    break
                elif direction != "below" and val >= float(mg_thr):
                    goal_met = True
                    break
            self.data["al_goal_streak"] = (self.data.get("al_goal_streak", 0) + 1) if goal_met else 0

        history: list[dict[str, Any]] = list(self.data.get("al_metrics_history", []))
        history.append({"round": self.data.get("al_round", 0), **metrics})
        self.data["al_metrics_history"] = history

        cache_size = self._get_setting("cache_size", 100)
        service = MLModelService(settings.WORK_PATH)
        version = service.get_active_version(result["model_id"])
        raw_cache: list[dict] = (
            version.cache_entries[:cache_size] if version and version.cache_entries else []
        )
        cache = [item["id"] for item in raw_cache]
        self.data["al_cache"] = cache
        self.data["al_cache_scores"] = {
            str(item["id"]): {"score": item["score"], "reason": item["reason"]}
            for item in raw_cache
        }

        label_id: int | None = self.params.get("label_id") or self.data.get("al_label_id")
        self.data["al_cache_position"] = (
            self._seek_first_unlabeled(cache, label_id) if label_id else 0
        )

    def _seek_first_unlabeled(self, cache: list[int], label_id: int) -> int:
        """Return the index of the first cache entry that has no label yet."""
        labeled = get_labeled_entry_ids(label_id)
        for i, entry_db_id in enumerate(cache):
            if entry_db_id not in labeled:
                return i
        return 0  # all labeled — restart from the top

    def _check_goal_reached(self) -> bool:
        """Check if stopping condition is met (metric threshold or max rounds fallback)."""
        if not self.data.get("al_metrics"):
            return False
        metric_goal = self._get_setting("metric_goal", {})
        if metric_goal:
            mg_consecutive = max(1, int(self._get_setting("mg_consecutive", 1)))
            streak = self.data.get("al_goal_streak", 0)
            if streak >= mg_consecutive:
                self.data["al_stop_reason"] = "goal"
                return True
        max_rounds = int(self._get_setting("max_rounds", 10))
        if max_rounds != -1 and self.data.get("al_round", 0) >= max_rounds:
            self.data["al_stop_reason"] = "max_rounds"
            return True
        return False

    def render(self) -> str:
        label_id: int | None = self.params.get("label_id") or self.data.get("al_label_id")
        title = self.params.get("title", _("Active Learning"))

        # Mode: select label
        if not label_id:
            mg = self._get_setting("metric_goal", {})
            mg_metric, mg_threshold = (list(mg.items()) + [("", "")])[0]
            return render_template(
                "learning_tasks/active_learning_loop.html",
                mode="select",
                title=title,
                labels=get_labels(self.params["_project_id"]),
                setting_retrain_every=self._get_setting("retrain_every", 10),
                setting_cache_size=self._get_setting("cache_size", 100),
                setting_max_rounds=self._get_setting("max_rounds", 10),
                setting_split=self._get_setting("split", 0.8),
                setting_alpha=self._get_setting("alpha", 0.1),
                setting_pool_size=self._get_setting("pool_size", 1000),
                setting_n_clusters=self._get_setting("n_clusters", 20),
                setting_certain_rate=self._get_setting("certain_rate", 0.0),
                setting_mg_metric=mg_metric,
                setting_mg_threshold=mg_threshold,
                setting_mg_direction=self._get_setting("metric_direction", "above"),
                setting_mg_consecutive=self._get_setting("mg_consecutive", 1),
                is_last_step=self.params.get("is_last_step", False),
            )

        task_id: str | None = self.data.get("al_task_id")
        cache: list[int] = self.data.get("al_cache", [])
        pos: int = self.data.get("al_cache_position", 0)

        # Blocking train mode: no usable cache, must wait for training
        if not cache or pos >= len(cache):
            if task_id:
                # Task running — show live progress (poll via POST to avoid mutation issues)
                status = self._get_task_status(task_id)
                if status["state"] == "failed":
                    return render_template(
                        "learning_tasks/active_learning_loop.html",
                        mode="train",
                        sub="error",
                        title=title,
                        error=self.data.get("al_task_error", status.get("error", _("Unknown error"))),
                        round=self.data.get("al_round", 0),
                        is_last_step=self.params.get("is_last_step", False),
                    )
                return render_template(
                    "learning_tasks/active_learning_loop.html",
                    mode="train",
                    sub="progress",
                    title=title,
                    round=self.data.get("al_round", 0),
                    progress=status.get("progress", 0),
                    message=status.get("message", _("Processing...")),
                    metrics_history=self.data.get("al_metrics_history", []),
                    is_last_step=self.params.get("is_last_step", False),
                )
            # No task yet (initial or cache just exhausted) — poll will start training
            return render_template(
                "learning_tasks/active_learning_loop.html",
                mode="train",
                sub="progress",
                title=title,
                round=self.data.get("al_round", 0),
                progress=0,
                message=_("Starting training..."),
                metrics_history=self.data.get("al_metrics_history", []),
                is_last_step=self.params.get("is_last_step", False),
            )

        # Mode: results (goal or rounds exhausted)
        if self._check_goal_reached():
            mg = self._get_setting("metric_goal", {})
            mg_metric, mg_threshold = (list(mg.items()) + [("", "")])[0]
            return render_template(
                "learning_tasks/active_learning_loop.html",
                mode="results",
                title=title,
                metrics=self.data.get("al_metrics", {}),
                history=self.data.get("al_metrics_history", []),
                round=self.data.get("al_round", 0),
                stop_reason=self.data.get("al_stop_reason", "max_rounds"),
                stop_mg_metric=mg_metric,
                stop_mg_threshold=mg_threshold,
                stop_mg_direction=self._get_setting("metric_direction", "above"),
                stop_mg_consecutive=self._get_setting("mg_consecutive", 1),
                stop_max_rounds=self._get_setting("max_rounds", 10),
                is_last_step=self.params.get("is_last_step", False),
            )

        # Mode: label current uncertain entry
        retrain_every: int = self._get_setting("retrain_every", 10)
        labels_this_round: int = self.data.get("al_labels_this_round", 0)
        entry_db_id = cache[pos]
        entry_obj = get_entry(entry_db_id, by="id")
        if entry_obj:
            entry_data = render_entry(entry_obj.entry_id, entry_obj.dataset_id)
        else:
            entry_data = {"valid_entry": False}
        label_obj = next(
            (lb for lb in get_labels(self.params["_project_id"]) if lb.id == label_id), None
        )
        label_options: list = []
        if label_obj:
            ltype = get_label_type_module(label_obj.label_type)
            label_options = ltype.get_label_options() if ltype else []
        cache_scores: dict = self.data.get("al_cache_scores", {})
        entry_score_info: dict = cache_scores.get(str(entry_db_id), {})
        return render_template(
            "learning_tasks/active_learning_loop.html",
            mode="label",
            title=title,
            entry=entry_data.get("entry"),
            entry_html=entry_data.get("entry_html", ""),
            valid_entry=entry_data.get("valid_entry", False),
            labels_values=entry_data.get("labels_values", {}),
            label=label_obj,
            label_options=label_options,
            position=pos + 1,
            total=len(cache),
            labels_this_round=labels_this_round,
            retrain_every=retrain_every,
            round=self.data.get("al_round", 0),
            metrics=self.data.get("al_metrics", {}),
            retraining=bool(task_id),
            task_error=self.data.get("al_task_error"),
            entry_score=entry_score_info.get("score"),
            entry_reason=entry_score_info.get("reason"),
            show_highlights=True,
            highlight=session.get("highlight"),
            is_last_step=self.params.get("is_last_step", False),
        )

    def handle(self, action: str, payload: dict[str, Any]) -> int:
        label_id: int | None = self.params.get("label_id") or self.data.get("al_label_id")

        if action == "poll_train":
            # Called by the train-mode polling form every few seconds.
            # This is the ONLY place that launches/applies training — render() is read-only.
            task_id = self.data.get("al_task_id")
            if task_id:
                status = self._get_task_status(task_id)
                if status["state"] == "completed":
                    self._on_training_complete(status["result"])
                elif status["state"] == "failed":
                    self.data.pop("al_task_id", None)
                    self.data["al_task_error"] = status.get("error", _("Unknown error"))
                # else still running — no-op, render will show progress
            else:
                # No task running — start one (initial or cache just exhausted)
                cache = self.data.get("al_cache", [])
                pos = self.data.get("al_cache_position", 0)
                if (not cache or pos >= len(cache)) and label_id:
                    self._trigger_retrain(label_id)
            return 0

        if action == "select_label":
            selected = payload.get("label_id")
            if selected:
                self.data["al_label_id"] = int(selected)
            # Persist advanced settings overrides
            for key, cast in [
                ("retrain_every", int),
                ("cache_size", int),
                ("pool_size", int),
                ("n_clusters", int),
                ("split", float),
                ("alpha", float),
                ("certain_rate", float),
            ]:
                raw = payload.get(key, "").strip()
                try:
                    val = cast(raw)
                    if val > 0:
                        self.data[f"al_setting_{key}"] = val
                except (ValueError, TypeError):
                    pass  # keep existing or param default
            # max_rounds: allow -1 for unlimited
            raw_max = payload.get("max_rounds", "").strip()
            try:
                max_rounds_val = int(raw_max)
                if max_rounds_val == -1 or max_rounds_val > 0:
                    self.data["al_setting_max_rounds"] = max_rounds_val
            except (ValueError, TypeError):
                pass
            # metric_goal: "metric:threshold" or empty
            mg_metric = payload.get("mg_metric", "").strip()
            mg_threshold = payload.get("mg_threshold", "").strip()
            mg_direction = payload.get("mg_direction", "above").strip()
            mg_consecutive_raw = payload.get("mg_consecutive", "").strip()
            if mg_metric and mg_threshold:
                try:
                    self.data["al_setting_metric_goal"] = {mg_metric: float(mg_threshold)}
                    self.data["al_setting_metric_direction"] = mg_direction if mg_direction in ("above", "below") else "above"
                    mg_consecutive_val = int(mg_consecutive_raw) if mg_consecutive_raw else 1
                    self.data["al_setting_mg_consecutive"] = max(1, mg_consecutive_val)
                except ValueError:
                    pass
            else:
                self.data.pop("al_setting_metric_goal", None)
                self.data.pop("al_setting_metric_direction", None)
                self.data.pop("al_setting_mg_consecutive", None)
            if selected:
                self._launch_training(int(selected))
            return 0

        if action == "retry_train":
            self.data.pop("al_task_id", None)
            self.data.pop("al_task_error", None)
            if label_id:
                self._launch_training(label_id)
            return 0

        if action == "label":
            # Check if background retraining finished since last label
            bg_task_id = self.data.get("al_task_id")
            if bg_task_id:
                bg_status = self._get_task_status(bg_task_id)
                if bg_status["state"] == "completed":
                    self._on_training_complete(bg_status["result"])
                elif bg_status["state"] == "failed":
                    self.data.pop("al_task_id", None)
                    self.data["al_task_error"] = bg_status.get("error", _("Unknown error"))

            # Save the label value then advance
            entry_db_id = payload.get("entry_id")
            value = payload.get("value", "")
            if entry_db_id and label_id:
                try:
                    add_entry_label(label_id, int(entry_db_id), self.params.get("_user_id"), value)
                except Exception as e:
                    print(f"[AL] Failed to save label: {e}")
            pos = self.data.get("al_cache_position", 0)
            self.data["al_cache_position"] = pos + 1
            labels_this_round = self.data.get("al_labels_this_round", 0) + 1
            self.data["al_labels_this_round"] = labels_this_round
            retrain_every = self._get_setting("retrain_every", 10)
            if labels_this_round >= retrain_every and label_id and not self.data.get("al_task_id"):
                self._trigger_retrain(label_id)
            return 0

        if action == "change_label":
            # Only available when label was not pre-configured in params
            if not self.params.get("label_id"):
                self.data.pop("al_label_id", None)
                self.data.pop("al_task_id", None)
                self.data.pop("al_cache", None)
                self.data.pop("al_cache_position", None)
                self.data.pop("al_metrics", None)
                self.data["al_round"] = 0
                self.data["al_labels_this_round"] = 0
            return 0

        if action == "prev_entry":
            pos = self.data.get("al_cache_position", 0)
            self.data["al_cache_position"] = max(0, pos - 1)
            return 0

        if action == "skip":
            pos = self.data.get("al_cache_position", 0)
            self.data["al_cache_position"] = pos + 1
            return 0

        if action == "finish":
            return 1

        if action == "prev":
            return -1

        return 0
