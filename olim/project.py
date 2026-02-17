import json
import shutil
from datetime import datetime
from io import StringIO

import pandas as pd
from flask import flash, redirect, render_template, request, session, url_for
from flask_babel import _

from . import app, entry_types
from .database import (
    del_controled,
    get_datasets,
    get_entries,
    get_labels,
    get_project,
    get_projects,
    new_project,
    random_entries,
)
from .functions import (
    get_def_nentries,
    get_highlights,
    render_entry,
)
from .settings import QUEUES_PATH
from .utils.entry import get_all_hidden
from .utils.queues import delete_queue, get_all_queues, get_queue, store_queue


def backup_old_queue_folder(project_id: int) -> None:
    """
    Backup old queue folder if it exists for the given project ID.

    Args:
        project_id: The project ID to check and backup queues for
    """
    old_queue_path = QUEUES_PATH / str(project_id)

    if old_queue_path.exists() and old_queue_path.is_dir():
        # Create backup with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = QUEUES_PATH / f"{project_id}_backup_{timestamp}"

        try:
            shutil.move(str(old_queue_path), str(backup_path))
            print(f"Backed up old queue folder {old_queue_path} to {backup_path}")
        except Exception as e:
            print(f"Failed to backup queue folder: {e}")


@app.route("/")
def redirect_to_project() -> ...:
    project_id = session.get("project_id")
    project_id = project_id or get_projects()[0].id
    session["project_id"] = project_id
    return redirect(f"/{project_id}")


def update_session_project(project_id: int, require_data: bool = False) -> ...:
    """
    Check if project exists and optionally if it has data.

    Args:
        project_id: The project ID to check
        require_data: If True, redirect to upload if project has no datasets

    Returns:
        None if project is valid, redirect response otherwise
    """
    # First, check if project exists and update session
    if session.get("project_id") != project_id:
        project = get_project(project_id)
        print(f"Loaded project: {project}")
        if project is None or project.is_deleted:
            flash(
                _("Invalid project ID: {project_id}!").format(project_id=project_id),
                category="warning",
            )
            session.pop("project_id", None)
            session.pop("project_name", None)
            return redirect("/")
        else:
            session["project_id"] = project.id
            session["project_name"] = project.name
            app.jinja_env.globals.update(
                project_id=project.id,
                project_name=project.name,
            )

    # AFTER confirming project exists, check if data is required
    if require_data:
        datasets = list(get_datasets(project_id, non_empty=True))
        if not datasets:
            flash(_("This project has no datasets. Please upload data first."), "warning")
            return redirect(url_for("upload_data", project_id=project_id))

    return None


def update_queue_pos(queue_id: str, pos: int) -> None:
    if "queue_pos" not in session:
        session["queue_pos"] = {}

    session["queue_pos"][queue_id] = pos


def get_queue_pos(queue_id: str) -> int:
    if "queue_pos" not in session:
        session["queue_pos"] = {}

    if queue_id in session["queue_pos"]:
        return session["queue_pos"][queue_id]
    else:
        session["queue_pos"][queue_id] = 1
        return 1


# region Entry routes and functions
# --------------------------------


