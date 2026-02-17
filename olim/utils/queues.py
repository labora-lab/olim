## Auxiliary functions
# All functions here must have type hints and docstrings
from flask import session
from flask_babel import _

from ..database import delete_queue_by_id, get_queue_by_id, get_queues_for_project, new_queue


def parse_queue(text: str) -> list[str]:
    """Parse a queue input into a queue list.

    Args:
        text (str): Queue input

    Returns:
        List[str]: Queue list
    """
    # TODO: Rewrite this to deal with dataset_id
    return text.replace(";", " ").replace(",", " ").replace("\n", " ").replace("\r\n", " ").split()


def generate_queue_name(
    queue_type: str,
    number: int | None = None,
    include_terms: list[str] | None = None,
    exclude_terms: list[str] | None = None,
) -> str:
    """Auto-generate queue name based on type and parameters.

    Args:
        queue_type: Type of queue ("search", "random", "manual")
        number: Number of entries (for random queues)
        include_terms: Search include terms
        exclude_terms: Search exclude terms

    Returns:
        Generated queue name
    """
    if queue_type == "search":
        parts = []
        if include_terms:
            parts.append(", ".join(include_terms[:3]))  # Limit to first 3 terms
            if len(include_terms) > 3:
                parts[-1] += "..."
        if exclude_terms:
            parts.append(_("excluding") + " " + ", ".join(exclude_terms[:2]))
            if len(exclude_terms) > 2:
                parts[-1] += "..."

        if parts:
            return _("Search: {terms}").format(terms=" - ".join(parts))
        else:
            return _("Search Results")

    elif queue_type == "random":
        return _("Random Sample ({count} entries)").format(count=number)

    elif queue_type == "manual":
        return _("Manual Queue ({count} entries)").format(count=number)

    return _("Queue")


def store_queue(
    queue: list[tuple[int, str]],
    project_id: int,
    highlight: list[str] | None = None,
    name: str | None = None,
    queue_type: str | None = None,
    **extra_data: dict,
) -> str:
    """Store a queue in the database.

    Args:
        queue: Queue list of (dataset_id, entry_id) tuples
        project_id: Project ID
        highlight: Optional list of highlight terms
        name: Optional queue name (auto-generated if not provided)
        queue_type: Type for auto-naming ("search", "random", "manual")
        **extra_data: Additional metadata

    Returns:
        str: Queue ID (MD5 hash)
    """
    queue_list = list(queue)

    # Auto-generate name if not provided
    if name is None:
        if queue_type == "search":
            include_raw = extra_data.get("Include", [])
            exclude_raw = extra_data.get("Exclude", [])
            include = include_raw if isinstance(include_raw, list) else []
            exclude = exclude_raw if isinstance(exclude_raw, list) else []
            name = generate_queue_name("search", include_terms=include, exclude_terms=exclude)
        elif queue_type == "random":
            name = generate_queue_name("random", number=len(queue_list))
        else:
            name = generate_queue_name("manual", number=len(queue_list))

    # Get user_id from session
    user_id = session.get("user_id", 1)

    # Create queue in database
    queue_obj = new_queue(
        queue_data=queue_list,
        name=name,
        project_id=project_id,
        user_id=user_id,
        highlight=highlight,
        **extra_data,
    )

    return queue_obj.id


def get_queue(queue_id: str, project_id: int) -> list[tuple[int, str]]:
    """Load queue data by ID.

    Args:
        queue_id (str): Queue ID (MD5 hash)
        project_id: Project ID for validation

    Returns:
        list[tuple[int, str]]: Queue list of (dataset_id, entry_id)

    Raises:
        FileNotFoundError: If queue doesn't exist (for compatibility)
    """
    queue = get_queue_by_id(queue_id, project_id)

    if queue is None:
        raise FileNotFoundError(f"Queue {queue_id} not found")

    # Handle highlight merging (same logic as before)
    if queue.highlight is not None:
        raw_highlights = session.get(
            "highlight", {"terms": [], "colorAssignments": {}, "colorCounter": 0}
        )

        # Handle both old format (list) and new format (dict)
        if isinstance(raw_highlights, list):
            existing_highlights: dict = {
                "terms": raw_highlights,
                "colorAssignments": {},
                "colorCounter": len(raw_highlights),
            }
        else:
            existing_highlights = {
                "terms": raw_highlights.get("terms", []),
                "colorAssignments": raw_highlights.get("colorAssignments", {}),
                "colorCounter": raw_highlights.get("colorCounter", 0),
            }

        queue_highlights = queue.highlight

        # Ensure terms is a list
        existing_terms = existing_highlights.get("terms", [])
        if not isinstance(existing_terms, list):
            existing_terms = []

        existing_assignments = existing_highlights.get("colorAssignments", {})
        if not isinstance(existing_assignments, dict):
            existing_assignments = {}

        existing_counter = existing_highlights.get("colorCounter", 0)
        if not isinstance(existing_counter, int):
            existing_counter = 0

        if set(queue_highlights) != set(existing_terms):
            merged_terms = list(existing_terms)
            merged_color_assignments = existing_assignments.copy()
            color_counter = existing_counter

            for highlight in queue_highlights:
                if highlight not in merged_terms:
                    merged_terms.append(highlight)
                    if highlight not in merged_color_assignments:
                        merged_color_assignments[highlight] = color_counter % 8
                        color_counter += 1

            session["highlight"] = {
                "terms": merged_terms,
                "colorAssignments": merged_color_assignments,
                "colorCounter": color_counter,
            }

    return queue.queue_data


def delete_queue(queue_id: str, project_id: int) -> bool:
    """Delete a queue.

    Args:
        queue_id (str): Queue ID to delete
        project_id (int): Project ID for validation

    Returns:
        bool: True if deleted successfully, False otherwise
    """
    user_id = session.get("user_id", 1)
    return delete_queue_by_id(queue_id, project_id, user_id)


def get_all_queues(project_id: int) -> list[dict]:
    """Get all queues for a project formatted for display.

    Args:
        project_id: Project ID

    Returns:
        List of queue dictionaries with frontend display data
    """
    queues = get_queues_for_project(project_id)

    result = []
    for queue in queues:
        queue_dict = {
            "id": queue.id,
            "name": queue.name,
            "lenght": queue.length,  # Keep typo for backward compatibility
            "highlight": queue.highlight,
            "extra_data": queue.extra_data or {},
            "frontend_text": _("Entries: {queue_length}").format(queue_length=queue.length),
        }

        # Add highlight info to frontend text
        if queue.highlight:
            queue_dict["frontend_text"] += " - " + _("Highlight: {highlight}").format(
                highlight=", ".join(h for h in queue.highlight)
            )

        result.append(queue_dict)

    return result
