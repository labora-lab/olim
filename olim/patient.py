from . import app
from .functions import (
    shorten,
    es_search,
    get_labels,
    get_all_hidden,
    get_queue,
    manage_label_in_session,
)
from flask import request, render_template, redirect, session
import json
import pandas as pd
from datetime import datetime, timedelta


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

    # Load labels
    labels = {}
    raw_labels = res["_source"]["labels"]
    raw_labels.sort(key=lambda x: x["date"], reverse=True)
    for label in raw_labels:
        if label["label"] not in labels:
            labels[label["label"]] = label["value"]
    data["patient_labels"] = labels

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


def index(msg=""):
    pid = request.args.get("id", "")
    start_date = request.args.get("start-date", "")
    end_date = request.args.get("end-date", "")
    show_hidden = request.args.get("show-hidden", False) == "True"
    return render_template(
        "index.html",
        labels=get_labels(),
        msg=msg,
        start_date=start_date,
        end_date=end_date,
        patient_id=pid,
        show_hidden=show_hidden,
        valid_patient=False,
    )


@app.route("/patient", methods=["GET"])
def patient():
    hidden_labels = request.args.get("hidden_labels", [])
    if len(hidden_labels) > 0:
        try:
            for label in json.loads(hidden_labels):
                manage_label_in_session(label, session, "add")
        except ValueError:
            pass
    hidden_labels = session.get("hidden_labels", [])
    pid = request.args.get("id", "")
    queue_id = request.args.get("queue", "")
    if pid == "" and queue_id == "":
        return index()
    start_date = request.args.get("start-date", "")
    end_date = request.args.get("end-date", "")
    show_hidden = request.args.get("show-hidden", False) == "True"
    highlight = request.args.get("highlight", [])

    # Load queue
    queue_pos = request.args.get("queue-pos", "")
    if queue_id != "":
        if queue_pos == "":
            queue_pos = 0
        try:
            queue = get_queue(queue_id)
            queue_pos = int(queue_pos)
            pid = queue[queue_pos]
        except:
            return index(msg=f"Fila {queue_id} não encontrada")

    try:
        data = load_patient(
            pid=pid,
            start_date=start_date,
            end_date=end_date,
            ascending=False,
        )
    except IndexError:
        return index(msg=f"Paciente {pid} não encontrado!")

    data.update(
        {
            "start_date": start_date,
            "end_date": end_date,
            "patient_id": pid,
            "show_hidden": show_hidden,
            "labels": get_labels(),
            "highlight": highlight,
            "valid_patient": True,
            "queue_id": queue_id,
            "hidden_labels": hidden_labels,
        }
    )
    if queue_id != "":
        data.update(
            {
                "queue_len": len(queue),
                "queue_pos": queue_pos,
            }
        )

    return render_template("patient.html", **data)
