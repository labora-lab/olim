import json
from typing import Any

import requests
from flask import render_template, session
from flask_babel import _

from ..celery_app import launch_task_with_tracking
from ..database import get_entry, get_labels, new_queue, random_entries
from ..functions import render_entry
from ..tasks.learning_tasks import label_queue_with_llm
from . import register_state
from .base import BaseState


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
            import re

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
                import re

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

    def render(self) -> str:
        available_labels = self._get_available_labels()
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
            entry_ids_text=self.data.get("_queue_ids_text", ""),
            entry_source=self.data.get("_entry_source", "manual"),
            random_count=self.data.get("_random_count", 10),
            completion_mode=self.data.get("queue_completion_mode", "any"),
            errors=self.errors,
            show_prev=self.params.get("show_prev", True),
            is_last_step=self.params.get("is_last_step", False),
        )

    def handle(self, action: str, payload: dict[str, Any]) -> int:
        if action == "prev":
            return -1

        if action == "submit":
            self.errors = {}
            entry_source = payload.get("entry_source", "manual")
            self.data["_entry_source"] = entry_source

            if entry_source == "random":
                # Random entries
                project_id = self.params.get("_project_id")
                try:
                    count = int(payload.get("random_count", 10))
                    self.data["_random_count"] = count
                except (ValueError, TypeError):
                    self.errors["random_count"] = _("Please enter a valid number")
                    return 0

                if count < 1:
                    self.errors["random_count"] = _("Must be at least 1")
                    return 0

                entries = list(random_entries(count, project_id))
                if not entries:
                    self.errors["random_count"] = _("No entries found in this project")
                    return 0

                entry_ids = [e.entry_id for e in entries]
            else:
                # Manual entry IDs
                ids_text = payload.get("entry_ids", "").strip()
                self.data["_queue_ids_text"] = ids_text

                if not ids_text:
                    self.errors["entry_ids"] = _("Please enter at least one entry ID")
                    return 0

                separator = self.params.get("id_separator", "newline")
                if separator == "comma":
                    raw_ids = [x.strip() for x in ids_text.split(",")]
                elif separator == "space":
                    raw_ids = ids_text.split()
                else:  # newline
                    raw_ids = [x.strip() for x in ids_text.splitlines()]

                entry_ids = [eid for eid in raw_ids if eid]

                if not entry_ids:
                    self.errors["entry_ids"] = _("Please enter at least one entry ID")
                    return 0

            # Get selected labels
            available_labels = self._get_available_labels()
            if self.params.get("allow_label_selection", True):
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

    def render(self) -> str:
        available_labels = self._get_available_labels()
        selected_label_ids = self.data.get("queue_labels", [])
        if selected_label_ids:
            selected_label_ids = [lbl["id"] for lbl in selected_label_ids]

        # Check for pre-selected labels in params (for automation)
        if not selected_label_ids and "labels" in self.params:
            selected_label_ids = self.params["labels"]
            # Auto-select all if empty array
            if not selected_label_ids and available_labels:
                selected_label_ids = [lbl["id"] for lbl in available_labels]

        # Detect automation mode - auto-submit if all required params are provided
        # and we haven't already attempted auto-submit
        auto_submit = (
            "entry_source" in self.params
            and "ollama_url" in self.params
            and "labels" in self.params
            and not self.data.get("_auto_submitted_queue_setup")  # Only auto-submit once
        )

        return render_template(
            "learning_tasks/ollama_queue_setup.html",
            title=self.params.get("title", _("Setup Auto-Labeling Queue")),
            description=self.params.get("description", ""),
            available_labels=available_labels,
            selected_label_ids=selected_label_ids,
            entry_ids_text=self.data.get("_queue_ids_text", ""),
            entry_source=self.data.get("_entry_source", self.params.get("entry_source", "random")),
            random_count=self.data.get("_random_count", self.params.get("random_count", 10)),
            ollama_url=self.data.get(
                "ollama_url", self.params.get("ollama_url", "http://localhost:11434/v1")
            ),
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
            self.data["_auto_submitted_queue_setup"] = True

            entry_source = payload.get("entry_source", self.params.get("entry_source", "random"))
            self.data["_entry_source"] = entry_source

            print(
                f"DEBUG OllamaQueueSetup.handle(submit): entry_source={entry_source}, "
                f"params={self.params.keys()}, "
                f"payload keys={payload.keys() if hasattr(payload, 'keys') else 'not a dict'}"
            )

            # Handle entry selection
            if entry_source == "random":
                # Random entries
                project_id = self.params.get("_project_id")
                try:
                    count = int(payload.get("random_count", self.params.get("random_count", 10)))
                    self.data["_random_count"] = count
                except (ValueError, TypeError):
                    self.errors["random_count"] = _("Please enter a valid number")
                    return 0

                if count < 1:
                    self.errors["random_count"] = _("Must be at least 1")
                    return 0

                entries = list(random_entries(count, project_id))
                if not entries:
                    self.errors["random_count"] = _("No entries found in this project")
                    return 0

                entry_ids = [e.entry_id for e in entries]
            else:
                # Manual entry IDs
                ids_text = payload.get("entry_ids", "").strip()
                self.data["_queue_ids_text"] = ids_text

                if not ids_text:
                    self.errors["entry_ids"] = _("Please enter at least one entry ID")
                    return 0

                raw_ids = [x.strip() for x in ids_text.splitlines()]
                entry_ids = [eid for eid in raw_ids if eid]

                if not entry_ids:
                    self.errors["entry_ids"] = _("Please enter at least one entry ID")
                    return 0

            # Get selected labels
            available_labels = self._get_available_labels()

            print(f"DEBUG OllamaQueueSetup: available_labels count={len(available_labels)}")

            # Check if labels are pre-selected in params (automation mode)
            if "labels" in self.params:
                selected_ids = self.params["labels"]
                print(f"DEBUG OllamaQueueSetup: labels from params={selected_ids}")
                # Auto-select all labels if empty array in automation mode
                if not selected_ids and available_labels:
                    selected_ids = [lbl["id"] for lbl in available_labels]
                    print(f"DEBUG OllamaQueueSetup: auto-selected all labels={selected_ids}")
            else:
                selected_ids = (
                    payload.getlist("labels")
                    if hasattr(payload, "getlist")
                    else payload.get("labels", [])
                )
                if isinstance(selected_ids, str):
                    selected_ids = [selected_ids]
                selected_ids = [int(x) for x in selected_ids if x]
                print(f"DEBUG OllamaQueueSetup: labels from payload={selected_ids}")

            if not selected_ids:
                print("DEBUG OllamaQueueSetup: ERROR - No labels selected")
                self.errors["labels"] = _("Please select at least one label")
                return 0

            selected_labels = [lbl for lbl in available_labels if lbl["id"] in selected_ids]

            if not selected_labels:
                print("DEBUG OllamaQueueSetup: ERROR - No matching labels found")
                self.errors["labels"] = _("No labels available")
                return 0

            print(f"DEBUG OllamaQueueSetup: Successfully selected {len(selected_labels)} labels")

            # Get Ollama URL
            ollama_url = payload.get(
                "ollama_url", self.params.get("ollama_url", "http://localhost:11434/v1")
            ).strip()

            if not ollama_url:
                self.errors["ollama_url"] = _("Ollama URL is required")
                return 0

            if not (ollama_url.startswith("http://") or ollama_url.startswith("https://")):
                self.errors["ollama_url"] = _("URL must start with http:// or https://")
                return 0

            # Store queue data
            self.data["queue_ids"] = entry_ids
            self.data["queue_labels"] = selected_labels
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
            "You are a precise labeling assistant. You MUST respond with ONLY the exact label value"
            " - nothing else. No explanations, no punctuation, no formatting."
        )
        default_prompt_template = """Classify this text for the label '{label_name}'.

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
            system_prompt = payload.get(
                "system_prompt",
                self.params.get(
                    "system_prompt", "You are a helpful assistant that accurately labels text data."
                ),
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
        from ..celery_app import app as celery_app

        task = celery_app.AsyncResult(task_id)

        print(f"DEBUG _get_task_status: task_id={task_id}, state={task.state}, info={task.info}")

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

            return render_template(
                "learning_tasks/ollama_auto_label.html",
                title=self.params.get("title", _("Auto-Labeling Complete")),
                mode="results",
                results=status["result"],
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
                task_id=task_id,
                is_last_step=self.params.get("is_last_step", False),
            )

    def handle(self, action: str, payload: dict[str, Any]) -> int:
        if action == "start":
            # Launch the Celery task
            task = launch_task_with_tracking(
                label_queue_with_llm,
                user_id=self.params["_user_id"],
                learning_task_id=self.params["_task_id"],
                label_configs=self.data["queue_labels"],
                datasets=[d.id for d in self.params["_datasets"]],
                project_id=self.params["_project_id"],
                ollama_url=self.data["ollama_url"],
                model=self.data["llm_model"],
                system_prompt=self.data["llm_system_prompt"],
                prompt_template=self.data["llm_prompt_template"],
            )
            self.data["llm_task_id"] = task.id
            print(f"DEBUG OllamaAutoLabel.handle(start): Launched task {task.id}")
            return 0  # Stay on this step to show progress

        if action == "retry":
            # Clear task ID to trigger re-launch
            self.data.pop("llm_task_id", None)
            self.data.pop("llm_results", None)
            return 0

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
            from flask import flash

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
