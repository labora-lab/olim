from flask import render_template

from . import app
from .utils.entry import get_all_hidden


@app.route("/hidden", methods=["GET"])
def hidden() -> ...:
    result = get_all_hidden()
    res = []
    for r in result:
        res.append(dict(r["_source"]))
    return render_template("hidden.html", res=res)