@app.route("/<int:project_id>/entry", methods=["GET"])
@app.route("/<int:project_id>/entry/<int:dataset_id>/<entry_id>", methods=["GET"])
@app.route("/<int:project_id>/queue/<queue_id>", methods=["GET"])
@app.route("/<int:project_id>/queue/<queue_id>/<int:queue_pos>", methods=["GET"])
def entry(
    project_id: int,
    dataset_id: int | None = None,
    entry_id: str | None = None,
    queue_id: str | None = None,
    queue_pos: int | None = None,
) -> ...:
    # Check project_id
    res = update_session_project(project_id)
    if res is not None:
        return res

    hidden_labels = session.get("hidden_labels", [])

    show_hidden = request.args.get("show-hidden", False) == "True"

    data: dict = {
        "valid_entry": False,
        "show_hidden": show_hidden,
    }

    # Load queue (queue must be loaded before highlight)
    if queue_id is not None:
        if queue_pos is None:
            queue_pos = get_queue_pos(queue_id)
        try:
            queue = get_queue(queue_id, project_id)

            # Check if queue is empty
            if len(queue) == 0:
                flash(
                    _("Queue {queue_id} is empty").format(queue_id=queue_id),
                    category="error",
                )
                queue_id = None
            # Check if position is out of range
            elif queue_pos < 1 or queue_pos > len(queue):
                flash(
                    _(
                        "Position {pos} is out of range for queue (size: {size}). "
                        "Redirecting to position 1."
                    ).format(pos=queue_pos, size=len(queue)),
                    category="warning",
                )
                # Reset to position 1 and redirect
                update_queue_pos(queue_id, 1)
                return redirect(
                    url_for("entry", project_id=project_id, queue_id=queue_id, queue_pos=1)
                )
            else:
                dataset_id, entry_id = queue[queue_pos - 1]
                update_queue_pos(queue_id, queue_pos)
                data.update(
                    {
                        "queue_id": queue_id,
                        "queue_len": len(queue),
                        "queue_pos": queue_pos,
                    }
                )
        except FileNotFoundError:
            flash(
                _("Queue {queue_id} not found").format(queue_id=queue_id),
                category="error",
            )
            queue_id = None
        except Exception as e:
            app.logger.error(f"Error loading queue {queue_id}: {e}", exc_info=True)
            flash(
                _("Error loading queue: {error}").format(error=str(e)),
                category="error",
            )
            queue_id = None

    # Check if entry exists ans try to render it
    data = render_entry(entry_id, dataset_id, data)

    data.update(
        {
            "show_hidden": show_hidden,
            "labels": get_labels(project_id=project_id),
            "highlight": get_highlights(),
            "hidden_labels": hidden_labels,
            "datasets": list(get_datasets(project_id)),
        }
    )

    return render_template("entry.html", **data)


@app.route("/<int:project_id>/hidden", methods=["GET"])
def hidden(project_id: int) -> ...:
    # Check project_id
    res = update_session_project(project_id)
    if res is not None:
        return res

    result = get_all_hidden(project_id)
    res = []
    for r in result:
        res.append(dict(r["_source"]))
    return render_template("hidden.html", res=res)


# endregion

# region Search routes and functions
# --------------------------------


def get_terms(field) -> tuple[str, list[str], list[str]]:
    value = request.args.get(field, "")
    if len(value) == 0:
        return "[]", [], []
    data = json.loads(value)
    terms = [term.strip() for term in data if len(term.split()) == 1]
    phrases = [term.strip() for term in data if len(term.split()) > 1]
    value = json.dumps([{"tag": term} for term in data])
    return value, terms, phrases


@app.route("/<int:project_id>/search", methods=["GET"])
def search(project_id: int) -> ...:
    # Check project_id
    res = update_session_project(project_id)
    if res is not None:
        return res

    include, must_terms, must_phrases = get_terms("include")
    exclude, not_must_terms, not_must_phrases = get_terms("exclude")
    number = int(request.args.get("number", get_def_nentries()))
    session["number_of_entries"] = number

    # only_queue = request.args.get("only-queue", "off")
    # only_queue = True if only_queue == "on" else False

    # No search return empty page
    if (
        len(must_terms) == 0
        and len(must_phrases) == 0
        and len(not_must_terms) == 0
        and len(not_must_phrases) == 0
    ):
        # Check if this is an HTMX request for search results only
        if request.headers.get("HX-Request"):
            return ""  # Return empty content for HTMX

        # Redirect to data navigation for direct access
        return redirect(url_for("data_navigation", project_id=project_id))

    session["highlight"] = must_terms + must_phrases

    project = get_project(project_id)
    if project is None:
        raise ValueError("Error loading project, this shouldn't happen...")

    data = []
    dataset_ids = []
    for mod in dir(entry_types):
        if get_entries(type=mod).all():
            module = getattr(entry_types, mod)
            if hasattr(module, "search"):
                for dataset in project.datasets:
                    this_data = module.search(
                        must_terms=must_terms,
                        must_phrases=must_phrases,
                        not_must_terms=not_must_terms,
                        not_must_phrases=not_must_phrases,
                        number=number,
                        dataset_id=dataset.id,
                    )
                    dataset_ids += [dataset.id] * len(this_data)
                    data += this_data

    highlight = must_terms + must_phrases
    if len(data) > 0:
        df_results = pd.DataFrame(data)
        df_results["dataset_id"] = dataset_ids
        df_results = df_results[df_results["match_count"] > 0]
        df_results = df_results.sort_values(by="score", ascending=False, ignore_index=True).iloc[
            :number
        ]
        data = df_results.to_dict("records")
        extra_data: dict = {
            "Include": must_terms + must_phrases,
            "Exclude": not_must_terms + not_must_phrases,
        }
        queue_id = store_queue(
            [(row["dataset_id"], row["entry_id"]) for _, row in df_results.iterrows()],
            project_id,
            highlight=highlight,
            queue_type="search",  # Auto-generate search queue name
            **extra_data,
        )
    else:
        queue_id = None

    # Check if this is an HTMX request for search results only
    if request.headers.get("HX-Request"):
        return render_template(
            "components/search-results.html",
            n_results=len(data),
            queue_id=queue_id,
        )

    # Redirect to data navigation for direct access
    return redirect(url_for("data_navigation", project_id=project_id))


