from datetime import datetime

from elasticsearch import Elasticsearch

from ..settings import ES_INDEX, ES_SERVER


def now_iso() -> str:
    return datetime.now().isoformat()


def get_es_conn(**kwargs) -> Elasticsearch:
    kwargs.update({"hosts": ES_SERVER})
    return Elasticsearch(**kwargs)


def get_index(kwargs) -> tuple[str, dict]:
    if "index" in kwargs:
        index = kwargs["index"]
    else:
        kwargs["index"] = ES_INDEX
        index = ES_INDEX
    return index, kwargs


def es_list_fields(**kwargs) -> list[str]:
    index, kwargs = get_index(kwargs)
    client = get_es_conn()
    return list(
        client.indices.get_mapping(**kwargs)[index]["mappings"]["properties"].keys()
    )


def es_search(**kwargs) -> dict:
    _, kwargs = get_index(kwargs)
    client = get_es_conn()
    return client.search(**kwargs)


def es_update(**kwargs) -> dict:
    _, kwargs = get_index(kwargs)
    client = get_es_conn()
    return client.update(**kwargs)
