import json

from flask import render_template, url_for

LABEL_TYPE = "multiple_choice"

LABEL_CONFIG = [
    ("option_1", "text", "1", "blue"),
    ("option_2", "text", "2", "blue"),
    ("option_3", "text", "3", "blue"),
]


def _resolve_settings(label, override: dict | None = None) -> dict:
    """Return effective settings: override > label.label_settings > empty dict."""
    if override:
        return override
    if label.label_settings and label.label_settings.get("options"):
        return label.label_settings
    return {}


def _build_label_options(settings: dict) -> list[tuple]:
    """Convert settings["options"] to (value, type, icon, color) tuples."""
    options = settings.get("options", [])
    result = []
    for i, opt in enumerate(options):
        if isinstance(opt, dict):
            result.append(
                (
                    opt.get("value", f"option_{i}"),
                    opt.get("type", "text"),
                    opt.get("icon", str(i + 1)),
                    opt.get("color", "blue"),
                )
            )
        else:
            result.append((str(opt), "text", str(i + 1), "blue"))
    return result or LABEL_CONFIG


def render(
    label,
    entry,
    labels_values,
    hidden_labels,
    show_hidden,
    valid_entry,
    _preset_settings=None,
    **kwargs,
) -> str:
    settings = _resolve_settings(label, _preset_settings)
    label_options = _build_label_options(settings)
    single_select = settings.get("single_select", False)
    items_per_line = settings.get("items_per_line", 2)
    helper_map = {
        opt.get("value", ""): opt.get("helper", "")
        for opt in settings.get("options", [])
        if isinstance(opt, dict)
    }

    selected_values = []
    current_value = labels_values.get(label.id)
    if current_value:
        try:
            parsed = json.loads(current_value)
            selected_values = parsed if isinstance(parsed, list) else [current_value]
        except (json.JSONDecodeError, TypeError):
            selected_values = [current_value]

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
        single_select=single_select,
        items_per_line=items_per_line,
        helper_map=helper_map,
        **kwargs,
    )


def get_label_options(label=None) -> list:
    if label is not None:
        settings = _resolve_settings(label)
        if settings:
            return _build_label_options(settings)
    return LABEL_CONFIG


def is_multiple_choice() -> bool:
    return True


def render_config(label) -> str | None:
    """Render the settings-page config editor for this label."""
    return render_template(
        "label_types/multiple_choice_config.html",
        label=label,
        settings=label.label_settings or {},
        save_url=url_for("update_label_type_settings", label_id=label.id),
        is_edit=True,
    )


def render_creation_config() -> str | None:
    """Render the creation-form inline config panel (empty, for new labels)."""
    return render_template(
        "label_types/multiple_choice_config.html",
        label=None,
        settings={},
        save_url=None,
        is_edit=False,
    )
