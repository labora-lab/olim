from flask import render_template

LABEL_TYPE = "yes_no"

# Label configuration - similar to the original LabelTypes.YES_NO
LABEL_CONFIG = [
    ("yes", "icon", "check-circle-fill", "green"),
    ("no", "icon", "x-circle-fill", "red"),
]


def render(label, entry, labels_values, hidden_labels, show_hidden, valid_entry, **kwargs):
    """Render the yes/no label type"""
    return render_template(
        "label_types/yes_no.html",
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