from flask import render_template

LABEL_TYPE = "check"

# Label configuration - similar to the original LabelTypes.CHECK
LABEL_CONFIG = [
    ("check", "icon", "check-circle-fill", "green"),
]


def render(label, entry, labels_values, hidden_labels, show_hidden, valid_entry, **kwargs) -> str:
    """Render the check label type"""
    return render_template(
        "label_types/check.html",
        label=label,
        entry=entry,
        labels_values=labels_values,
        hidden_labels=hidden_labels,
        show_hidden=show_hidden,
        valid_entry=valid_entry,
        label_config=LABEL_CONFIG,
        **kwargs,
    )


def get_label_options() -> list:
    """Get the available options for this label type"""
    return LABEL_CONFIG
