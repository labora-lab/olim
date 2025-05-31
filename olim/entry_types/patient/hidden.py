from ...database import get_entries
from ...utils.es import get_es_conn
from .constants import ENTRY_TYPE, ES_TO_HIDE_INDEX


def have_hidden() -> bool:
    for _ in get_entries(ENTRY_TYPE):
        return True
    return False


def get_all_hidden(*_, **__) -> list[dict]:
    client = get_es_conn()
    return client.search(
        index=ES_TO_HIDE_INDEX,
        query={"match_all": {}},
        size=10000,
    )["hits"]["hits"]
