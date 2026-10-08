import re
from collections.abc import Generator, Iterable
from typing import Any

import pandas as pd
from flask import render_template
from flask_babel import gettext as _
from tqdm import tqdm

from olim.settings import ES_INDEX
from olim.utils.es import es_search

from .base import EntryTypeBase, prepare_id_column
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

DEFAULT_COLUMN_CONFIG = {
    "text_is_html": False,
    "text_hidden": False,
    "extra_columns": [],
    "show_remaining_as_metadata": True,
}
RENDER_AS = ("text", "html", "pdf", "image", "json")


def normalize_column_config(raw: object, fields: Iterable[str]) -> dict[str, Any]:
    """Validate display settings sent by the column configuration editor.

    Args:
        raw: Config dict (see DEFAULT_COLUMN_CONFIG)
        fields: Document fields an extra column may show

    Raises:
        ValueError: with a user-facing message for unknown columns or render modes
    """
    if not isinstance(raw, dict):
        raise ValueError(_("Invalid column configuration."))
    allowed = set(fields)
    extra_columns = []
    seen = set()
    for item in raw.get("extra_columns") or []:
        column = item.get("column") if isinstance(item, dict) else None
        if column not in allowed:
            raise ValueError(_("Unknown column: %(column)s", column=column))
        if column in seen:
            continue
        render_as = "pdf" if item.get("render_as") == "pdf_url" else item.get("render_as", "text")
        if render_as not in RENDER_AS:
            raise ValueError(_("Unknown display mode: %(mode)s", mode=render_as))
        seen.add(column)
        extra_columns.append(
            {
                "column": column,
                "render_as": render_as,
                "show_title": bool(item.get("show_title")),
                "as_tab": bool(item.get("as_tab")),
            }
        )
    return {
        "text_is_html": bool(raw.get("text_is_html")),
        "text_hidden": bool(raw.get("text_hidden")),
        "extra_columns": extra_columns,
        "show_remaining_as_metadata": bool(raw.get("show_remaining_as_metadata", True)),
    }


def current_column_config(column_config: dict | None, fields: Iterable[str]) -> dict[str, Any]:
    """The config entries of a dataset are rendered with (see FlexibleTextEntry.render)."""
    if column_config is not None:
        return column_config
    return _LEGACY_PDF_CONFIG if "pdf_url" in fields else DEFAULT_COLUMN_CONFIG


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
            column_config = DEFAULT_COLUMN_CONFIG

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
            # Trim IDs and stop on empty or repeated ones; never drop rows silently
            rows = prepare_id_column(chunk, id_column)
            chunk = chunk.fillna(-1)

            try:
                if "date" in chunk:
                    chunk["date"] = pd.to_datetime(chunk["date"], format="mixed")
            except Exception as e:
                print(f"Failed to convert column dates to datetime: {e!s}")

            records = chunk.to_dict("records")
            batch_entries = []

            for row, record in zip(rows, records, strict=True):
                record_id = record.get(id_column)

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
                    {
                        "id": str(record_id),
                        "text": str(text_content),
                        "metadata": metadata,
                        "row": row,
                    }
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
