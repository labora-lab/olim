"""Label type modules for OLIM."""

from types import ModuleType

from . import (
    check,
    free_text,
    long_text,
    multiple_choice,
    short_text,
    sim_nao,
    sim_nao_ns,
    yes_no,
    yes_no_idk,
    yes_no_unknown,
)

__all__ = [
    "check",
    "free_text",
    "long_text",
    "multiple_choice",
    "short_text",
    "sim_nao",
    "sim_nao_ns",
    "yes_no",
    "yes_no_idk",
    "yes_no_unknown",
]

_LABEL_TYPE_MAP = {
    "sim_nao": sim_nao,
    "sim_nao_ns": sim_nao_ns,
    "yes_no": yes_no,
    "check": check,
    "yes_no_unknown": yes_no_unknown,
    "yes_no_idk": yes_no_idk,
    "free_text": free_text,
    "multiple_choice": multiple_choice,
    "short_text": short_text,
    "long_text": long_text,
}

_FREE_TEXT_TYPES = {"free_text", "short_text", "long_text"}
_CONFIGURABLE_TYPES = {"multiple_choice"}


def get_label_type_module(label_type) -> ModuleType:
    return _LABEL_TYPE_MAP.get(label_type, sim_nao)


def get_available_label_types() -> list[tuple[str, str]]:
    return [
        ("sim_nao", "Sim/Não"),
        ("sim_nao_ns", "Sim/Não/Não Sei"),
        ("yes_no", "Yes/No"),
        ("check", "Check"),
        ("yes_no_unknown", "Yes/No/Unknown"),
        ("yes_no_idk", "Yes/No/Don't Know"),
        ("multiple_choice", "Multiple Choice"),
        ("free_text", "Free Text"),
        ("short_text", "Short Text"),
        ("long_text", "Long Text"),
    ]


def is_free_text_label(label_type) -> bool:
    return label_type in _FREE_TEXT_TYPES


def is_configurable_label(label_type) -> bool:
    return label_type in _CONFIGURABLE_TYPES


def get_preset_settings(label_type) -> dict | None:
    module = _LABEL_TYPE_MAP.get(label_type)
    if module and hasattr(module, "PRESET_SETTINGS"):
        return module.PRESET_SETTINGS
    return None
