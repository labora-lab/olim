from . import app
from .functions import get_labels
from flask import render_template


@app.route("/labels", methods=["GET"])
def labels():
    result = get_labels()["hits"]["hits"]
    res = []
    for r in result:
        res.append(dict(r["_source"], _id=r["_id"]))
    return render_template("labels.html", res=res)
