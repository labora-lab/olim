"""Label type modules for OLIM."""

from . import (
    check,
    free_text,
    multiple_choice,
    sim_nao,
    sim_nao_ns,
    yes_no,
    yes_no_idk,
    yes_no_unknown,
)

__all__ = [
    "check",
    "free_text",
    "multiple_choice",
    "sim_nao",
    "sim_nao_ns",
    "yes_no",
    "yes_no_idk",
    "yes_no_unknown",
]

# Mapping of label type identifiers to their modules
_LABEL_TYPE_MAP = {
    "sim_nao": sim_nao,
    "sim_nao_ns": sim_nao_ns,
    "yes_no": yes_no,
    "check": check,
    "yes_no_unknown": yes_no_unknown,
    "yes_no_idk": yes_no_idk,
    "free_text": free_text,
    "multiple_choice": multiple_choice,
}


def get_label_type_module(label_type):
    """Get the module for a specific label type"""
    return _LABEL_TYPE_MAP.get(label_type, sim_nao)


def get_available_label_types():
    """Get all available label types"""
    return [
        ("sim_nao", "Sim/Não"),
        ("sim_nao_ns", "Sim/Não/Não Sei"),
        ("yes_no", "Yes/No"),
        ("check", "Check"),
        ("yes_no_unknown", "Yes/No/Unknown"),
        ("yes_no_idk", "Yes/No/Don't Know"),
        ("free_text", "Free Text"),
        ("multiple_choice", "Multiple Choice"),
    ]


def is_free_text_label(label_type):
    """Check if a label type is free text"""
    if label_type == "free_text":
        module = get_label_type_module(label_type)
        return hasattr(module, 'is_free_text') and module.is_free_text()
    return False
