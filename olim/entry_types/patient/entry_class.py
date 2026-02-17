"""PatientEntry class implementation for the patient entry type.

This module provides the class-based implementation for patient entries,
delegating to the existing module functions for backward compatibility.
"""

from typing import Any

import pandas as pd

from ..base import EntryTypeBase
from ..registry import register_entry_type
from . import (
    extract as extract_module,
    hidden as hidden_module,
    render as render_module,
    search as search_module,
)
from .commands import COMMANDS


@register_entry_type
class PatientEntry(EntryTypeBase):
    """Patient medical record entry type with timeline and hiding functionality."""

    entry_type = "patient"
    template_path = "entry_types/patient.html"
    supports_hiding = True
    custom_commands = COMMANDS

    def render(self, entry_id: str, **kwargs: Any) -> str:  # noqa: ANN401
        """Render patient entry HTML with timeline and hiding controls.

        Delegates to existing render module for backward compatibility.
        """
        return render_module.render(entry_id, **kwargs)  # type: ignore[attr-defined]

    def extract_texts(self, entry_id: str, **kwargs) -> pd.DataFrame:
        """Extract patient text content for ML/export.

        Delegates to existing extract module for backward compatibility.

        Args:
            entry_id: Unique patient identifier
            **kwargs: May include only_ids, only_values parameters
        """
        only_ids = kwargs.get("only_ids", False)
        only_values = kwargs.get("only_values", False)
        return extract_module.extract_texts(entry_id, only_ids, only_values)

    def search(
        self,
        must_terms: list[str],
        must_phrases: list[str],
        not_must_terms: list[str],
        not_must_phrases: list[str],
        number: int,
        **kwargs: Any,  # noqa: ANN401
    ) -> list[dict]:
        """Search patient entries via Elasticsearch.

        Delegates to existing search module for backward compatibility.

        Note: Patient search does not use dataset_id parameter.
        """
        return search_module.search(  # type: ignore[attr-defined]
            must_terms, must_phrases, not_must_terms, not_must_phrases, number
        )

    def get_all_hidden(self, project_id: int) -> list[dict]:
        """Get all hidden patient entries for a project.

        Delegates to existing hidden module for backward compatibility.
        """
        return hidden_module.get_all_hidden(project_id)

    def have_hidden(self) -> bool:
        """Check if patient entry type has hidden entries.

        Delegates to existing hidden module for backward compatibility.
        """
        return hidden_module.have_hidden()
