import json

from flask import render_template

LABEL_TYPE = "multiple_choice"

# Default placeholder config - actual options come from label_settings
LABEL_CONFIG = [
    ("option_1", "text", "1", "blue"),
    ("option_2", "text", "2", "blue"),
    ("option_3", "text", "3", "blue"),
]

#   How to Use:

#   1. Create a label with multiple choice type:

#   When creating a label through the UI or API, set:
#   - Label Type: multiple_choice
#   - Label Settings (JSON):
#   {
#     "options": [
#       {"value": "Option 1", "color": "blue", "icon": "1", "type": "text"},
#       {"value": "Option 2", "color": "green", "icon": "2", "type": "text"},
#       {"value": "Option 3", "color": "red", "icon": "3", "type": "text"}
#     ]
#   }

#   Or use simple strings:
#   {
#     "options": ["Fever", "Cough", "Headache", "Fatigue"]
#   }

#   2. Data Storage:

#   The selected values are stored in LabelEntry.value as a JSON string:
#   ["Option 1", "Option 3"]

#   3. Example Usage:

#   For a medical annotation project, you might create a "Symptoms" label:
#   {
#     "options": [
#       {"value": "Fever", "color": "red"},
#       {"value": "Cough", "color": "orange"},
#       {"value": "Headache", "color": "yellow"},
#       {"value": "Nausea", "color": "green"},
#       {"value": "Fatigue", "color": "blue"}
#     ]
#   }


def render(label, entry, labels_values, hidden_labels, show_hidden, valid_entry, **kwargs) -> str:
    """Render the multiple choice label type"""
    # Get options from label settings if available
    label_options = []
    if label.label_settings and "options" in label.label_settings:
        options = label.label_settings["options"]
        # Convert options to the format expected by the template
        # Each option: (value, type, icon, color)
        for i, option in enumerate(options):
            if isinstance(option, dict):
                # Support for {value: "name", color: "blue", icon: "check"}
                label_options.append(
                    (
                        option.get("value", f"option_{i}"),
                        option.get("type", "text"),
                        option.get("icon", str(i + 1)),
                        option.get("color", "blue"),
                    )
                )
            else:
                # Simple string option
                label_options.append((str(option), "text", str(i + 1), "blue"))
    else:
        # Use default config if no options configured
        label_options = LABEL_CONFIG

    # Parse the current selected values (stored as JSON list)
    selected_values = []
    current_value = labels_values.get(label.id)
    if current_value:
        try:
            selected_values = json.loads(current_value)
            if not isinstance(selected_values, list):
                selected_values = [current_value]
        except (json.JSONDecodeError, TypeError):
            # If not valid JSON, treat as single value
            selected_values = [current_value] if current_value else []

    return render_template(
        "label_types/multiple_choice.html",
        label=label,
        entry=entry,
        labels_values=labels_values,
        hidden_labels=hidden_labels,
        show_hidden=show_hidden,
        valid_entry=valid_entry,
        label_config=label_options,
        selected_values=selected_values,
        **kwargs,
    )


def get_label_options() -> list:
    """Get the available options for this label type"""
    return LABEL_CONFIG


def is_multiple_choice() -> bool:
    """Indicates this is a multiple choice label type"""
    return True
