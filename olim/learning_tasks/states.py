import json
from typing import Any

from flask import render_template
from flask_babel import _

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

    def __init__(self, data: dict[str, Any], params: dict[str, Any] | None = None):
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

    def validate_field(self, field: dict, value: Any) -> str | None:
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
                    return _("{label} must be at least {min}").format(
                        label=label, min=field["min"]
                    )
                if "max" in field and num_value > field["max"]:
                    return _("{label} must be at most {max}").format(
                        label=label, max=field["max"]
                    )
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
