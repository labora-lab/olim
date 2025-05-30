import json

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
from .utils.entry import get_all_hidden
from .utils.queues import get_all_queues, get_queue, store_queue


@app.route("/")
def redirect_to_project() -> ...:
    project_id = session.get("project_id")
    project_id = project_id or get_projects()[0].id
    session["project_id"] = project_id
    return redirect(f"/{project_id}")


def update_session_project(project_id: int) -> ...:
    if session["project_id"] != project_id:
        project = get_project(project_id)
        if project is None:
            flash(
                _(f"Invalid project ID: {project_id}!"),
                category="warning",
            )
            return redirect("/")
        else:
            session["project_id"] = project.id
            session["project_name"] = project.name
            app.jinja_env.globals.update(
                project_id=project.id,
                project_name=project.name,
            )
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
            dataset_id, entry_id = queue[queue_pos - 1]
            update_queue_pos(queue_id, queue_pos)
            data.update(
                {
                    "queue_id": queue_id,
                    "queue_len": len(queue),
                    "queue_pos": queue_pos,
                }
            )
        except Exception as e:
            print(e)
            flash(
                _("Queue {queue_id} not found").format(queue_id=queue_id),
                category="error",
            )
            queue_id = None

    # Check if entry exists ans try to render it
    data = render_entry(entry_id, dataset_id, data)

    data.update(
        {
            "show_hidden": show_hidden,
            "labels": get_labels(),
            "highlight": get_highlights(),
            "hidden_labels": hidden_labels,
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
        return render_template(
            "search.html",
            number=number,
            include="[]",
            exclude="[]",
            highlight="[]",
            n_results=-1,
        )

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
            highlight,
            **extra_data,
        )
    else:
        queue_id = None

    return render_template(
        "search.html",
        results=data,
        n_results=len(data),
        include=include,
        exclude=exclude,
        number=number,
        highlight=highlight,
        queue_id=queue_id,
    )


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
        queue_id = store_queue(queue, project_id, **extra_data)
        print(url_for("queue", project_id=project_id, queue_id=queue_id))
        return redirect(url_for("queue", project_id=project_id, queue_id=queue_id))
    # If not render blank page
    else:
        return render_template(
            "queue.html", number=get_def_nentries(), queues=get_all_queues(project_id)
        )


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
        new_project(project_name, session["user_id"])
        flash(_("Project created successfully"), "success")
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
