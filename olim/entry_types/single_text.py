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

                # Rename reserved "text" field to avoid overwriting the main text
                if key == "text":
                    key = "metadata_text"

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
    col_search = "text"

    # Build OR conditions for must clauses
    should_clauses = [
        *[{"match": {col_search: term}} for term in must_terms],
        *[{"match_phrase": {col_search: phrase}} for phrase in must_phrases],
    ]

    # Build AND conditions for must_not clauses
    must_not_clauses = [
        *[{"match": {col_search: term}} for term in not_must_terms],
        *[{"match_phrase": {col_search: phrase}} for phrase in not_must_phrases],
    ]

    # Create query with OR logic for must and AND for must_not
    es_query = {"bool": {"must_not": must_not_clauses}}

    if should_clauses:
        # OR logic: at least one should clause must match
        es_query["bool"]["should"] = should_clauses
        es_query["bool"]["minimum_should_match"] = 1  # type: ignore
    else:
        # If no must conditions, match all documents that don't match must_not
        es_query["bool"]["must"] = [{"match_all": {}}]

    # Execute query
    results = es_search(query=es_query, size=number, index=ES_INDEX.format(dataset_id=dataset_id))[
        "hits"
    ]["hits"]

    # Process results (unchanged from original)
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
