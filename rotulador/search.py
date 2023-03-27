from . import app
from .functions import es_list_fields, es_search
from flask import request, render_template
import secrets
import json
from .settings import ES_MAPPINGS

app.secret_key = secrets.token_hex(16)

def get_terms(field, sep = ","):
    try:
        return [x.strip() for x in request.args.get(field).split(sep) if x.strip()]
    except AttributeError:
        return []

@app.route("/search", methods=["GET"])
def search():
    must_terms = get_terms("must_terms")
    must_phrases = get_terms("must_phrases", ";")
    not_must_terms = get_terms("not_must_terms")
    not_must_phrases = get_terms("not_must_phrases", ";")

    # No search return empty page
    if len(must_terms) == 0 and len(must_terms) == 0 and len(must_terms) == 0 and len(must_terms) == 0:
        return render_template("search.html")

    all_must = must_terms + must_phrases
    col_search = ES_MAPPINGS['TEXT_CONTENT']
    es_query = {
        "bool": {
            "must": [],
            "must_not": [],
            "should": []
        }
    }

    es_query["bool"]["must"].extend([{"query_string": {"query": term, "fields": [col_search]}} for term in must_terms])
    es_query["bool"]["must"].extend([{"match_phrase": {col_search: {"query": phrase}}} for phrase in must_phrases])
    es_query["bool"]["must_not"].extend([{"query_string": {"query": term, "fields": [col_search]}} for term in not_must_terms])
    es_query["bool"]["must_not"].extend([{"match_phrase": {col_search: {"query": phrase}}} for phrase in not_must_phrases])

    # print(json.dumps(es_query, indent=2))

    # pacient_id = cd_usu_cadsus
    resp = es_search(
        query=es_query,
        size=10000
    )

    results = {}
    for result in resp["hits"]["hits"]:
        for term in all_must:
            result["_source"][col_search] = result["_source"][col_search].replace(term, f"<span class=\"highlight\">{term}</span>")
        value = results.get(result["_source"][ES_MAPPINGS['ID_PATIENT']], [])
        value.append(result)
        results[result["_source"][ES_MAPPINGS['ID_PATIENT']]] = value

    return render_template("search.html",
                           results=results,
                           must_terms=request.args.get("must_terms"),
                           must_phrases=request.args.get("must_phrases"),
                           not_must_phrases=request.args.get("not_must_phrases"),
                           not_must_terms=request.args.get("not_must_terms"),
                           default_es_column=col_search,
                           len_f=len
        )
