from . import app
from .functions import shorten, es_search, get_labels
from .settings import CALENDAR_LANGUAGE, YEAR_RANGE
from flask import request, render_template
import pandas as pd
from datetime import datetime
import json
import numpy as np


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
    # remove space before and after from start_date and end_date (empty date data is coming as "  " string)
    start_date = start_date.strip()
    end_date = end_date.strip()
    try:
        start_date = datetime.strptime(start_date, "%d/%m/%Y")
    except ValueError:
        data["error"] = 'Data inválida "{}".'.format(start_date)
        start_date = ""
    except TypeError:
        pass
    try:
        end_date = datetime.strptime(end_date, "%d/%m/%Y")
    except ValueError:
        data["error"] = 'Data inválida "{}".'.format(end_date)
        end_date = ""
    except TypeError:
        pass

    # Loads data from elastic search
    query = {"bool": {"must": [{"terms": {"_id": [pid]}}]}}
    res = es_search(query=query)["hits"]["hits"][0]
    df = pd.DataFrame(res["_source"]["texts"])

    # Generates shortned texts
    df["short_text"] = df["text"].apply(shorten)

    # Filter and format dates
    df["datetime"] = pd.to_datetime(df["date"])
    df["date"] = df["datetime"].dt.strftime("%d/%m/%Y")
    if start_date != "":
        df = df[df["datetime"] >= start_date]
    if end_date != "":
        df = df[df["datetime"] <= end_date]
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


@app.route("/patient", methods=["GET"])
def patient():
    pid = request.args.get("id", "")
    start_date = request.args.get("start-date", "")
    end_date = request.args.get("end-date", "")
    show_hidden = request.args.get("show-hidden", False) == "True"
    highlight = request.args.get("highlight", [])

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
            "language": CALENDAR_LANGUAGE,
            "year_range": YEAR_RANGE,
            "labels": get_labels(),
            "highlight": highlight,
        }
    )

    return render_template("patient.html", **data)
