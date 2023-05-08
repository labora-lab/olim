from . import app
from .functions import es_search, store_queue
from flask import request, render_template
import secrets
import json

app.secret_key = secrets.token_hex(16)


def get_terms(field):
    value = request.args.get(field, "")
    if len(value) == 0:
        return "[]", [], []
    data = json.loads(value)
    terms = [term.strip() for term in data if len(term.split()) == 1]
    phrases = [term.strip() for term in data if len(term.split()) > 1]
    value = json.dumps([{"tag": term} for term in data])
    return value, terms, phrases


@app.route("/", methods=["GET"])
@app.route("/search", methods=["GET"])
def search():
    include, must_terms, must_phrases = get_terms("include")
    exclude, not_must_terms, not_must_phrases = get_terms("exclude")
    number = int(request.args.get("number", 20))

    only_queue = request.args.get("only-queue", "off")
    only_queue = True if only_queue == 'on' else False    

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

    all_must = must_terms + must_phrases
    all_not = not_must_terms + not_must_phrases
    col_search = "texts.text"
    es_query = {
        "nested": {
            "path": "texts",
            "query": {
                "bool": {"must": [], "must_not": [], "should": []},
            },
        }
    }
    es_sort = [
        {"_score": {"order": "desc"}},
        {"texts.date": {"order": "asc", "nested": {"path": "texts"}}},
    ]

    es_query["nested"]["query"]["bool"]["must"].extend(
        [{"query_string": {"query": term, "fields": [col_search]}} for term in all_must]
    )
    # es_query["nested"]["query"]["bool"]["must"].extend(
    #     [{"match_phrase": {col_search: {"query": phrase}}} for phrase in must_phrases]
    # )
    es_query["nested"]["query"]["bool"]["must_not"].extend(
        [{"query_string": {"query": term, "fields": [col_search]}} for term in all_not]
    )
    # es_query["nested"]["query"]["bool"]["must_not"].extend(
    #     [
    #         {"match_phrase": {col_search: {"query": phrase}}}
    #         for phrase in not_must_phrases
    #     ]
    # )

    # print(json.dumps(es_query, indent=2))

    # pacient_id = cd_usu_cadsus
    results = es_search(query=es_query, sort=es_sort, size=number)["hits"]["hits"]
    patients = []

    for patient in results:
        patients.append(patient['_id'])
        if not only_queue:
            for text in patient["_source"]["texts"]:
                count = 0
                for term in all_must:
                    count += text["text"].count(term)
                text["match_count"] = count
                text["data"] = text["date"].split("T")[0].split("-")
                text["data"].reverse()
                text["data"] = "/".join(text["data"])
            patient["_source"]["texts"].sort(key=lambda t: t["match_count"], reverse=True)


    queue_id = store_queue(patients)

    return render_template(
        "search.html",
        results=results,
        include=include,
        exclude=exclude,
        default_es_column=col_search,
        len_f=len,
        number=number,
        highlight=all_must,
        only_queue=only_queue,
        queue_id=queue_id,
    )
