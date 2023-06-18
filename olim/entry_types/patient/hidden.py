from . import ENTRY_TYPE, ES_TO_HIDE_INDEX
from ...database import get_entries
from ...functions import get_es_conn


def have_hidden():
    for _ in get_entries(ENTRY_TYPE):
        return True
    return False

def get_all_hidden():
    client = get_es_conn()
    return client.search(
        index=ES_TO_HIDE_INDEX,
        query={"match_all": {}},
        size=10000,
    )[
        "hits"
    ]["hits"]
