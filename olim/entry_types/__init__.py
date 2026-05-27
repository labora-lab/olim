from . import flexible_text, patient, pdf, single_text
from .registry import (
    get_entry_type_class,
    get_entry_type_instance,
    is_class_based,
    list_entry_types,
    register_entry_type,
)

# Backward compat: existing text_pdf_url DB entries render via flexible_text
text_pdf_url = flexible_text

__all__ = [
    "flexible_text",
    "get_entry_type_class",
    "get_entry_type_instance",
    "is_class_based",
    "list_entry_types",
    "patient",
    "pdf",
    "register_entry_type",
    "single_text",
    "text_pdf_url",
]
