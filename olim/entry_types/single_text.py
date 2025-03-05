from collections.abc import Generator

import click
import pandas as pd
from flask import render_template
from tqdm import tqdm

from ..cli import upload
from ..functions import es_bulk_upload, es_search

ES_INDEX = "single_text_entries"
ENTRY_TYPE = "single_text"


def render(entry_id, **pars) -> str:
    query = {"bool": {"must": [{"terms": {"_id": [entry_id]}}]}}
    res = es_search(query=query, index=ES_INDEX)["hits"]["hits"][0]

    return render_template("entry_types/single_text.html", res=res, **pars)


def extract_texts(entry_id, **pars) -> pd.DataFrame:
    query = {"bool": {"must": [{"terms": {"_id": [entry_id]}}]}}
    res = es_search(query=query, index=ES_INDEX)["hits"]["hits"][0]
    return pd.DataFrame({"entry_id": [entry_id], "text": res["_source"]["text"]})


@click.command(
    ENTRY_TYPE,
    help="Upload data of the single_text type."
    "\n\n\tCSV_FILE\tPath to the CSV file to load data."
    "\n\n\tID_COLUMN\tColumn name to use as id for the entries (must be unique with all other entries in OLIM)."  # noqa: E501
    "\n\n\tTEXT_COLUMN\tColumn name to use as the text.",
)
@click.argument("csv_file", type=click.Path(exists=True))
@click.argument("id_column")
@click.argument("text_column")
def up_single_text(csv_file, id_column, text_column) -> None:
    mapping = {"properties": {"texts": {"type": "text"}}}

    def doc_generator(df, index, id_column, text_column) -> Generator[dict, None, None]:
        for _, row in tqdm(df.iterrows(), total=len(df)):
            data = {
                "_index": index,
                "_id": f"{row[id_column]}",
                "_source": {"text": row[text_column]},
            }
            for col in row.index:
                if col != text_column:
                    data["_source"][col] = row[col]
            yield data

    es_bulk_upload(
        csv_file,
        id_column,
        text_column,
        ES_INDEX,
        mapping,
        doc_generator,
        ENTRY_TYPE,
    )


upload.add_command(up_single_text)


def search(
    must_terms: list[str],
    must_phrases: list[str],
    not_must_terms: list[str],
    not_must_phrases: list[str],
    number: int,
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
    results = es_search(query=es_query, size=number, index=ES_INDEX)["hits"]["hits"]

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
