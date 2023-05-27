## Auxiliary functions
# All functions here must have type hints and docstrings
from .settings import ES_INDEX, ES_LABEL_INDEX, ES_TO_HIDE_INDEX, ES_SERVER
from . import tmp_dir
from elasticsearch import Elasticsearch
from elasticsearch.helpers import scan
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
        n (int): Minimum number of characters to preserve

    Returns:
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


def update_hidden(txt_id, patient_id, hide):
    body = {
        "script": {
            "source": "def targets = ctx._source.texts.findAll(texts -> texts.text_id == params.text_id); for(text in targets) { text.is_hidden = params.is_hidden }",
            "params": {"text_id": txt_id, "is_hidden": hide},
        }
    }

    return es_update(id=patient_id, body=body, refresh=True)


def add_patient_label(label, patient_id, value, date_created=None):
    date_created = date_created or now_ISO()
    body = {
        "script": {
            "source": "def targets = ctx._source.labels.add(params.label)",
            "params": {"label": {"label": label, "date": date_created, "value": value}},
        }
    }

    return es_update(id=patient_id, body=body, refresh=True)


def create_new_label(label):
    label_doc = {"label": label, "created": now_ISO()}

    client = get_es_conn()
    return client.index(index=ES_LABEL_INDEX, document=label_doc)


def get_labels():
    client = get_es_conn()
    return client.search(index=ES_LABEL_INDEX, query={"match_all": {}}, size=10000)


def add_text_to_hide(text, text_id, patient_id):
    label_doc = {
        "text": text,
        "text_id": text_id,
        "patient_id": patient_id,
        "date": now_ISO(),
    }

    client = get_es_conn()
    return client.index(index=ES_TO_HIDE_INDEX, document=label_doc)


def get_all_hidden():
    client = get_es_conn()
    return client.search(
        index=ES_TO_HIDE_INDEX,
        query={"match_all": {}},
        size=10000,
    )[
        "hits"
    ]["hits"]


def remove_from_hidden(text_id):
    client = get_es_conn()
    query = {"query": {"bool": {"must": [{"match": {"text_id": text_id}}]}}}
    return client.delete_by_query(index=ES_TO_HIDE_INDEX, body=query, refresh=True)


def remove_from_labels(label_id):
    client = get_es_conn()
    query = {"query": {"bool": {"must": [{"match": {"_id": label_id}}]}}}
    return client.delete_by_query(index=ES_LABEL_INDEX, body=query, refresh=True)


def extract_label(label, only_ids=False):
    # Query to get all patients with the label
    # Getting only the more recent label
    # If the label value is empty, the patient doesn't have that label
    query = {
        "query": {
            "nested": {
                "path": "labels",
                "query": {"bool": {"filter": [{"term": {"labels.label": label}}]}},
                "inner_hits": {"size": 1, "sort": [{"labels.date": {"order": "desc"}}]},
            }
        },
    }

    # Query the search using scroll to get all the results
    es = get_es_conn()
    scroll = scan(
        es, query=query, index=ES_INDEX, scroll="10m", size=10000, request_timeout=30
    )

    results = []

    if only_ids:
        return [res["_id"] for res in scroll]

    for res in scroll:
        hits = res["inner_hits"]["labels"]["hits"]["hits"]
        res["_source"]["patient_id"] = res["_id"]
        for hit in hits:
            results.append((res["_source"], hit["_source"]))

    # Create a dataframe with the results
    # Initialize the dataframe with text, text_id, date, patient_id, visitation_id, label, label_value, label_created
    data = []
    for patient, label in results:
        if label["value"] == "":
            continue
        for texts in patient["texts"]:
            data.append(
                {
                    "text": texts["text"],
                    "text_id": texts["text_id"],
                    "date": texts["date"],
                    "patient_id": patient["patient_id"],
                    "visitation_id": texts["visitation_id"],
                    "label": label["label"],
                    "label_value": label["value"],
                    "label_created": label["date"],
                }
            )

    # Df to csv
    df = pd.DataFrame(data)
    return df.to_csv(index=False)


def parse_queue(text: str) -> List[str]:
    """Parse a queue input in to a queue list.

    Args:
        text (str): Queue input

    Returns:
        List[str]: Queue list
    """
    return text.replace(';', ' ').replace(',', ' ').replace('\n', ' ').replace('\r\n', ' ').split()


def store_queue(queue: List[str]) -> str:
    """Stores a queue in a temporay file.

    Args:
        queue (List[str]): Queue list

    Returns:
        str: Hash of the queue for access
    """
    queue = json.dumps(queue)
    h = hashlib.md5(queue.encode('utf-8')).hexdigest()
    tmp_file = os.path.join(tmp_dir, h)
    print(tmp_file)
    print(queue)
    with open(tmp_file, 'w') as f:
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
    with open(tmp_file, 'r') as f:
        queue = json.load(f)
    return queue

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

