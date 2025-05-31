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
    return list(client.indices.get_mapping(**kwargs)[index]["mappings"]["properties"].keys())


def es_search(**kwargs) -> dict:
    _, kwargs = get_index(kwargs)
    client = get_es_conn()
    return client.search(**kwargs)


def es_update(**kwargs) -> dict:
    _, kwargs = get_index(kwargs)
    client = get_es_conn()
    return client.update(**kwargs)


def create_index(index_name: str) -> None:
    """Creates an empty index with standard OLIM settings (n-gram tokenization).

    Does nothing if index already exists.

    Args:
        index_name (str): Index name to be created.
    """

    # Define n-gram analyzer settings
    settings = {
        "analysis": {
            "analyzer": {
                "ngram_analyzer": {"tokenizer": "ngram_tokenizer", "filter": ["lowercase"]}
            },
            "tokenizer": {
                "ngram_tokenizer": {
                    "type": "ngram",
                    "min_gram": 3,
                    "max_gram": 5,
                    "token_chars": ["letter", "digit"],
                }
            },
        }
    }

    # Define mapping with n-gram analyzer
    mapping = {
        "properties": {
            "text": {
                "type": "text",
                "analyzer": "ngram_analyzer",
                "search_analyzer": "standard",  # Use standard analyzer at search time
            }
        }
    }

    es = get_es_conn(
        hosts=ES_SERVER,
        request_timeout=1000,
        read_timeout=1000,
        timeout=1000,
        max_retries=20,
    )

    try:
        # Create index with custom settings and mapping
        es.indices.create(index=index_name, settings=settings, mappings=mapping)
    except Exception:
        pass  # Index already exists
