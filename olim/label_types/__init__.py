"""Label type modules for OLIM."""

import json
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


def get_abstain_values(label_type, label=None) -> set[str]:
    """Values that record "the annotator could not decide" rather than a class.

    These are excluded from model training by default: "não sei" / "unknown" /
    "don't know" describe the annotator's state, not the text, so learning them as
    a class blurs the boundary between the classes that matter.

    For multiple_choice labels the flag lives on the configured option dict
    (``{"value": "...", "abstain": true}``).
    """
    module = _LABEL_TYPE_MAP.get(label_type)
    values: set[str] = set(getattr(module, "ABSTAIN_VALUES", set()))

    if label is not None:
        settings = getattr(label, "label_settings", None) or {}
        for opt in settings.get("options", []):
            if isinstance(opt, dict) and opt.get("abstain"):
                values.add(str(opt.get("value", "")))
    return values


def is_open_label(label_type) -> bool:
    """Whether this type's class values are open-ended rather than a fixed set.

    Preset types (sim_nao, yes_no, ...) declare their options in code, and
    multiple_choice declares them in the label's settings. Only when neither
    supplies a real option set is the annotated data the sole source of truth.
    """
    return label_type in _CONFIGURABLE_TYPES


def get_class_values(label, include_abstain: bool = False) -> list[str]:
    """The sorted class values a model for this label should predict.

    Read from the label's own configuration — the preset for a fixed type, or
    label_settings["options"] for a configurable one — so the class space is what
    the label declares rather than whatever happens to be in the database. That
    keeps a class nobody has annotated yet in the space (without it, the encoder
    maps predictions onto the wrong class name) and keeps a stray value from
    silently becoming a class of its own.

    Args:
        label: Label instance
        include_abstain: keep "don't know" style values as a trainable class

    Returns:
        Sorted class value strings; empty when the type declares no options.
    """
    label_type = getattr(label, "label_type", None)
    module = _LABEL_TYPE_MAP.get(label_type)
    if module is None or not hasattr(module, "get_label_options"):
        return []

    if is_open_label(label_type):
        # An unconfigured multiple_choice label reports placeholder options
        # ("option_1", ...). Those are not classes anyone annotated with, so report
        # no declaration and let the caller fall back to the annotated values.
        settings = getattr(label, "label_settings", None) or {}
        if not settings.get("options"):
            return []

    values = {opt[0] for opt in module.get_label_options(label)}
    if not include_abstain:
        values -= get_abstain_values(getattr(label, "label_type", None), label)
    return sorted(values)


def parse_label_value(raw) -> list[str]:
    """Decode a stored LabelEntry.value into the class values it stands for.

    The column holds two formats. The manual labelling UI serialises the selected
    options as a JSON array — `'["yes"]'` — because multiple_choice supports
    multi-select, and every non-free-text type renders through it. The active
    learning loop, the legacy /al route and the LLM auto-labeller each write a plain
    scalar — `'yes'`. Readers have to accept both or the same answer counts as two
    different classes depending on which screen recorded it.

    Returns:
        The selected values: empty for a cleared label, one entry for a single
        choice, several for a genuine multi-select.
    """
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(v) for v in raw]

    text = str(raw)
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, TypeError, ValueError):
        return [text]
    if isinstance(parsed, list):
        return [str(v) for v in parsed]
    # Valid JSON that is not a list (a value like "5" or "true") is still just the
    # class value it was written as.
    return [text]
