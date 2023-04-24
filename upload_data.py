from olim.settings import ES_SERVER, ES_INDEX, ES_LABEL_INDEX, ES_TO_HIDE_INDEX
from elasticsearch import Elasticsearch
from elasticsearch import helpers
import json
from datetime import datetime
import pandas as pd
from tqdm import tqdm
from pprint import pprint
import sys


def now():
    return datetime.now().isoformat()


labels_mapping = {
    "properties": {
        "label": {"type": "text"},
        "description": {"type": "text"},
        "created": {"type": "date"},
    }
}

label_mapping = {
    "type": "nested",
    "properties": {
        "label": {"type": "text"},
        "value": {"type": "text"},
        "date": {"type": "date"},
    },
}

extra_fields_mapping = {
    "type": "nested",
    "properties": {
        "name": {"type": "text"},
        "value": {"type": "text"},
        "type": {"type": "text"},
        "date": {"type": "date"},
    },
}


patients_mapping = {
    "properties": {
        "texts": {
            "type": "nested",
            "properties": {
                "date": {"type": "date"},
                "text": {"type": "text"},
                "text_id": {"type": "text"},
                "text_type": {"type": "text"},
                "visitation_id": {"type": "text"},
                "is_hidden": {"type": "boolean"},
                "labels": label_mapping,
                "extra_fields": extra_fields_mapping,
            },
        },
        "labels": label_mapping,
        "extra_fields": extra_fields_mapping,
    }
}

to_hide_mapping = {
    "properties": {
        "date": {"type": "date"},
        "text": {"type": "text"},
        "text_id": {"type": "text"},
        "patient_id": {"type": "text"},
    }
}


class ESManager:
    def __init__(self, serverfile="", **params) -> None:
        if len(params) == 0:
            with open(serverfile, "r") as f:
                params = json.load(f)

        self.es = Elasticsearch(**params)

    def create_index(self, index, mapping):
        return self.es.indices.create(index=index, mappings=mapping)

    def delete_index(self, index):
        return self.es.indices.delete(index=index)

    def list_indices(self):
        return self.es.indices.get_alias(index="*")

    def get_mapping(self, index):
        return self.es.indices.get_mapping(index=index)

    def add_document(self, document, index):
        return self.es.index(index=index, document=document)

    def get_all_documents(self, index, size=10000):
        return self.es.search(index=index, query={"match_all": {}}, size=size)

    def get_head_documents(self, index, n=10):
        return self.es.search(
            index=index, query={"query": {"match_all": {}}, "from": 0, "size": n}
        )

    def search(self, **kwargs):
        return self.es.search(**kwargs)


client = ESManager(
    hosts=ES_SERVER,
    request_timeout=1000,
    read_timeout=1000,
    timeout=1000,
    max_retries=20,
)

client.create_index(ES_LABEL_INDEX, labels_mapping)
pprint(client.get_mapping(index=ES_LABEL_INDEX))

client.create_index(index=ES_TO_HIDE_INDEX, mapping=to_hide_mapping)
pprint(client.get_mapping(index=ES_TO_HIDE_INDEX))

client.create_index(ES_INDEX, patients_mapping)
pprint(client.get_mapping(ES_INDEX))

df = pd.read_csv(sys.argv[1])
df = df.drop_duplicates()
df = df[~df["text"].isna()]


def get_texts(pid, df):
    def parse_row(row):
        if "visitation_id" in row:
            if row["visitation_id"] == "nan":
                del row["visitation_id"]
            else:
                row["visitation_id"] = str(int(row["visitation_id"]))
        row["is_hidden"] = False
        row["date"] = row["date"].isoformat()
        row["labels"] = []
        return row

    df_a = df[df["patient_id"] == pid]
    df_a = df_a.drop(columns="patient_id")
    df_a["date"] = pd.to_datetime(df_a["date"])
    return [parse_row(row.dropna().to_dict()) for _, row in df_a.iterrows()]


def doc_generator(df):
    for pid in tqdm(df["patient_id"].unique()):
        yield {
            "_index": ES_INDEX,
            "_id": f"{pid}",
            "_source": {
                "texts": get_texts(pid, df),
                "labels": [],
            },
        }


helpers.bulk(client.es, doc_generator(df))

print()
print("Data uploaded!")
