## Auxiliary functions
# All functions here must have type hints and docstrings
from .settings import ES_INDEX, ES_SERVER
from .database import register_entries
from . import queue_dir, entry_types
from elasticsearch import Elasticsearch, helpers
from flask import session, flash
from datetime import datetime
from typing import List, Dict
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
    hidden = []
    for mod in dir(entry_types):
        module = getattr(entry_types, mod)
        if hasattr(module, "get_all_hidden"):
            hidden += module.get_all_hidden()
    return hidden


def have_hidden():
    have_hidden = False
    for mod in dir(entry_types):
        module = getattr(entry_types, mod)
        if hasattr(module, "have_hidden"):
            have_hidden = have_hidden or module.have_hidden()
    return have_hidden


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


def store_queue(queue: List[str], highlight: List[str] = None, **extra_data) -> str:
    """Stores a queue in a temporay file.

    Args:
        queue (List[str]): Queue list

    Returns:
        str: Hash of the queue for access
    """
    queue = list(queue)
    queue_id = hashlib.md5(json.dumps(queue).encode("utf-8")).hexdigest()
    queue_data = {
        "id": queue_id,
        "queue": queue,
        "highlight": highlight,
        "exta_data": extra_data,
        "lenght": len(queue),
    }
    queue_file = os.path.join(queue_dir, "queue_" + queue_id + ".json")
    with open(queue_file, "w") as f:
        json.dump(queue_data, f)
    return queue_id


def get_queue(queue_id: str) -> str:
    """Load the id of a position in a queue

    Args:
        queue_hash (str): Hash of the queue for access

    Returns:
        str: Queue list
    """
    queue_file = os.path.join(queue_dir, "queue_" + queue_id + ".json")
    with open(queue_file, "r") as f:
        queue = json.load(f)
    if queue["highlight"] != None:
        session["highlight"] = queue["highlight"]
    return queue["queue"]


def get_all_queues() -> List[Dict]:
    queues = []
    for queue_file in os.listdir(queue_dir):
        if queue_file.startswith("queue_") and queue_file.endswith(".json"):
            try:
                with open(os.path.join(queue_dir, queue_file), "r") as f:
                    queue = json.load(f)
            except:
                flash(f"Failed to read queue file {queue_file}.", category="error")
                queue = None
            if queue != None:
                queues.append(queue)
    return queues


def get_def_nentries() -> int:
    """Gets the number os entries for the session.

    Returns:
        int: Number of entries.
    """
    if "number_of_entries" not in session:
        session["number_of_entries"] = 1000
    return session["number_of_entries"]


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
