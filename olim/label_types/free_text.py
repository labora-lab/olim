from flask import render_template

LABEL_TYPE = "free_text"

# Free text doesn't have predefined options, but we return a placeholder for compatibility
LABEL_CONFIG = [
    ("free", "text", "", "blue"),  # Placeholder for free text
]


def render(label, entry, labels_values, hidden_labels, show_hidden, valid_entry, **kwargs) -> str:
    """Render the free text label type"""
    return render_template(
        "label_types/free_text.html",
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


def is_free_text() -> bool:
    """Indicates this is a free text label type"""
    return True
