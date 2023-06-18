from . import ES_INDEX
from ...functions import es_search
import pandas as pd


def extract_texts(entry_id, only_ids=False, only_values=False):
    query = {"bool": {"must": [{"terms": {"_id": [entry_id]}}]}}
    res = es_search(query=query, index=ES_INDEX)["hits"]["hits"][0]

    # Load texts
    df = pd.DataFrame(res["_source"]["texts"])
    df["entry_id"] = entry_id

    return df