# endregion


# region Queues routes and functions
# --------------------------------


@app.route("/<int:project_id>/queue", methods=["POST", "GET"])
@app.route("/<int:project_id>/list-queue/<queue_id>", methods=["GET"])
def queue(project_id: int, queue_id: str | None = None) -> ...:
    # Check project_id
    res = update_session_project(project_id)
    if res is not None:
        return res

    # If a we have a queue_id load that queue
    if queue_id is not None:
        try:
            queue = get_queue(queue_id, project_id)
            datasets = {
                dataset.id: dataset.name
                for dataset in get_datasets(project_id=project_id, non_empty=True)
            }
            datasets = datasets if len(datasets) > 1 else None
            return render_template(
                "queue.html",
                queue=queue,
                queue_id=queue_id,
                datasets=datasets,
            )
        except FileNotFoundError:
            flash(_("Queue not found or has been deleted"), category="warning")
            return redirect(
                url_for("data_navigation", project_id=project_id, section="queue-management")
            )

    # Check if we have a rquest
    type = request.form.get("type", "")
    queue = []
    # If our request is of type random
    if type == "random":
        try:
            # Try to parse the number and store it
            number = int(request.form.get("number", ""))
            session["number_of_entries"] = number
            # Generate the queue
            queue = [
                (entry.dataset_id, entry.entry_id) for entry in random_entries(number, project_id)
            ]
        except ValueError:
            flash(_("Invalid number of entries"), category="error")
    # If our request is of type list
    # elif type == "list":
    #     # Try to parse the list and store it
    #     queue = parse_queue(request.form.get("text", ""))

    # If we have a populated queue store it and redirect by the id
    if len(queue) > 0:
        extra_data: dict = {"Randomly generated": True}
        queue_id = store_queue(
            queue,
            project_id,
            queue_type="random",  # Auto-generate random queue name
            **extra_data,
        )
        # Redirect to the first entry in the queue
        return redirect(url_for("entry", project_id=project_id, queue_id=queue_id, queue_pos=1))
    # If not redirect to data navigation
    else:
        return redirect(url_for("data_navigation", project_id=project_id))


# endregion


# region Data Navigation route
# --------------------------------


@app.route("/<int:project_id>/data-navigation", methods=["GET"])
def data_navigation(project_id: int) -> ...:
    """Data navigation dashboard consolidating entry navigation, search, and queue management"""
    # Check project_id and require data
    res = update_session_project(project_id, require_data=True)
    if res is not None:
        return res

    # Get datasets
    datasets = list(get_datasets(project_id))

    # Get queues
    queues = get_all_queues(project_id)

    # Get number of entries from session or default
    number = session.get("number_of_entries", get_def_nentries())

    # No stats calculation needed for data navigation page
    stats = None

    # Get section parameter for directing to specific component
    section = request.args.get("section", "entry-navigation")  # Default to entry navigation

    return render_template(
        "data-navigation.html",
        datasets=datasets,
        queues=queues,
        number=number,
        stats=stats,
        active_section=section,
    )


