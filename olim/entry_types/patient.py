from ..functions import (
    shorten,
    es_search,
    get_all_hidden,
    manage_label_in_session,
    es_bulk_upload,
    es_update,
    get_es_conn,
    now_ISO,
    scan,
)
from flask import request, render_template, session, flash
import json
import pandas as pd
from datetime import datetime, timedelta
from ..cli import upload
from tqdm import tqdm
import click

ES_INDEX = "patients_index"
ES_TO_HIDE_INDEX = "patients_hidden_texts"

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
                "extra_fields": extra_fields_mapping,
            },
        },
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


def update_hidden(txt_id, entry_id, hide):
    body = {
        "script": {
            "source": "def targets = ctx._source.texts.findAll(texts -> texts.text_id == params.text_id); for(text in targets) { text.is_hidden = params.is_hidden }",
            "params": {"text_id": txt_id, "is_hidden": hide},
        }
    }

    return es_update(id=entry_id, body=body, refresh=True, index=ES_INDEX)


def remove_from_hidden(text_id):
    client = get_es_conn()
    query = {"query": {"bool": {"must": [{"match": {"text_id": text_id}}]}}}
    return client.delete_by_query(index=ES_TO_HIDE_INDEX, body=query, refresh=True)


def add_text_to_hide(text, text_id, entry_id):
    label_doc = {
        "text": text,
        "text_id": text_id,
        "entry_id": entry_id,
        "date": now_ISO(),
    }

    client = get_es_conn()
    return client.index(index=ES_TO_HIDE_INDEX, document=label_doc)


def hide_one(**args):
    txt_id = args.get("txt_id", None)
    entry_id = int(args.get("entry_id", None))

    try:
        update_hidden(txt_id, entry_id, True)
    except:
        return {
            "type": "error",
            "text": "Failed writing to database",
        }

    if txt_id == None:
        return {
            "type": "error",
            "text": "No ID passed",
        }
    else:
        return {
            "type": "OK",
            "text": f"Ocultado texto {txt_id}",
        }


def show(**args):
    txt_id = args.get("txt_id", None)
    entry_id = int(args.get("entry_id", None))

    try:
        update_hidden(txt_id, entry_id, False)
    except:
        return {
            "type": "error",
            "text": "Failed writing to database",
        }

    if txt_id == None:
        return {
            "type": "error",
            "text": "No ID passed",
        }
    else:
        return {
            "type": "OK",
            "text": f"Desocultado texto {txt_id}",
        }


def hide_all(**args):
    entry_id = args.get("entry_id", None)
    text = args.get("text", None)
    text_id = args.get("text_id", None)

    try:
        add_text_to_hide(text, text_id, entry_id)
    except:
        return {
            "type": "error",
            "text": "Failed writing to database",
        }

    if entry_id == None or text == None or text_id == None:
        return {
            "type": "error",
            "text": f"Missing data: {entry_id}, {text_id}, {text}",
        }
    else:
        return {
            "type": "OK",
            "text": f"Sempre esconderá texto {text}",
        }


def remove_hidden(**args):
    text_id = args.get("text_id", None)

    try:
        remove_from_hidden(text_id)
    except:
        return {
            "type": "error",
            "text": "Failed writing to database",
        }

    if text_id == None:
        return {
            "type": "error",
            "text": "Missing data: text_id",
        }
    else:
        return {
            "type": "OK",
            "text": f"Texto {text_id} removido da lista de escondidos",
        }


COMMANDS = {
    "hide-one": hide_one,
    "hide-all": hide_all,
    "show": show,
    "remove-hidden": remove_hidden,
}


