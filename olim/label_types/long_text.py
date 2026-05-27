from flask import render_template, url_for

LABEL_TYPE = "long_text"

LABEL_CONFIG = [("long_text", "text", "", "blue")]


def render(label, entry, labels_values, hidden_labels, show_hidden, valid_entry, **kwargs) -> str:
    settings = label.label_settings or {}
    return render_template(
        "label_types/long_text.html",
        label=label,
        entry=entry,
        labels_values=labels_values,
        hidden_labels=hidden_labels,
        show_hidden=show_hidden,
        valid_entry=valid_entry,
        rows=settings.get("rows", 4),
        **kwargs,
    )


def get_label_options(label=None) -> list:
    return LABEL_CONFIG


def is_free_text() -> bool:
    return True


def render_config(label) -> str | None:
    return render_template(
        "label_types/long_text_config.html",
        label=label,
        settings=label.label_settings or {},
        save_url=url_for("update_label_type_settings", label_id=label.id),
        is_edit=True,
    )


def render_creation_config() -> str | None:
    return render_template(
        "label_types/long_text_config.html",
        label=None,
        settings={},
        save_url=None,
        is_edit=False,
    )
