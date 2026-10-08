"""Standalone module for resolving entry sources in queue setup.

Supports five source types:
- random: random sample from project entries
- search: Elasticsearch keyword/phrase search
- regex: Python regex filter applied over ES results
- manual: explicit entry IDs, optionally written as dataset_id:entry_id
- search_per_class: one search per class value of a label, with an equal quota each
"""

from __future__ import annotations

import re

from flask_babel import _

from olim import db
from olim.database import Entry, get_dataset_entry_type, get_label, random_entries
from olim.entry_types.registry import get_entry_type_instance
from olim.label_types import get_class_values

# A queue item is (entry_id, dataset_id): entry IDs are only unique within a dataset.
QueueItem = tuple[str, int]


def resolve_sources(
    sources: list[dict],
    project_id: int | None,
    datasets: list,
) -> tuple[list[QueueItem], list[str]]:
    """Resolve a list of source configs into a deduplicated list of queue items.

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
        (items, problems): deduplicated (entry_id, dataset_id) pairs in encounter
        order, and user-facing messages for manual IDs that could not be resolved.
    """
    seen: set[QueueItem] = set()
    found: list[QueueItem] = []
    problems: list[str] = []

    for src in sources:
        stype = src.get("type", "random")
        try:
            count = max(1, int(src.get("count") or 10))
        except (ValueError, TypeError):
            count = 10

        if stype == "random":
            for e in random_entries(count, project_id):
                item = (e.entry_id, e.dataset_id)
                if item not in seen:
                    seen.add(item)
                    found.append(item)

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
                            item = (r["entry_id"], ds.id)
                            if item not in seen:
                                seen.add(item)
                                found.append(item)
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
                            item = (r["entry_id"], ds.id)
                            if item not in seen:
                                seen.add(item)
                                found.append(item)
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
            items, manual_problems = _resolve_manual(src.get("ids_text", ""), datasets)
            problems.extend(manual_problems)
            for item in items:
                if item not in seen:
                    seen.add(item)
                    found.append(item)

    return found, problems


def resolve_entry_ids(entry_ids: list[str], datasets: list) -> tuple[list[QueueItem], list[str]]:
    """Resolve a list of IDs (bare or dataset_id:entry_id) like the manual source does."""
    return _resolve_manual("\n".join(entry_ids), datasets)


def _resolve_manual(ids_text: str, datasets: list) -> tuple[list[QueueItem], list[str]]:
    """Pin each typed ID to the dataset that holds it.

    A bare ID is accepted when exactly one of the project's datasets has it. When
    several do, the user has to say which one with the dataset_id:entry_id form.
    """
    lines = [x.strip() for x in ids_text.splitlines() if x.strip()]
    by_id = {ds.id: ds for ds in datasets}
    if not lines or not by_id:
        return [], []

    # Read every line both as a bare ID and, when it has one, as a dataset prefix.
    prefixed: dict[str, QueueItem] = {}
    for line in lines:
        ds_part, sep, eid = line.partition(":")
        if sep and ds_part.strip().isdigit() and int(ds_part) in by_id and eid.strip():
            prefixed[line] = (eid.strip(), int(ds_part))

    candidates = set(lines) | {eid for eid, _ds in prefixed.values()}
    rows = db.session.execute(
        db.select(Entry.entry_id, Entry.dataset_id).where(
            Entry.entry_id.in_(candidates), Entry.dataset_id.in_(list(by_id))
        )
    ).all()
    locations: dict[str, list[int]] = {}
    for entry_id, dataset_id in rows:
        locations.setdefault(entry_id, []).append(dataset_id)

    items: list[QueueItem] = []
    missing: list[str] = []
    problems: list[str] = []
    for line in lines:
        found_in = sorted(locations.get(line, []))
        if len(found_in) == 1:
            items.append((line, found_in[0]))
        elif len(found_in) > 1:
            names = ", ".join(f"{by_id[ds_id].name} ({ds_id})" for ds_id in found_in)
            problems.append(
                _(
                    "Entry {entry_id} exists in more than one dataset: {datasets}. "
                    "Write it as {example} to pick one."
                ).format(entry_id=line, datasets=names, example=f"{found_in[0]}:{line}")
            )
        elif line in prefixed and prefixed[line][1] in locations.get(prefixed[line][0], []):
            items.append(prefixed[line])
        else:
            missing.append(line)

    if missing:
        problems.append(
            _("Entries not found in this project's datasets: {ids}").format(ids=", ".join(missing))
        )
    return items, problems


def _search_per_class(
    label_id: int | None,
    terms: dict[str, str],
    total: int,
    datasets: list,
    seen: set[QueueItem],
) -> list[QueueItem]:
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
    found: list[QueueItem] = []
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
                item = (result["entry_id"], dataset.id)
                if item not in seen:
                    seen.add(item)
                    found.append(item)
    return found
