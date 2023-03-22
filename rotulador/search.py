from . import app
from .functions import es_list_fields, es_search
from flask import request, render_template
import secrets
import json
from .settings import ES_MAPPINGS

app.secret_key = secrets.token_hex(16)

@app.route("/search", methods=["GET", "POST"])
def search():
    index_columns = es_list_fields()
    if request.method == "GET":
        return render_template("search.html",
                               es_columns=index_columns,
                               default_es_column=ES_MAPPINGS['TEXT_CONTENT'])

    must_terms = [x.strip() for x in request.form["must_terms"].split(",") if x.strip()]
    must_phrases = [x.strip() for x in request.form["must_phrases"].split(";") if x.strip()]
    not_must_terms = [x.strip() for x in request.form["not_must_terms"].split(",") if x.strip()]
    not_must_phrases = [x.strip() for x in request.form["not_must_phrases"].split(";") if x.strip()]
    col_search = request.form["column_for_search"]
    aggregate = request.form.get("aggregate", False, type=bool)

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

    print(json.dumps(es_query, indent=2))

    # pacient_id = cd_usu_cadsus
    resp = es_search(
        query=es_query,
        size=10000
    )

    if not aggregate:
        results = resp["hits"]["hits"]
    else:
        results = {}
        for result in resp["hits"]["hits"]:
            value = results.get(result["_source"][ES_MAPPINGS['ID_PATIENT']], [])
            value.append(result)
            results[result["_source"][ES_MAPPINGS['ID_PATIENT']]] = value

    return render_template("search.html",
                           results=results,
                           must_terms=request.form["must_terms"],
                           must_phrases=request.form["must_phrases"],
                           not_must_phrases=request.form["not_must_phrases"],
                           not_must_terms=request.form["not_must_terms"],
                           es_columns=index_columns,
                           default_es_column=col_search,
                           aggregated=aggregate,
                           len_f=len
        )
