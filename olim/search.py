from . import app, entry_types
from .functions import store_queue, get_def_nentries
from .database import get_entries
from flask import request, render_template, session
import pandas as pd
import json


def get_terms(field):
    value = request.args.get(field, "")
    if len(value) == 0:
        return "[]", [], []
    data = json.loads(value)
    terms = [term.strip() for term in data if len(term.split()) == 1]
    phrases = [term.strip() for term in data if len(term.split()) > 1]
    value = json.dumps([{"tag": term} for term in data])
    return value, terms, phrases


@app.route("/search", methods=["GET"])
def search():
    include, must_terms, must_phrases = get_terms("include")
    exclude, not_must_terms, not_must_phrases = get_terms("exclude")
    number = int(request.args.get("number", get_def_nentries()))
    session["number_of_entries"] = number

    only_queue = request.args.get("only-queue", "off")
    only_queue = True if only_queue == "on" else False

    # No search return empty page
    if (
        len(must_terms) == 0
        and len(must_phrases) == 0
        and len(not_must_terms) == 0
        and len(not_must_phrases) == 0
    ):
        return render_template(
            "search.html",
            number=number,
            include="[]",
            exclude="[]",
            highlight="[]",
        )

    session["highlight"] = must_terms + must_phrases

    data = []
    for mod in dir(entry_types):
        if get_entries(type=mod).all():
            module = getattr(entry_types, mod)
            if hasattr(module, "search"):
                data += module.search(
                    must_terms=must_terms,
                    must_phrases=must_terms,
                    not_must_terms=not_must_terms,
                    not_must_phrases=not_must_phrases,
                    number=number,
                )

    highlight = must_terms + must_phrases
    if len(data) > 0:
        df_results = pd.DataFrame(data)
        df_results = df_results.sort_values(
            by="score", ascending=False, ignore_index=True
        ).iloc[:number]
        data = df_results.to_dict("records")
        extra_data = {
            "Include": must_terms + must_phrases,
            "Exclude": not_must_terms + not_must_phrases,
        }
        queue_id = store_queue(df_results["entry_id"], highlight, **extra_data)
    else:
        queue_id = None

    return render_template(
        "search.html",
        results=data,
        include=include,
        exclude=exclude,
        number=number,
        highlight=highlight,
        only_queue=only_queue,
        queue_id=queue_id,
    )
