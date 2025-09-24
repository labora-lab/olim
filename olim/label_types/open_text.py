from flask import render_template

LABEL_TYPE = "open_text"

# Open text doesn't have predefined options, but we return a placeholder for compatibility
LABEL_CONFIG = [
    ("open", "text", "", "blue"),  # Placeholder for open text
]


def render(label, entry, labels_values, hidden_labels, show_hidden, valid_entry, **kwargs):
    """Render the open text label type"""
    return render_template(
        "label_types/open_text.html",
        label=label,
        entry=entry,
        labels_values=labels_values,
        hidden_labels=hidden_labels,
        show_hidden=show_hidden,
        valid_entry=valid_entry,
        label_config=LABEL_CONFIG,
        **kwargs
    )


def get_label_options():
    """Get the available options for this label type"""
    return LABEL_CONFIG


def is_open_text():
    """Indicates this is an open text label type"""
    return True