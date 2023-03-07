from . import app
from flask import url_for, request, render_template
from pprint import pprint, pformat
import sqlite3
import pandas as pd

# 1256519
# id_paciente,data,texto,tipo_texto,id_atendimento,id_texto
# 1256519,2019-08-12,cd4<50,solicitacao_agendamento.obs_urgente,,6d1e965f72763bd521ada5f14aa5a7b28a2c10e575a07f3033afad956a237d29


@app.route("/pacient",methods = ['GET'])
def pacient():
    pid = request.args['id']
    con = sqlite3.connect("textos_limpos.sqlite")
    df = pd.read_sql_query(f"SELECT * from textos_limpos WHERE id_paciente == {pid};", con)
    data = {
        "pacient_id": pid,
        "data": [],
    }
    for _, row in df.iterrows():
        data['data'].append(dict(row))
    return render_template('pacient.html', **data)