def load_patient(
    pid: int,
    start_date: str = None,
    end_date: str = None,
    ascending: bool = False,
) -> dict:
    """Loads all texts for a given pacient, data will be  stored in the format:

    data = {
        'patient_id': pid,
        'dates': {
            'DD/MM/YYYY': {
                'texts': {
                        "text_id": XXXXXX,
                        "text": "Text",
                        "short_text": "Shorted text.",
                        "text_type: "Text type",
                        "visitation_id": XXXXX,
                    },
                    (.....)
                'hidden_count': XX,
                'count': XX,
            },
            'DD/MM/YYYY': (......)
        },
        'patient_labels': {
            "Label 1": 'value',
            (....)
            "Label n": 'value',
        }
    }

    Args:
        pid (int): Id of the patient.
        start_date (str, optional): Date to filter entrys. Defaults to None.
        end_date (str, optional): Date to filter entrys. Defaults to None.
        ascending (bool, optional): Sort dates in acending order. Defaults to False.

    Returns:
        dict, list: Data dictionary, List of labels.
    """
    data = {
        "patient_id": pid,
        "dates": {},
    }

    # Loads data from elastic search
    query = {"bool": {"must": [{"terms": {"_id": [pid]}}]}}
    res = es_search(query=query, index=ES_INDEX)["hits"]["hits"][0]

    # Load texts
    df = pd.DataFrame(res["_source"]["texts"])

    # Filter hidden everywhere texts
    hidden_everyhere = [res["_source"]["text"] for res in get_all_hidden()]
    df["hidden_everywhere"] = df["text"].isin(hidden_everyhere)

    # Generates shortned texts
    df["short_text"] = df["text"].apply(shorten)

    # Filter and format dates
    df["datetime"] = pd.to_datetime(df["date"])
    df["date"] = df["datetime"].dt.strftime("%d/%m/%Y")
    if start_date != "":
        df = df[df["datetime"] >= start_date]
    if end_date != "":
        df = df[df["datetime"] < end_date + timedelta(days=1)]
    df = df.sort_values(by="datetime", ascending=ascending)
    df = df.drop(columns=["datetime"])

    # Reverse data if ascending
    if ascending:
        df = df.iloc[::-1]

    # Iterate on returned DataFrame
    for _, row in df.iterrows():
        date = row["date"]
        if date not in data["dates"].keys():
            data["dates"][date] = {
                "texts": [],
                "count": 0,
                "hidden_count": 0,
            }
        data["dates"][date]["texts"].append(dict(row))
        data["dates"][date]["count"] += 1
    return data


def get_date(name):
    date = request.args.get(name, "")
    date = date.strip()
    if date == "":
        if ("patient_" + name in session) and (name not in request.args):
            date = session["patient_" + name]
    if name in request.args:
        session["patient_" + name] = date
    date_obj = ""
    if date != "":
        try:
            date_obj = datetime.strptime(date, "%d/%m/%Y")
        except ValueError:
            flash('Data inválida "{}".'.format(date), category="error")
        except TypeError:
            pass
    return date, date_obj


def render(entry_id, **pars):
    hidden_labels = request.args.get("hidden_labels", [])
    if len(hidden_labels) > 0:
        try:
            for label in json.loads(hidden_labels):
                manage_label_in_session(label, session, "add")
        except ValueError:
            pass
    pid = entry_id

    # Checks integrity of dates
    start_date_str, start_date = get_date("start-date")
    end_date_str, end_date = get_date("end-date")

    data = load_patient(
        pid=pid,
        start_date=start_date,
        end_date=end_date,
        ascending=False,
    )

    data.update(
        {
            "start_date": start_date_str,
            "end_date": end_date_str,
            "patient_id": pid,
        }
    )

    return render_template("entry_types/patient.html", **data)


@click.command(
    "patient",
    help="Upload data of the patient type."
    "\n\n\tCSV_FILE\tPath to the CSV file to load data.",
)
@click.argument("csv_file", type=click.Path(exists=True))
def up_patients(csv_file):
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

    def doc_generator(df, *_):
        for pid in tqdm(df["patient_id"].unique()):
            yield {
                "_index": ES_INDEX,
                "_id": f"{pid}",
                "_source": {
                    "texts": get_texts(pid, df),
                    "labels": [],
                },
            }

    es_bulk_upload(
        csv_file,
        "patient_id",
        None,
        ES_INDEX,
        patients_mapping,
        doc_generator,
        "patient",
        additional_indexes=[(ES_TO_HIDE_INDEX, to_hide_mapping)],
    )


upload.add_command(up_patients)


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
