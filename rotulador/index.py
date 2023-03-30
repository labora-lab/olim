from . import app
from flask import render_template
from .functions import get_labels


@app.route("/")
def index():
    return render_template(
        "index.html",
        labels=get_labels(),
    )
