"""Standalone module for resolving entry sources in queue setup.

Supports five source types:
- random: random sample from project entries
- search: Elasticsearch keyword/phrase search
- regex: Python regex filter applied over ES results
- manual: explicit entry IDs
- search_per_class: one search per class value of a label, with an equal quota each
"""

from __future__ import annotations

import re

from olim.database import get_dataset_entry_type, get_label, random_entries
from olim.entry_types.registry import get_entry_type_instance
from olim.label_types import get_class_values


def resolve_sources(
    sources: list[dict],
    project_id: int | None,
    datasets: list,
) -> list[str]:
    """Resolve a list of source configs into a deduplicated list of entry IDs.

    Args:
        sources: List of source dicts with keys:
            - type: "random" | "search" | "regex" | "manual" | "search_per_class"
            - count: int (random/search/regex; total budget for search_per_class)
            - term: str (search)
            - pattern: str (regex)
            - ids_text: str (manual, newline-separated)
            - label_id: int (search_per_class)
            - terms: {class_value: search term} (search_per_class)
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

        elif stype == "search_per_class":
            # One search per class value with an equal share of the budget, so a rare
            # class gets seeded too. A plain "search" source hands its whole quota to
            # whichever term matches most, which is how cold starts end up with no
            # positive examples at all.
            found.extend(
                _search_per_class(
                    label_id=src.get("label_id"),
                    terms=src.get("terms") or {},
                    total=count,
                    datasets=datasets,
                    seen=seen,
                )
            )

        elif stype == "manual":
            for eid in (x.strip() for x in src.get("ids_text", "").splitlines() if x.strip()):
                if eid not in seen:
                    seen.add(eid)
                    found.append(eid)

    return found


def _search_per_class(
    label_id: int | None,
    terms: dict[str, str],
    total: int,
    datasets: list,
    seen: set[str],
) -> list[str]:
    """Run one search per class value, each capped at an equal share of `total`."""
    if not label_id or not datasets:
        return []
    label = get_label(int(label_id))
    if label is None:
        return []

    class_values = get_class_values(label)
    if not class_values:
        return []

    per_class = max(1, total // len(class_values))
    found: list[str] = []
    for class_value in class_values:
        term = str(terms.get(class_value, "")).strip()
        if not term:
            continue
        for dataset in datasets:
            dataset_type = get_dataset_entry_type(dataset.id) or "single_text"
            instance = get_entry_type_instance(dataset_type)
            if instance is None or not hasattr(instance, "search"):
                continue
            try:
                results = instance.search(
                    must_terms=[term],
                    must_phrases=[],
                    not_must_terms=[],
                    not_must_phrases=[],
                    number=per_class,
                    dataset_id=dataset.id,
                )
            except Exception:
                continue
            for result in results:
                entry_id = result["entry_id"]
                if entry_id not in seen:
                    seen.add(entry_id)
                    found.append(entry_id)
    return found
