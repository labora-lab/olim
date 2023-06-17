from . import ES_INDEX
from ...functions import get_es_conn, scan
import pandas as pd

def extract_label(label, only_ids=False, only_values=False):
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
        return [res["_id"] for res in scroll if res["_source"]["label"] != ""]

    if only_values:
        values = []
        for res in scroll:
            hits = res["inner_hits"]["labels"]["hits"]["hits"]
            for hit in hits:
                values.append(hit["_source"]["value"])
        return values

    for res in scroll:
        hits = res["inner_hits"]["labels"]["hits"]["hits"]
        res["_source"]["entry_id"] = res["_id"]
        for hit in hits:
            results.append((res["_source"], hit["_source"]))

    # Create a dataframe with the results
    # Initialize the dataframe with text, text_id, date, entry_id, visitation_id, label, label_value, label_created
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
                    "entry_id": patient["entry_id"],
                    "visitation_id": texts["visitation_id"],
                    "label": label["label"],
                    "label_value": label["value"],
                    "label_created": label["date"],
                }
            )

    # Df to csv
    df = pd.DataFrame(data)
    return df.to_csv(index=False)
