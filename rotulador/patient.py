from . import app
from flask import request, render_template
import pandas as pd
from datetime import datetime
from .functions import shorten
import numpy as np
from elasticsearch import Elasticsearch
import json

def get_data_elastic(
        pid: int,
        start_date: datetime,
        end_date: datetime,
        show_hidden: bool) -> pd.DataFrame:
    """Loads data from elastic search.

    Args:
        pid (int): Id of the patient.
        start_date (str): Date to filter entrys.
        end_date (str): Date to filter entrys.
        show_hidden (bool): Get hidden entrys if True.

    Returns:
        pd.DataFrame: Dataframe with the data.
    """
    # Connect to elastic search
    server_file = "server_credentials.json"
    with open(server_file, 'r') as f:
        pars = json.load(f)
    ES = Elasticsearch(**pars)

    # Load data from query
    query = {'query' : {
        "bool": {"must": [
                {"match": {"id_paciente": pid}},

                {"range": #filters by date
                    {"data": {
                        "gte": start_date,
                        "lte": end_date
                    }}
                },

                {"bool": {"should": [ #gets hidden if show_hidden == True
                    {"match": {"hidden": False}},
                    {"match": {"hidden": show_hidden}}
                ]}}
            ]}
    }}

    res = ES.search(index = "prontuarios_texto", body = query)
    if res['hits']['hits'] == []:
        return pd.DataFrame()
    df = pd.DataFrame([x['_source'] for x in res['hits']['hits']])

    df = df.drop_duplicates(ignore_index=True)

    # Parse dates to sort
    df["datetime"] = pd.to_datetime(df["data"])
    df = df.sort_values(by="datetime", ascending=False, ignore_index=True)

    # Convert and collet the relevant data
    new_df = pd.DataFrame()
    new_df["text_id"] = df["id_texto"]
    new_df["date"] = df["datetime"].dt.strftime("%d/%m/%Y")
    new_df["text"] = df["texto"]
    new_df["text_type"] = df["tipo_texto"]
    new_df["visitation_id"] = df["id_atendimento"].astype(int)
    new_df["hidden"] = df["hidden"]


    return new_df


    return new_df

def load_patient(
    pid: int,
    start_date: str = None,
    end_date: str = None,
    ascending: bool = False,
    show_hidden: bool = False
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
    }

    Args:
        pid (int): Id of the patient.
        start_date (str, optional): Date to filter entrys. Defaults to None.
        end_date (str, optional): Date to filter entrys. Defaults to None.
        ascending (bool, optional): Sort dates in acending order. Defaults to False.

    Returns:
        dict: Data dictionary.
    """
    data = {
        "patient_id": pid,
        "dates": {},
    }

    # Checks integrity of dates
    #remove space before and after from start_date and end_date (empty date data is coming as "  " string)
    start_date = start_date.strip()
    end_date = end_date.strip()
    if start_date == "":
        start_date = "01/01/1900"
    if end_date == "":
        end_date = "01/01/3000"
    try:
        start_date = datetime.strptime(start_date, "%d/%m/%Y")
    except ValueError:
        data["error"] = 'Data inválida "{}".'.format(start_date)
    except TypeError:
        pass
    try:
        end_date = datetime.strptime(end_date, "%d/%m/%Y")
    except ValueError:
        data["error"] = 'Data inválida "{}".'.format(end_date)
    except TypeError:
        pass


    # Loads data from elastic search
    df = get_data_elastic(
        pid=pid,
        start_date=start_date,
        end_date=end_date,
        show_hidden=show_hidden
    )

    # Generates shortned texts
    df["short_text"] = df["text"].apply(shorten)

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
        if row["hidden"]:
            data["dates"][date]["hidden_count"] += 1
    return data


@app.route("/patient", methods=["GET"])
def patient():
    pid = request.args.get("id", "")
    start_date = request.args.get("start-date", "")
    end_date = request.args.get("end-date", "")
    show_hidden = request.args.get("show-hidden", False) == "True"

    data = load_patient(
        pid=pid,
        start_date=start_date,
        end_date=end_date,
        ascending=False,
    )

    data.update(
        {
            "start_date": start_date,
            "end_date": end_date,
            "show_hidden": show_hidden,
        }
    )

    return render_template("patient.html", **data)
