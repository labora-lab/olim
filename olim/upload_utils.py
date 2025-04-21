from collections.abc import Callable
from typing import Any

import pandas as pd
from elasticsearch import helpers
from tqdm import tqdm

from .database import register_entries
from .settings import ES_SERVER
from .utils.es import get_es_conn


def es_bulk_upload(
    csv_file: str,
    id_column: str,
    text_column: str | None,
    index: str,
    mapping: dict[str, Any],
    doc_generator: Callable,
    entry_type: str,
    additional_indexes=None,
) -> None:
    """Upload bulk data to elasticsearch and register entries in database

    Args:
        csv_file: Path to CSV file with data
        id_column: Name of ID column in CSV
        text_column: Name of text column in CSV
        index: Elasticsearch index name
        mapping: Elasticsearch mapping for index
        doc_generator: Function to generate documents
        entry_type: Type of entry
        additional_indexes: Additional indexes to create
    """
    if additional_indexes is None:
        additional_indexes = []

    es = get_es_conn(
        hosts=ES_SERVER,
        request_timeout=1000,
        read_timeout=1000,
        timeout=1000,
        max_retries=20,
    )

    print(f"Trying to create {index} index...")
    try:
        es.indices.create(index=index, mappings=mapping)
    except Exception:
        print("Index creation failed, index already exists?")

    for ind, mp in additional_indexes:
        print(f"Trying to create {ind} additional index...")
        try:
            es.indices.create(index=ind, mappings=mp)
        except Exception:
            print("Index creation failed, index already exists?")

    print(f"Loading data from {csv_file}...")
    df = pd.read_csv(csv_file)
    df = df.drop_duplicates()
    df = df.fillna(-1)
    if "date" in df:
        df["date"] = pd.to_datetime(df["date"], format="mixed")

    print("Uploading texts to ElasticSearch...")
    helpers.bulk(es, doc_generator(df, index, id_column, text_column))

    print("Registring entries on OLIM database...")
    batch_size = 1000
    n_batches = int(len(df) / batch_size)
    for i in tqdm(range(0, n_batches + 1)):
        if i == n_batches:
            register_entries(df[id_column][i * batch_size :].tolist(), entry_type)  # type: ignore [pandas is weird]
        else:
            register_entries(
                df[id_column][i * batch_size : (i + 1) * batch_size].tolist(),  # type: ignore [pandas is weird]
                entry_type,
            )

    print()
    print("Data uploaded!")
