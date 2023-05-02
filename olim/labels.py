from . import app
from .functions import get_labels, extract_label
from flask import render_template, Response


@app.route("/labels", methods=["GET"])
def labels():
    result = get_labels()["hits"]["hits"]
    res = []
    for r in result:
        res.append(dict(r["_source"], _id=r["_id"]))
    return render_template("labels.html", res=res)


@app.route("/labels/", defaults={"path": ""})
@app.route("/labels/<path:path>")
def catch_all(path):
    if path.lower().endswith(".csv"):
        label = path[:-4].lower()
        return Response(extract_label(label), mimetype="text/csv")
