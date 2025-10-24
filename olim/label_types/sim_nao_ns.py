from flask import render_template

LABEL_TYPE = "sim_nao_ns"

# Label configuration - similar to the original LabelTypes.SIM_NAO_NS
LABEL_CONFIG = [
    ("sim", "icon", "check-circle-fill", "green"),
    ("não", "icon", "x-circle-fill", "red"),
    ("não sei", "text", "?", "orange"),
]


def render(label, entry, labels_values, hidden_labels, show_hidden, valid_entry, **kwargs) -> str:
    """Render the sim/não/não sei label type"""
    return render_template(
        "label_types/sim_nao_ns.html",
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
