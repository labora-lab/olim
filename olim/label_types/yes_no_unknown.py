from flask import render_template

from . import multiple_choice

LABEL_TYPE = "yes_no_unknown"

PRESET_SETTINGS = {
    "options": [
        {
            "value": "yes",
            "type": "icon",
            "icon": "check-circle-fill",
            "color": "green",
            "helper": "",
        },
        {"value": "no", "type": "icon", "icon": "x-circle-fill", "color": "red", "helper": ""},
        {"value": "unknown", "type": "text", "icon": "?", "color": "gray", "helper": ""},
    ],
    "single_select": True,
    "items_per_line": 3,
}

LABEL_CONFIG = [(o["value"], o["type"], o["icon"], o["color"]) for o in PRESET_SETTINGS["options"]]


def render(label, entry, labels_values, hidden_labels, show_hidden, valid_entry, **kwargs) -> str:
    if not (label.label_settings and label.label_settings.get("options")):
        kwargs["_preset_settings"] = PRESET_SETTINGS
    return multiple_choice.render(
        label, entry, labels_values, hidden_labels, show_hidden, valid_entry, **kwargs
    )


def get_label_options(label=None) -> list:
    return LABEL_CONFIG


def render_config(label) -> str | None:
    return render_template("label_types/preset_config.html", label=label, preset=PRESET_SETTINGS)


def render_creation_config() -> str | None:
    return None
