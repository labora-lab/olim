from . import app
from .functions import get_all_hidden
from flask import request, render_template
import secrets
import json



@app.route("/hidden", methods=["GET"])
def hidden():
    result = get_all_hidden()
    res = []
    for r in result:
        res.append(dict(r["_source"]))
    return render_template("hidden.html", res=res)