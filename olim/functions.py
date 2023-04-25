## Auxiliary functions
# All functions here must have type hints and docstrings
from .settings import ES_INDEX, ES_LABEL_INDEX, ES_TO_HIDE_INDEX, ES_SERVER
from elasticsearch import Elasticsearch
from datetime import datetime
import json


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


def add_patient_label(label, patient_id, value):
    body = {
        "script": {
            "source": "def targets = ctx._source.labels.add(params.label)",
            "params": {"label": {"label": label, "date": now_ISO(), "value": value}},
        }
    }

    return es_update(id=patient_id, body=body, refresh=True)


def create_new_label(label):
    label_doc = {"label": label, "created": now_ISO()}

    client = get_es_conn()
    return client.index(index=ES_LABEL_INDEX, document=label_doc)


def get_labels():
    client = get_es_conn()
    print(client)
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
    return client.search(index=ES_TO_HIDE_INDEX, query={"match_all": {}}, size=10000,)[
        "hits"
    ]["hits"]

def remove_from_hidden(text_id):
    client = get_es_conn()
    query = {
        "query": {
            "match": {
                "text_id": text_id
            }
        }
    }
    return client.delete_by_query(index=ES_TO_HIDE_INDEX, body=query, refresh=True)