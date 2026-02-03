import pandas as pd
from flask import render_template

from .base import EntryTypeBase
from .registry import register_entry_type

ENTRY_TYPE = "pdf"


@register_entry_type
class PdfEntry(EntryTypeBase):
    """PDF document entry type."""

    entry_type = "pdf"
    template_path = "entry_types/pdf.html"

    def render(self, entry_id: str, **kwargs) -> str:
        """Render PDF entry HTML for display."""
        return render_template(self.template_path, filename=entry_id, **kwargs)

    def extract_texts(self, entry_id: str, **kwargs) -> pd.DataFrame:
        """Extract filename for PDF entries."""
        return pd.DataFrame({"entry_id": [entry_id], "filename": [str(entry_id) + ".pdf"]})


# ============================================================================
# Backward Compatibility Layer
# ============================================================================

_instance: PdfEntry | None = None


def _get_instance() -> PdfEntry:
    """Get singleton instance of PdfEntry for backward compatibility."""
    global _instance
    if _instance is None:
        _instance = PdfEntry()
    return _instance


def render(entry_id, **pars) -> str:
    """Legacy function wrapper - calls class method."""
    return _get_instance().render(entry_id, **pars)


def extract_texts(entry_id) -> pd.DataFrame:
    """Legacy function wrapper - calls class method."""
    return _get_instance().extract_texts(entry_id)
