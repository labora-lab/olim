from . import app
from flask import request, render_template, redirect, url_for, g
from elasticsearch import Elasticsearch
from elasticsearch_dsl import Search
import secrets
import json
from .settings import TEXT_CONTENT

app.secret_key = secrets.token_hex(16)

server_file = json.load(open("server_credentials.json"))
es_index = "cpf_prontuarios"

@app.route("/search", methods=["GET", "POST"])
def search():
    if request.method == "GET":
        return render_template("search.html", context={})
    ## return early here
    must_terms = [x.strip() for x in request.form["must_terms"].split(",") if x.strip()]
    must_phrases = [x.strip() for x in request.form["must_phrases"].split(";") if x.strip()]
    not_must_terms = [x.strip() for x in request.form["not_must_terms"].split(",") if x.strip()]
    not_must_phrases = [x.strip() for x in request.form["not_must_phrases"].split(";") if x.strip()]

    client = Elasticsearch(**server_file)
    es_query = {
        "bool": {
            "must": [],
            "must_not": [],
            "should": []
        }
    }

    es_query["bool"]["must"].extend([{"query_string": {"query": term, "fields": [TEXT_CONTENT]}} for term in must_terms])

    es_query["bool"]["must"].extend([{"match_phrase": {TEXT_CONTENT: {"query": phrase}}} for phrase in must_phrases])

    es_query["bool"]["must_not"].extend([{"query_string": {"query": term, "fields": [TEXT_CONTENT]}} for term in not_must_terms])

    es_query["bool"]["must_not"].extend([{"match_phrase": {TEXT_CONTENT: {"query": phrase}}} for phrase in not_must_phrases])

    print(json.dumps(es_query, indent=2))

    print(es_query)
    # pacient_id = cd_usu_cadsus
    resp = client.search(
        index=es_index,
        query=es_query
    )

    return render_template("search.html", results=resp["hits"]["hits"], must_terms=request.form["must_terms"], must_phrases=request.form["must_phrases"], not_must_phrases=request.form["not_must_phrases"], not_must_terms=request.form["not_must_terms"])