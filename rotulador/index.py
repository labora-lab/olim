from . import app
from flask import render_template
from .settings import CALENDAR_LANGUAGE, YEAR_RANGE
from .functions import get_labels


@app.route("/")
def index():
    return render_template(
        "index.html",
        language=CALENDAR_LANGUAGE,
        year_range=YEAR_RANGE,
        labels=get_labels(),
    )