@app.route("/<int:project_id>/data-navigation/component/<component_name>", methods=["GET"])
def data_navigation_component(project_id: int, component_name: str) -> ...:
    """Load individual data navigation components via HTMX"""
    # Check project_id
    res = update_session_project(project_id)
    if res is not None:
        return res

    # Validate component name
    valid_components = [
        "entry-navigation",
        "text-search",
        "random-queue",
        "queue-management",
    ]
    if component_name not in valid_components:
        return "Invalid component", 404

    # Get required data based on component
    context = {}

    # Always include project_id in context
    context["project_id"] = project_id

    if component_name in ["entry-navigation", "text-search", "random-queue"]:
        context["datasets"] = list(get_datasets(project_id))

    if component_name == "random-queue":
        context["number"] = session.get("number_of_entries", get_def_nentries())

    if component_name == "queue-management":
        try:
            context["queues"] = get_all_queues(project_id)
        except Exception as e:
            print(f"Error getting queues: {e}")
            context["queues"] = []

    return render_template(f"components/{component_name}.html", **context)


@app.route("/<int:project_id>/data-navigation/queue/<queue_id>/delete", methods=["DELETE"])
def delete_queue_route(project_id: int, queue_id: str) -> ...:
    """Delete a queue"""
    # Check project_id
    res = update_session_project(project_id)
    if res is not None:
        return res

    # Delete the queue
    success = delete_queue(queue_id, project_id)

    if success:
        return "", 200
    else:
        return "", 404


@app.route("/<int:project_id>/queue/<queue_id>/delete-entries", methods=["POST"])
def delete_queue_entries(project_id: int, queue_id: str) -> ...:
    """Delete selected entries from a queue"""
    from flask import jsonify

    from . import auth
    from .database import db, get_queue_by_id

    # Check project_id
    res = update_session_project(project_id)
    if res is not None:
        return res

    # Check admin permission
    if not auth.role_has_permission(role="admin"):
        return jsonify({"error": "Admin permission required"}), 403

    try:
        # Get indices to delete from request
        if request.json is None:
            return jsonify({"error": "No JSON data provided"}), 400
        indices_to_delete = request.json.get("indices", [])
        if not indices_to_delete:
            return jsonify({"error": "No indices provided"}), 400

        # Load the queue from database
        queue_obj = get_queue_by_id(queue_id, project_id)
        if not queue_obj:
            return jsonify({"error": "Queue not found"}), 404

        # Get current queue data
        current_queue = queue_obj.queue_data.copy()

        # Sort indices in descending order to avoid index shifting issues
        indices_to_delete = sorted(set(indices_to_delete), reverse=True)

        # Remove entries at specified indices (0-based)
        deleted_count = 0
        for idx in indices_to_delete:
            if 0 <= idx < len(current_queue):
                del current_queue[idx]
                deleted_count += 1

        # Update queue in database
        queue_obj.queue_data = current_queue
        queue_obj.length = len(current_queue)
        db.session.commit()

        return jsonify(
            {
                "success": True,
                "message": f"Successfully deleted {deleted_count} entries from queue",
                "deleted_count": deleted_count,
                "remaining_count": len(current_queue),
            }
        ), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@app.route("/<int:project_id>/create-queue", methods=["GET", "POST"])
