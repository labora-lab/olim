from . import app
from flask import request, render_template
import sqlite3
import pandas as pd
from datetime import datetime
from .functions import shorten
import numpy as np

# 1256519
# id_paciente,data,texto,tipo_texto,id_atendimento,id_texto


def get_data_sqlite(pid: int) -> pd.DataFrame:
    # Load data from the sqlite database
    con = sqlite3.connect("textos_limpos.sqlite")
    df = pd.read_sql_query(
        f"SELECT * from textos_limpos WHERE id_paciente = {pid};", con
    )
    df = df.drop_duplicates(ignore_index=True)

    # Parse dates to sort
    df["datetime"] = pd.to_datetime(df["data"])
    df = df.sort_values(by="datetime", ascending=False, ignore_index=True)

    # Convert and collet the relevant data
    new_df = pd.DataFrame()
    new_df["text_id"] = df["id_texto"].astype(int)
    new_df["date"] = df["datetime"].dt.strftime("%d/%m/%Y")
    new_df["text"] = df["texto"]
    new_df["text_type"] = df["tipo_texto"]
    new_df["visitation_id"] = df["id_atendimento"].astype(int)
    new_df["datetime"] = df["datetime"]
    new_df["hidden"] = np.random.uniform(size=len(df)) >= 0.5

    return new_df


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
    df = get_data_sqlite(pid)

    # Filters by date
    try:
        start_date = datetime.strptime(start_date, "%d/%m/%Y")
        df = df[df["datetime"].dt >= start_date]
    except ValueError:
        data["error"] = 'Data inválida "{}".'.format(start_date)
    except TypeError:
        pass
    try:
        end_date = datetime.strptime(end_date, "%d/%m/%Y")
        df = df[df["datetime"].dt <= end_date]
    except ValueError:
        data["error"] = 'Data inválida "{}".'.format(end_date)
    except TypeError:
        pass
    df = df.drop(columns=["datetime"])

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
    show_hidden = bool(request.args.get("show-hidden", False))

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
