from ...functions import es_search
from . import ENTRY_TYPE, ES_INDEX


def search(
    must_terms: list[str],
    must_phrases: list[str],
    not_must_terms: list[str],
    not_must_phrases: list[str],
    number: int,
) -> list[dict]:
    all_must = must_terms + must_phrases
    all_not = not_must_terms + not_must_phrases
    col_search = "texts.text"

    # Create query
    es_query = {
        "nested": {
            "path": "texts",
            "query": {
                "bool": {"must": [], "must_not": [], "should": []},
            },
        }
    }

    # Sort decrescent on score
    es_sort = [
        {"_score": {"order": "desc"}},
        {"texts.date": {"order": "asc", "nested": {"path": "texts"}}},
    ]

    # Add must and must not therms anf phrases
    es_query["nested"]["query"]["bool"]["must"].extend(
        [{"query_string": {"query": term, "fields": [col_search]}} for term in all_must]
    )
    es_query["nested"]["query"]["bool"]["must_not"].extend(
        [{"query_string": {"query": term, "fields": [col_search]}} for term in all_not]
    )

    # Runs query
    results = es_search(query=es_query, sort=es_sort, size=number, index=ES_INDEX)["hits"]["hits"]

    # Aggregates results
    patients = []
    for patient in results:
        texts = patient["_source"]["texts"]
        # Count matchs
        count = 0
        for text in texts:
            for term in all_must:
                count += text["text"].lower().count(term.lower())
        patient_desc = f"{len(texts)} texts"
        patients.append(
            {
                "entry_id": patient["_id"],
                "match_count": count,
                "description": patient_desc,
                "score": patient["_score"],
                "type": ENTRY_TYPE,
            }
        )

    return patients