def create_queue(project_id: int) -> ...:
    """Create a queue manually from a list of entry IDs"""
    # Check project_id
    res = update_session_project(project_id)
    if res is not None:
        return res

    # Get datasets
    datasets = list(get_datasets(project_id))

    if request.method == "GET":
        return render_template("create-queue.html", project_id=project_id, datasets=datasets)

    # Handle POST request
    entry_ids_text = request.form.get("entry_ids", "").strip()
    highlight_terms = request.form.get("highlight_terms", "").strip()
    queue_name = request.form.get("queue_name", "").strip() or None  # Optional custom name

    if not entry_ids_text:
        flash(_("Please enter at least one entry ID"), "error")
        return render_template("create-queue.html", project_id=project_id, datasets=datasets)

    # Parse entry IDs
    lines = [line.strip() for line in entry_ids_text.split("\n") if line.strip()]
    queue_entries = []
    errors = []

    # Create dataset lookup
    dataset_by_name = {dataset.name: dataset for dataset in datasets}

    for line_num, line in enumerate(lines, 1):
        if len(datasets) == 1:
            # Single dataset: just entry ID
            try:
                entry_id = line.strip()
                if entry_id:
                    queue_entries.append((datasets[0].id, entry_id))
            except Exception:
                errors.append(
                    _("Line {line_num}: Invalid entry ID '{line}'").format(
                        line_num=line_num, line=line
                    )
                )
        else:
            # Multiple datasets: entry_id,dataset_name (with CSV parsing for quotes)
            try:
                # Use pandas to parse the line as CSV (handles quotes properly)
                csv_io = StringIO(line)
                df = pd.read_csv(csv_io, header=None, quoting=1)  # quoting=1 = QUOTE_ALL

                if df.shape[1] != 2:
                    errors.append(
                        _(
                            "Line {line_num}: Expected format 'entry_id,dataset_name', got '{line}'"
                        ).format(line_num=line_num, line=line)
                    )
                    continue

                entry_id = str(df.iloc[0, 0]).strip()
                dataset_name = str(df.iloc[0, 1]).strip()

                if dataset_name not in dataset_by_name:
                    errors.append(
                        _("Line {line_num}: Unknown dataset '{dataset_name}'").format(
                            line_num=line_num, dataset_name=dataset_name
                        )
                    )
                    continue

                if entry_id:
                    queue_entries.append((dataset_by_name[dataset_name].id, entry_id))

            except Exception:
                errors.append(
                    _(
                        "Line {line_num}: Invalid format '{line}'. Use 'entry_id,dataset_name'"
                        " or 'entry_id,\"dataset name with spaces\"'"
                    ).format(line_num=line_num, line=line)
                )
                continue

    if errors:
        for error in errors:
            flash(error, "error")
        return render_template("create-queue.html", project_id=project_id, datasets=datasets)

    if not queue_entries:
        flash(_("No valid entries found"), "error")
        return render_template("create-queue.html", project_id=project_id, datasets=datasets)

    # Parse highlight terms
    highlights = None
    if highlight_terms:
        highlights = [term.strip() for term in highlight_terms.split(",") if term.strip()]

    # Store the queue
    try:
        store_queue(
            queue_entries,
            project_id,
            highlight=highlights,
            name=queue_name,  # Use custom name if provided
            queue_type="manual",  # Auto-generate if no name provided
        )
        flash(
            _("Queue created successfully with {count} entries").format(count=len(queue_entries)),
            "success",
        )
        return redirect(
            url_for("data_navigation", project_id=project_id) + "?section=queue-management"
        )
    except Exception as e:
        flash(_("Failed to create queue: {error}").format(error=str(e)), "error")
        return render_template("create-queue.html", project_id=project_id, datasets=datasets)


# endregion


# region General projects management routes
# --------------------------------
@app.route("/projects")
def projects() -> ...:
    """Project management dashboard"""
    projects = get_projects()
    stats = {}
    for project in projects:
        stats[project.id] = {
            "total_labels": len(project.labels),
            "labeled_entries": 0,
        }
    return render_template("projects.html", projects=projects, stats=stats)


@app.route("/projects/new", methods=["POST"])
def create_project() -> ...:
    """Create new project"""
    project_name = request.form.get("name")
    if project_name:
        project = new_project(project_name, session["user_id"])

        # Backup any existing queue folder for this project ID
        backup_old_queue_folder(project.id)

        flash(_("Project created successfully"), "success")
        # Redirect to upload data page with new project selected
        return redirect(url_for("upload_data", project_id=project.id))
    return redirect(url_for("projects"))


@app.route("/projects/<int:project_id>/delete", methods=["GET"])
def delete_project(project_id) -> ...:
    """Delete a project"""
    project = get_project(project_id)
    if project:
        del_controled(project, session["user_id"])
        flash(_("Project deleted successfully"), "success")
    return redirect(url_for("projects"))


# endregion
