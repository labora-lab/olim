## Auxiliary functions
# All functions here must have type hints and docstrings
from .settings import ES_INDEX, ES_LABEL_INDEX, ES_SERVER
from .database import register_entries
from . import tmp_dir
from elasticsearch import Elasticsearch, helpers
from flask import session
from datetime import datetime
from typing import List
import pandas as pd
import json
import os
import hashlib


def now_ISO():
    return datetime.now().isoformat()


def shorten(string: str, n: int = 80, add: str = " (...)") -> str:
    """Finds the first space after n characters and truncate the
        string there.

    Args:
        string (str): Original string.
        n (int): Minimum number of characters to prese¨
        str: Shortened string.
    """
    pos = string.find(" ", n)
    if pos != -1:
        return string[:pos] + add
    else:
        return string


def get_es_conn(**kwargs):
    pars = dict(
        hosts=ES_SERVER,
    )
    pars.update(kwargs)
    return Elasticsearch(**pars)


def get_index(kwargs):
    if "index" in kwargs:
        index = kwargs["index"]
    else:
        kwargs["index"] = ES_INDEX
        index = ES_INDEX
    return index, kwargs


def es_list_fields(**kwargs):
    index, kwargs = get_index(kwargs)
    client = get_es_conn()
    return list(
        client.indices.get_mapping(**kwargs)[index]["mappings"]["properties"].keys()
    )


def es_search(**kwargs):
    _, kwargs = get_index(kwargs)
    client = get_es_conn()
    return client.search(**kwargs)


def es_update(**kwargs):
    _, kwargs = get_index(kwargs)
    client = get_es_conn()
    return client.update(**kwargs)


def get_all_hidden():
    from .entry_types.patient import ES_TO_HIDE_INDEX

    client = get_es_conn()
    return client.search(
        index=ES_TO_HIDE_INDEX,
        query={"match_all": {}},
        size=10000,
    )[
        "hits"
    ]["hits"]


def parse_queue(text: str) -> List[str]:
    """Parse a queue input in to a queue list.

    Args:
        text (str): Queue input

    Returns:
        List[str]: Queue list
    """
    return (
        text.replace(";", " ")
        .replace(",", " ")
        .replace("\n", " ")
        .replace("\r\n", " ")
        .split()
    )


def store_queue(queue: List[str], highlight: List[str] = None) -> str:
    """Stores a queue in a temporay file.

    Args:
        queue (List[str]): Queue list

    Returns:
        str: Hash of the queue for access
    """
    queue = json.dumps(
        {
            "queue": list(queue),
            "highlight": highlight,
        }
    )
    h = hashlib.md5(queue.encode("utf-8")).hexdigest()
    tmp_file = os.path.join(tmp_dir, h)
    with open(tmp_file, "w") as f:
        f.write(queue)
    return h


def get_queue(queue_hash: str) -> str:
    """Load the id of a position in a queue

    Args:
        queue_hash (str): Hash of the queue for access

    Returns:
        str: Queue list
    """
    tmp_file = os.path.join(tmp_dir, queue_hash)
    with open(tmp_file, "r") as f:
        queue = json.load(f)
    if queue["highlight"] != None:
        session["highlight"] = queue["highlight"]
    return queue["queue"]


def manage_label_in_session(label: str, session, mode: str = "add"):
    """Hide a label in a session

    Args:
        label (str): Label to hide
        session (flask.session): Flask session
    """
    labels_list = []
    if "hidden_labels" in session:
        for l in session["hidden_labels"]:
            labels_list.append(l)

    if mode == "add":
        labels_list.append(label)
    elif mode == "remove":
        try:
            labels_list.remove(label)
        except ValueError:
            pass

    session["hidden_labels"] = labels_list


class ESManager:
    def __init__(self, serverfile="", **params) -> None:
        if len(params) == 0:
            with open(serverfile, "r") as f:
                params = json.load(f)

        self.es = Elasticsearch(**params)

    def create_index(self, index, mapping):
        return self.es.indices.create(index=index, mappings=mapping)

    def delete_index(self, index):
        return self.es.indices.delete(index=index)

    def list_indices(self):
        return self.es.indices.get_alias(index="*")

    def get_mapping(self, index):
        return self.es.indices.get_mapping(index=index)

    def add_document(self, document, index):
        return self.es.index(index=index, document=document)

    def get_all_documents(self, index, size=10000):
        return self.es.search(index=index, query={"match_all": {}}, size=size)

    def get_head_documents(self, index, n=10):
        return self.es.search(
            index=index, query={"query": {"match_all": {}}, "from": 0, "size": n}
        )

    def search(self, **kwargs):
        return self.es.search(**kwargs)


def es_bulk_upload(
    csv_file,
    id_column,
    text_column,
    index,
    mapping,
    doc_generator,
    entry_type,
    additional_indexes=[],
):
    client = ESManager(
        hosts=ES_SERVER,
        request_timeout=1000,
        read_timeout=1000,
        timeout=1000,
        max_retries=20,
    )

    print(f"Trying to create {index} index...")
    try:
        client.create_index(index, mapping)
    except:
        print("Index creation failed, index already exists?")

    for ind, mp in additional_indexes:
        print(f"Trying to create {ind} additional index...")
        try:
            client.create_index(ind, mp)
        except:
            print("Index creation failed, index already exists?")

    print(f"Loading data from {csv_file}...")
    df = pd.read_csv(csv_file)
    df = df.drop_duplicates()

    print("Uploading texts to ElasticSearch...")
    helpers.bulk(client.es, doc_generator(df, index, id_column, text_column))

    print("Registring entries on OLIM database...")
    register_entries(df[id_column].unique(), entry_type)

    print()
    print("Data uploaded!")
