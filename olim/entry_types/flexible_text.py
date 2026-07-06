import re
from collections.abc import Generator
from typing import Any

import pandas as pd
from flask import render_template
from tqdm import tqdm

from olim.settings import ES_INDEX
from olim.utils.es import es_search

from .base import EntryTypeBase
from .registry import register_entry_type

ENTRY_TYPE = "flexible_text"

_LEGACY_PDF_CONFIG = {
    "text_is_html": True,
    "text_hidden": False,
    "extra_columns": [
        {"column": "pdf_url", "render_as": "pdf", "show_title": False, "as_tab": False}
    ],
    "show_remaining_as_metadata": True,
}


@register_entry_type
class FlexibleTextEntry(EntryTypeBase):
    """Flexible text entry type with configurable column rendering."""

    entry_type = "flexible_text"
    template_path = "entry_types/flexible_text.html"
    show_metadata = True

    def render(self, entry_id: str, **kwargs) -> str | dict:
        dataset_id = kwargs.get("dataset_id")
        if not dataset_id:
            raise ValueError("dataset_id required for flexible_text entries")

        query = {"bool": {"must": [{"terms": {"_id": [entry_id]}}]}}
        res = es_search(query=query, index=ES_INDEX.format(dataset_id=dataset_id))["hits"]["hits"][
            0
        ]

        column_config = kwargs.pop("column_config", None)

        # Auto-detect legacy text_pdf_url entries
        if column_config is None and "pdf_url" in res.get("_source", {}):
            column_config = _LEGACY_PDF_CONFIG

        if column_config is None:
            column_config = {
                "text_is_html": False,
                "text_hidden": False,
                "extra_columns": [],
                "show_remaining_as_metadata": True,
            }

        tabbed_cols = [c for c in column_config.get("extra_columns", []) if c.get("as_tab")]
        content_html = render_template(
            self.template_path, res=res, column_config=column_config, **kwargs
        )

        if tabbed_cols:
            tab_nav_html = render_template(
                "entry_types/flexible_text_tab_nav.html",
                tabbed_cols=tabbed_cols,
                src=res.get("_source", {}),
            )
            return {"html": content_html, "tab_nav": tab_nav_html}

        return content_html

    def extract_texts(self, entry_id: str, **kwargs) -> pd.DataFrame:
        dataset_id = kwargs.get("dataset_id")
        if not dataset_id:
            raise ValueError("dataset_id required for flexible_text entries")

        query = {"bool": {"must": [{"terms": {"_id": [entry_id]}}]}}
        res = es_search(query=query, index=ES_INDEX.format(dataset_id=dataset_id))["hits"]["hits"][
            0
        ]
        return pd.DataFrame({"entry_id": [entry_id], "text": res["_source"]["text"]})

    def search(
        self,
        must_terms: list[str],
        must_phrases: list[str],
        not_must_terms: list[str],
        not_must_phrases: list[str],
        number: int,
        **kwargs,
    ) -> list[dict]:
        dataset_id = kwargs.get("dataset_id")
        if not dataset_id:
            raise ValueError("dataset_id required for flexible_text search")

        all_must = must_terms + must_phrases
        col_search = "text"

        should_clauses = [
            *[{"match": {col_search: term}} for term in must_terms],
            *[{"match_phrase": {col_search: phrase}} for phrase in must_phrases],
        ]
        must_not_clauses = [
            *[{"match": {col_search: term}} for term in not_must_terms],
            *[{"match_phrase": {col_search: phrase}} for phrase in not_must_phrases],
        ]

        es_query: dict = {"bool": {"must_not": must_not_clauses}}
        if should_clauses:
            es_query["bool"]["should"] = should_clauses
            es_query["bool"]["minimum_should_match"] = 1
        else:
            es_query["bool"]["must"] = [{"match_all": {}}]

        results = es_search(
            query=es_query, size=number, index=ES_INDEX.format(dataset_id=dataset_id)
        )["hits"]["hits"]

        patients = []
        for patient in results:
            text = patient["_source"]["text"]
            try:
                patient_desc = " ".join(text.split(" ")[:5]) + "..."
            except IndexError:
                patient_desc = text
            count = sum([text.lower().count(term.lower()) for term in all_must])
            patients.append(
                {
                    "entry_id": patient["_id"],
                    "match_count": count,
                    "description": patient_desc,
                    "score": patient["_score"],
                    "type": self.entry_type,
                }
            )
        return patients

    def search_regex(self, pattern: str, number: int, **kwargs) -> list[dict]:
        dataset_id = kwargs.get("dataset_id")
        if not dataset_id:
            raise ValueError("dataset_id required for flexible_text regex search")

        compiled = re.compile(pattern, re.IGNORECASE)
        batch_size = min(number * 10, 5000)
        hits = es_search(
            query={"match_all": {}},
            size=batch_size,
            index=ES_INDEX.format(dataset_id=dataset_id),
        )["hits"]["hits"]

        results = []
        for h in hits:
            text = h["_source"].get("text", "")
            if compiled.search(text):
                try:
                    desc = " ".join(text.split()[:5]) + "..."
                except IndexError:
                    desc = text
                results.append(
                    {
                        "entry_id": h["_id"],
                        "description": desc,
                        "type": self.entry_type,
                    }
                )
                if len(results) >= number:
                    break
        return results

    def generate_upload_batches(
        self,
        filename: str,
        id_column: str,
        text_column: str,
        batch_size: int = 1000,
        **kwargs,
    ) -> Generator[list[dict[str, Any]]]:
        sep = kwargs.get("sep", ",")
        encoding = kwargs.get("encoding", "utf-8")
        read_kwargs: dict = {"chunksize": batch_size, "sep": sep, "encoding": encoding}
        if len(sep) > 1:
            read_kwargs["engine"] = "python"

        for chunk in tqdm(pd.read_csv(filename, **read_kwargs)):
            chunk = chunk.drop_duplicates(subset=[id_column])
            chunk = chunk.fillna(-1)

            try:
                if "date" in chunk:
                    chunk["date"] = pd.to_datetime(chunk["date"], format="mixed")
            except Exception as e:
                print(f"Failed to convert column dates to datetime: {e!s}")

            records = chunk.to_dict("records")
            batch_entries = []
            seen_ids = set()

            for record in records:
                record_id = record.get(id_column)
                if not record_id or record_id in seen_ids:
                    print(f"Duplicated data on dataset id: {record_id}")
                    continue
                seen_ids.add(record_id)

                text_content = record.get(text_column, "")

                metadata = {}
                for key, value in record.items():
                    if key in [id_column, text_column]:
                        continue
                    if pd.isna(value) or value == "" or value == -1:
                        continue
                    if key == "text":
                        key = "metadata_text"
                    metadata[key] = value

                batch_entries.append(
                    {"id": str(record_id), "text": str(text_content), "metadata": metadata}
                )

            yield batch_entries


# ============================================================================
# Backward Compatibility Layer
# ============================================================================

_instance: FlexibleTextEntry | None = None


def _get_instance() -> FlexibleTextEntry:
    global _instance
    if _instance is None:
        _instance = FlexibleTextEntry()
    return _instance


def render(entry_id: str, dataset_id: int, **pars) -> str | dict:
    return _get_instance().render(entry_id, dataset_id=dataset_id, **pars)


def extract_texts(entry_id: str, dataset_id: int, **pars) -> pd.DataFrame:
    return _get_instance().extract_texts(entry_id, dataset_id=dataset_id, **pars)


def generate_upload_batches(
    filename: str, id_column: str, text_column: str, **pars
) -> Generator[list[dict[str, Any]]]:
    return _get_instance().generate_upload_batches(filename, id_column, text_column, **pars)
