from collections.abc import Generator
from typing import Any

import pandas as pd
from flask import render_template
from tqdm import tqdm

from olim.settings import ES_INDEX
from olim.utils.es import es_search

ENTRY_TYPE = "single_text"


def render(entry_id: str, dataset_id: int, **pars) -> str:
    query = {"bool": {"must": [{"terms": {"_id": [entry_id]}}]}}
    res = es_search(query=query, index=ES_INDEX.format(dataset_id=dataset_id))["hits"]["hits"][0]

    return render_template("entry_types/single_text.html", res=res, **pars)


def extract_texts(entry_id: str, dataset_id: int, **pars) -> pd.DataFrame:
    query = {"bool": {"must": [{"terms": {"_id": [entry_id]}}]}}
    res = es_search(query=query, index=ES_INDEX.format(dataset_id=dataset_id))["hits"]["hits"][0]
    return pd.DataFrame({"entry_id": [entry_id], "text": res["_source"]["text"]})


def generate_upload_batches(
    filename: str,
    id_column: str,
    text_column: str,
    batch_size: int = 1000,
    **__,
) -> Generator[list[dict[str, Any]]]:
    """Generate batches of records with structured metadata

    Yields batches in the format:
    [
        {
            "id": "entry_123",
            "text": "Text content here",
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

            # Extract text content
            text_content = record.get(text_column, "")

            # Create metadata from other columns
            metadata = {}
            for key, value in record.items():
                # Skip id/text columns and empty values
                if key in [id_column, text_column]:
                    continue
                if pd.isna(value) or value == "" or value == -1:
                    continue

                # # Convert pandas types to native
                # if pd.api.types.is_datetime64_any_dtype(value):
                #     value = value.to_pydatetime()
                # elif pd.api.types.is_timedelta64_dtype(value):
                #     value = value.to_pytimedelta()
                # elif pd.api.types.is_float_dtype(value) and value.is_integer():
                #     value = int(value)

                metadata[key] = value

            # Create structured entry
            batch_entries.append(
                {"id": str(record_id), "text": str(text_content), "metadata": metadata}
            )

        yield batch_entries


def search(
    must_terms: list[str],
    must_phrases: list[str],
    not_must_terms: list[str],
    not_must_phrases: list[str],
    number: int,
    dataset_id: int,
) -> list[dict]:
    all_must = must_terms + must_phrases
    all_not = not_must_terms + not_must_phrases
    col_search = "text"

    # Create query
    es_query = {
        "bool": {
            "must": [
                {"query_string": {"query": term, "fields": [col_search]}} for term in all_must
            ],
            "must_not": [
                {"query_string": {"query": term, "fields": [col_search]}} for term in all_not
            ],
            "should": [],
        },
    }

    # Runs query
    results = es_search(query=es_query, size=number, index=ES_INDEX.format(dataset_id=dataset_id))[
        "hits"
    ]["hits"]

    # Aggregates results
    patients = []
    for patient in results:
        text = patient["_source"]["text"]
        try:
            patient_desc = " ".join(text.split(" ")[:5]) + "..."
        except IndexError:
            patient_desc = text
        count = sum([text.lower().count(term.lower()) for term in all_must])
        patients.append(
            {
                "entry_id": patient["_id"],
                "match_count": count,
                "description": patient_desc,
                "score": patient["_score"],
                "type": ENTRY_TYPE,
            }
        )

    return patients
