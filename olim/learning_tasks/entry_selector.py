"""Standalone module for resolving entry sources in queue setup.

Supports four source types:
- random: random sample from project entries
- search: Elasticsearch keyword/phrase search
- regex: Python regex filter applied over ES results
- manual: explicit entry IDs
"""
from __future__ import annotations

import re

from olim.database import get_dataset_entry_type, random_entries
from olim.entry_types.registry import get_entry_type_instance


def resolve_sources(
    sources: list[dict],
    project_id: int | None,
    datasets: list,
) -> list[str]:
    """Resolve a list of source configs into a deduplicated list of entry IDs.

    Args:
        sources: List of source dicts with keys:
            - type: "random" | "search" | "regex" | "manual"
            - count: int (random/search/regex)
            - term: str (search)
            - pattern: str (regex)
            - ids_text: str (manual, newline-separated)
        project_id: Project ID for random/search sources
        datasets: Dataset ORM objects for search/regex sources

    Returns:
        Deduplicated list of entry IDs in encounter order.
    """
    seen: set[str] = set()
    found: list[str] = []

    for src in sources:
        stype = src.get("type", "random")
        try:
            count = max(1, int(src.get("count") or 10))
        except (ValueError, TypeError):
            count = 10

        if stype == "random":
            for e in random_entries(count, project_id):
                if e.entry_id not in seen:
                    seen.add(e.entry_id)
                    found.append(e.entry_id)

        elif stype == "search":
            term = src.get("term", "").strip()
            if not term:
                continue
            for ds in datasets:
                ds_type = get_dataset_entry_type(ds.id) or "single_text"
                inst = get_entry_type_instance(ds_type)
                if inst is not None and hasattr(inst, "search"):
                    try:
                        results = inst.search(
                            must_terms=[term],
                            must_phrases=[],
                            not_must_terms=[],
                            not_must_phrases=[],
                            number=count,
                            dataset_id=ds.id,
                        )
                        for r in results:
                            eid = r["entry_id"]
                            if eid not in seen:
                                seen.add(eid)
                                found.append(eid)
                    except Exception:
                        pass

        elif stype == "regex":
            pattern = src.get("pattern", "").strip()
            if not pattern:
                continue
            try:
                re.compile(pattern)
            except re.error:
                continue
            for ds in datasets:
                ds_type = get_dataset_entry_type(ds.id) or "single_text"
                inst = get_entry_type_instance(ds_type)
                if inst is not None and hasattr(inst, "search_regex"):
                    try:
                        results = inst.search_regex(
                            pattern=pattern,
                            number=count,
                            dataset_id=ds.id,
                        )
                        for r in results:
                            eid = r["entry_id"]
                            if eid not in seen:
                                seen.add(eid)
                                found.append(eid)
                    except Exception:
                        pass

        elif stype == "manual":
            for eid in (x.strip() for x in src.get("ids_text", "").splitlines() if x.strip()):
                if eid not in seen:
                    seen.add(eid)
                    found.append(eid)

    return found
