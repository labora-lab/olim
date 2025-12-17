from collections.abc import Generator
from typing import Any

import pandas as pd
from flask import render_template
from tqdm import tqdm

from olim.settings import ES_INDEX
from olim.utils.es import es_search

from .base import EntryTypeBase
from .registry import register_entry_type
from .single_text import SingleTextEntry

ENTRY_TYPE = "text_pdf_url"
SHOW_METADATA = False


@register_entry_type
class TextPdfUrlEntry(EntryTypeBase):
    """Text entry with embedded PDF viewer."""

    entry_type = "text_pdf_url"
    template_path = "entry_types/text_pdf_url.html"
    show_metadata = False

    def __init__(self):
        """Initialize with delegation to SingleTextEntry for shared functionality."""
        super().__init__()
        self._single_text = SingleTextEntry()

    def render(self, entry_id: str, **kwargs) -> str:
        """Render entry HTML with text and embedded PDF viewer."""
        dataset_id = kwargs.get("dataset_id")
        if not dataset_id:
            raise ValueError("dataset_id required for text_pdf_url entries")

        query = {"bool": {"must": [{"terms": {"_id": [entry_id]}}]}}
        res = es_search(query=query, index=ES_INDEX.format(dataset_id=dataset_id))["hits"]["hits"][
            0
        ]

        return render_template(
            self.template_path, res=res, show_metadata=self.show_metadata, **kwargs
        )

    def extract_texts(self, entry_id: str, **kwargs) -> pd.DataFrame:
        """Delegate to single_text implementation."""
        return self._single_text.extract_texts(entry_id, **kwargs)

    def search(
        self,
        must_terms: list[str],
        must_phrases: list[str],
        not_must_terms: list[str],
        not_must_phrases: list[str],
        number: int,
        **kwargs,
    ) -> list[dict]:
        """Delegate to single_text implementation."""
        return self._single_text.search(
            must_terms, must_phrases, not_must_terms, not_must_phrases, number, **kwargs
        )

    def generate_upload_batches(
        self,
        filename: str,
        id_column: str,
        text_column: str,
        batch_size: int = 1000,
        **kwargs,
    ) -> Generator[list[dict[str, Any]]]:
        """Generate batches of records with text and PDF URL."""
        pdf_url_column = kwargs.get("pdf_url_column")
        if not pdf_url_column:
            raise ValueError("pdf_url_column required for text_pdf_url upload")

        # Read in chunks
        for chunk in tqdm(pd.read_csv(filename, chunksize=batch_size)):
            # Clean chunk
            chunk = chunk.drop_duplicates(subset=[id_column])
            chunk = chunk.fillna(-1)

            try:
                if "date" in chunk:
                    chunk["date"] = pd.to_datetime(chunk["date"], format="mixed")
            except Exception as e:
                print(f"Failed to convert column dates to datetime: {e!s}")

            # Convert to records
            records = chunk.to_dict("records")
            batch_entries = []
            seen_ids = set()

            for record in records:
                # Skip duplicates
                record_id = record.get(id_column)
                if not record_id or record_id in seen_ids:
                    print(f"Duplicated data on dataset id: {record_id}")
                    continue
                seen_ids.add(record_id)

                # Extract text content and PDF URL
                text_content = record.get(text_column, "")
                pdf_url = record.get(pdf_url_column, "")

                # Create metadata from other columns
                metadata = {}
                for key, value in record.items():
                    # Skip id/text columns and empty values (include pdf_url in metadata)
                    if key in [id_column, text_column]:
                        continue
                    if pd.isna(value) or value == "" or value == -1:
                        continue

                    # Rename reserved "text" field to avoid overwriting the main text
                    if key == "text":
                        key = "metadata_text"

                    metadata[key] = value

                # Ensure pdf_url is in metadata
                if pdf_url:
                    metadata["pdf_url"] = str(pdf_url)

                # Create structured entry
                batch_entries.append(
                    {"id": str(record_id), "text": str(text_content), "metadata": metadata}
                )

            yield batch_entries


# ============================================================================
# Backward Compatibility Layer
# ============================================================================

_instance: TextPdfUrlEntry | None = None


def _get_instance() -> TextPdfUrlEntry:
    """Get singleton instance of TextPdfUrlEntry for backward compatibility."""
    global _instance
    if _instance is None:
        _instance = TextPdfUrlEntry()
    return _instance


def render(entry_id: str, dataset_id: int, **pars) -> str:
    """Legacy function wrapper - calls class method."""
    return _get_instance().render(entry_id, dataset_id=dataset_id, **pars)


def generate_upload_batches(
    filename: str,
    id_column: str,
    text_column: str,
    pdf_url_column: str,
    batch_size: int = 1000,
    **kwargs,
) -> Generator[list[dict[str, Any]]]:
    """Legacy function wrapper - calls class method."""
    return _get_instance().generate_upload_batches(
        filename, id_column, text_column, batch_size, pdf_url_column=pdf_url_column, **kwargs
    )


# Re-export single_text functions for backward compatibility
from .single_text import extract_texts, search  # noqa: E402, F401
