import pandas as pd

from ...utils.es import es_search
from .constants import ES_INDEX


def extract_texts(entry_id, only_ids=False, only_values=False) -> pd.DataFrame:
    query = {"bool": {"must": [{"terms": {"_id": [entry_id]}}]}}
    res = es_search(query=query, index=ES_INDEX)["hits"]["hits"][0]

    # Load texts
    df = pd.DataFrame(res["_source"]["texts"])
    df["entry_id"] = entry_id

    return df
