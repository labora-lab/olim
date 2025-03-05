from datetime import datetime, timedelta

import pandas as pd
from flask import flash, render_template, request, session
from flask_babel import _

from ...functions import es_search, get_all_hidden, shorten
from .constants import ES_INDEX


def load_patient(
    pid: int,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
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
        start_date (datetime, optional): Date to filter entrys. Defaults to None.
        end_date (datetime, optional): Date to filter entrys. Defaults to None.
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
    if start_date is not None:
        df = df[df["datetime"] >= start_date]
    if end_date is not None:
        df = df[df["datetime"] < end_date + timedelta(days=1)]
    df = df.sort_values(by="datetime", ascending=ascending)
    df = df.drop(columns=["datetime"])

    # Reverse data if ascending
    if ascending:
        df = df.iloc[::-1]

    # Iterate on returned DataFrame
    for _, row in df.iterrows():  # noqa: F402 [_ will not be shadowed]
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


def get_date(name: str) -> tuple[str, datetime | None]:
    """Gets a date from the GET request or the session info.

    Args:
        name (str): Name of the parameter containing the date

    Returns:
        Tuple[str, datetime | None]: Date string and object.
    """
    date = request.args.get(name, "")
    date = date.strip()
    if date == "":
        if ("patient_" + name in session) and (name not in request.args):
            date = session["patient_" + name]
    if name in request.args:
        session["patient_" + name] = date
    date_obj = None
    if date != "":
        try:
            date_obj = datetime.strptime(date, "%d/%m/%Y")
        except ValueError:
            flash(_('Invalid date "{date}".').format(date=date), category="error")
        except TypeError:
            pass
    return date, date_obj


def render(entry_id: int, **pars) -> str:
    """Renders a patient view.

    Args:
        entry_id (int): Patient entry id.

    Returns:
        str: Rendered HTML.
    """
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
