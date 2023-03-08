from . import app
from flask import url_for, request, render_template
from pprint import pprint, pformat
import sqlite3
import pandas as pd

# 1256519
# id_patiente,data,texto,tipo_texto,id_atendimento,id_texto


@app.route("/patient", methods=["GET"])
def patient():
    pid = request.args["id"]
    con = sqlite3.connect("textos_limpos.sqlite")
    df = pd.read_sql_query(
        f"SELECT * from textos_limpos WHERE id_paciente == {pid};", con
    )
    df["datetime"] = pd.to_datetime(df["data"])
    df["data"] = df["datetime"].dt.strftime("%d/%m/%Y")
    df = df.drop_duplicates(ignore_index=True)
    df = df.sort_values(by="datetime", ascending=False, ignore_index=True)
    data = {
        "patient_id": pid,
        "data": {},
    }
    date = ""
    for _, row in df.iterrows():
        curr_date = row["data"]
        if date != curr_date:
            date = curr_date
            data["data"][curr_date] = []
        data["data"][curr_date].append(dict(row))
    return render_template("patient.html", **data)
