from collections.abc import Generator
from typing import Any

import pandas as pd
from flask import render_template
from tqdm import tqdm

from olim.settings import ES_INDEX
from olim.utils.es import es_search
from .single_text import extract_texts, search  # noqa: F401

ENTRY_TYPE = "text_pdf_url"
SHOW_METADATA = False


def render(entry_id: str, dataset_id: int, **pars) -> str:
    query = {"bool": {"must": [{"terms": {"_id": [entry_id]}}]}}
    res = es_search(query=query, index=ES_INDEX.format(dataset_id=dataset_id))["hits"]["hits"][0]

    return render_template("entry_types/text_pdf_url.html", res=res, show_metadata=SHOW_METADATA, **pars)


def generate_upload_batches(
    filename: str,
    id_column: str,
    text_column: str,
    pdf_url_column: str,
    batch_size: int = 1000,
    **__,
) -> Generator[list[dict[str, Any]]]:
    """Generate batches of records with text and PDF URL

    Yields batches in the format:
    [
        {
            "id": "entry_123",
            "text": "Text content here",
            "pdf_url": "https://example.com/document.pdf",
            "metadata": {
                "date": "2023-01-01",
                "source": "clinical notes",
                ...
            }
        },
        ...
    ]
    """
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

                metadata[key] = value

            # Ensure pdf_url is in metadata
            if pdf_url:
                metadata["pdf_url"] = str(pdf_url)

            # Create structured entry
            batch_entries.append(
                {
                    "id": str(record_id),
                    "text": str(text_content),
                    "metadata": metadata
                }
            )

        yield batch_entries