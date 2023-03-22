## Auxiliary functions
# All functions here must have type hints and docstrings
from .settings import ES_SERVER_FILE, ES_INDEX
from elasticsearch import Elasticsearch
import json

def shorten(string:str, n:int=80, add:str=" (...)") -> str:
    """Finds the first space after n characters and truncate the
        string there.

    Args:
        string (str): Original string.
        n (int): Minimum number of characters to preserve

    Returns:
        str: Shortened string.
    """
    pos = string.find(' ', n)
    if pos != -1:
        return string[:pos] + add
    else:
        return string

def get_es_conn(**kwargs):
    with open(ES_SERVER_FILE, 'r') as f:
        pars = dict(json.load(f))
    pars.update(kwargs)
    return Elasticsearch(**pars)

def get_index(kwargs):
    if 'index' in kwargs:
        index = kwargs['index']
    else:
        kwargs['index'] = ES_INDEX
        index = ES_INDEX
    return index, kwargs

def es_list_fields(**kwargs):
    index, kwargs = get_index(kwargs)
    client = get_es_conn()
    return list(client.indices.get_mapping(**kwargs)[index]["mappings"]["properties"].keys())

def es_search(**kwargs):
    _, kwargs = get_index(kwargs)
    client = get_es_conn()
    return client.search(**kwargs)
