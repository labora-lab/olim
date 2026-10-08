import copy
import json
from pathlib import Path

from flask import (
    abort,
    flash,
    get_flashed_messages,
    make_response,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_babel import _, get_locale

from .. import app
from ..auth import role_has_permission as has_permission
from ..database import (
    assign_learning_task,
    delete_learning_task,
    get_datasets,
    get_labels,
    get_learning_task,
    get_learning_tasks,
    get_users,
    new_learning_task,
    update_learning_task,
)
from ..project import update_session_project
from .base import BaseState
from .entry_selector import resolve_entry_ids

# Registry of state classes by name
STATE_REGISTRY: dict[str, type[BaseState]] = {}

# Path to configurations folder
CONFIGURATIONS_PATH = Path(__file__).parent / "configurations"


def register_state(cls: type[BaseState]) -> type[BaseState]:
    """Decorator to register a state class."""
    STATE_REGISTRY[cls.__name__] = cls
    return cls


def get_state_class(state_name: str) -> type[BaseState] | None:
    """Get a state class by name."""
    return STATE_REGISTRY.get(state_name)


def can_go_back_steps() -> bool:
    """Annotators only move forward: going back (e.g. to a queue's setup) would let
    them change what the task's author set up for them."""
    return session.get("role") != "annotator"


app.jinja_env.globals.update(can_go_back_steps=can_go_back_steps)


def get_current_step(initial_setup: dict, position: int) -> dict | None:
    """Get the current step from the sequence."""
    sequence = initial_setup.get("sequence", [])
    if 0 <= position < len(sequence):
        return sequence[position]
    return None


def clamp_position(position: int, sequence_length: int) -> int:
    """Clamp position to valid range."""
    return max(0, min(position, sequence_length - 1))


# region Configuration Management
# -------------------------------


def localised(config: dict, key: str, default: str = "") -> str:
    """Return a preset field in the viewer's language.

    Preset copy lives in JSON, which babel does not extract, so a preset carries its
    own translations rather than going through the message catalogue:

        {"name": "Labeling Queue", "name_pt_BR": "Fila de Rotulagem"}

    Falls back from the full locale (name_pt_BR) to the bare language (name_pt) to
    the untagged key, so a preset that only supplies English still works — as do
    presets uploaded by admins, which need no changes at all.
    """
    try:
        locale = str(get_locale() or "")
    except Exception:  # outside a request context there is no locale to resolve
        locale = ""

    candidates = []
    if locale:
        candidates.append(f"{key}_{locale}")
        language = locale.split("_")[0]
        if language != locale:
            candidates.append(f"{key}_{language}")
    candidates.append(key)

    for candidate in candidates:
        value = config.get(candidate)
        if value:
            return str(value)
    return default


def get_available_configurations() -> list[dict]:
    """Get list of available task configurations from the configurations folder."""
    configurations = []
    if CONFIGURATIONS_PATH.exists():
        for file_path in CONFIGURATIONS_PATH.glob("*.json"):
            try:
                with open(file_path, encoding="utf-8") as f:
                    config = json.load(f)
                    configurations.append(
                        {
                            "filename": file_path.stem,
                            "name": localised(config, "name", file_path.stem),
                            "description": localised(config, "description"),
                            "steps": len(config.get("sequence", [])),
                            "order": config.get("order", 999),
                            "icon": config.get("icon", "diagram-3"),
                        }
                    )
            except (OSError, json.JSONDecodeError):
                continue
    configurations.sort(key=lambda c: (c["order"], c["name"].lower()))
    return configurations


def build_initial_setup(config: dict) -> dict:
    """Fields of a preset that a task carries with it.

    `sequence` is what drives the task; the rest is provenance and presentation.
    `show_progress` in particular is read back by learning_task_view, so dropping it
    here is why every preset that asks for a progress bar never got one.
    """
    return {
        "sequence": config.get("sequence", []),
        "show_progress": config.get("show_progress", False),
        # Untranslated on purpose: this is a record of which preset built the task,
        # and it should not read differently depending on who opens it.
        "preset_name": config.get("name", ""),
        "preset_description": config.get("description", ""),
    }


def _label_ids(value: object, field: str) -> list[int]:
    if not isinstance(value, list) or not all(
        isinstance(v, int) or (isinstance(v, str) and v.isdigit()) for v in value
    ):
        raise ValueError(_("'{field}' must be a list of label IDs").format(field=field))
    return [int(v) for v in value]


def build_initial_data(config: dict, project_id: int) -> dict:
    """Task data preset by a configuration's optional "data" block.

    Lets a task start straight at LabelEntry with a fixed queue:
        "data": {
            "entries": ["PAT-1", "3:PAT-2"],   # entry IDs, dataset_id:entry_id if ambiguous
            "labels": [12, 15],                # label IDs of the project (default: all)
            "required_labels": [12],           # subset of labels (default: none)
            "completion_mode": "all",          # "any" (default) or "all"
            "enforce_required": true           # block moving on until complete
        }

    Raises:
        ValueError: with a user-facing message when the block is invalid
    """
    raw = config.get("data")
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError(_("'data' must be an object"))
    unknown = set(raw) - {
        "entries",
        "labels",
        "required_labels",
        "completion_mode",
        "enforce_required",
    }
    if unknown:
        raise ValueError(
            _("Unknown fields in 'data': {fields}").format(fields=", ".join(sorted(unknown)))
        )

    entries = raw.get("entries")
    if not isinstance(entries, list) or not entries:
        raise ValueError(_("'entries' must be a non-empty list of entry IDs"))
    entry_ids = [str(e).strip() for e in entries]
    if "" in entry_ids:
        raise ValueError(_("'entries' contains an empty ID"))
    repeated = sorted({e for e in entry_ids if entry_ids.count(e) > 1})
    if repeated:
        raise ValueError(
            _("'entries' repeats these IDs: {ids}").format(ids=", ".join(repeated[:20]))
        )
    items, problems = resolve_entry_ids(entry_ids, list(get_datasets(project_id)))
    if problems:
        raise ValueError(" ".join(problems))

    project_labels = {label.id: label for label in get_labels(project_id)}
    label_ids = _label_ids(raw["labels"], "labels") if "labels" in raw else list(project_labels)
    missing = [str(i) for i in label_ids if i not in project_labels]
    if missing:
        raise ValueError(
            _("These labels don't exist in this project: {ids}").format(ids=", ".join(missing))
        )
    if not label_ids:
        raise ValueError(_("The task needs at least one label"))
    required_ids = _label_ids(raw.get("required_labels", []), "required_labels")
    outside = [str(i) for i in required_ids if i not in label_ids]
    if outside:
        raise ValueError(
            _("Required labels must also be in 'labels': {ids}").format(ids=", ".join(outside))
        )

    completion_mode = raw.get("completion_mode", "any")
    if completion_mode not in ("any", "all"):
        raise ValueError(_('\'completion_mode\' must be "any" or "all"'))

    def label_refs(ids: list[int]) -> list[dict]:
        return [{"id": i, "name": project_labels[i].name} for i in ids]

    return {
        "queue_ids": [entry_id for entry_id, _dataset_id in items],
        "queue_dataset_ids": [dataset_id for _entry_id, dataset_id in items],
        "queue_labels": label_refs(label_ids),
        "queue_required_labels": label_refs(required_ids),
        "queue_completion_mode": completion_mode,
        "queue_enforce_required": bool(raw.get("enforce_required", False)),
        "queue_position": 0,
    }


def load_configuration(filename: str) -> dict | None:
    """Load a configuration by filename."""
    file_path = CONFIGURATIONS_PATH / f"{filename}.json"
    if file_path.exists():
        try:
            with open(file_path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return None
    return None


def save_configuration(filename: str, config: dict) -> bool:
    """Save a configuration to the configurations folder."""
    CONFIGURATIONS_PATH.mkdir(parents=True, exist_ok=True)
    file_path = CONFIGURATIONS_PATH / f"{filename}.json"
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4, ensure_ascii=False)
        return True
    except OSError:
        return False


def validate_configuration(config: dict) -> tuple[bool, str]:
    """Validate a configuration structure."""
    if not isinstance(config, dict):
        return False, _("Configuration must be a JSON object")

    if "sequence" not in config:
        return False, _("Configuration must have a 'sequence' field")

    sequence = config["sequence"]
    if not isinstance(sequence, list) or len(sequence) == 0:
        return False, _("Sequence must be a non-empty list")

    for i, step in enumerate(sequence):
        if not isinstance(step, dict):
            return False, _("Step {i} must be an object").format(i=i + 1)
        if "state" not in step:
            return False, _("Step {i} must have a 'state' field").format(i=i + 1)
        if step["state"] not in STATE_REGISTRY:
            return False, _("Step {i} has unknown state: {state}").format(
                i=i + 1, state=step["state"]
            )

    return True, ""


# endregion


# region Learning Tasks Management
# --------------------------------


@app.route("/<int:project_id>/tasks", methods=["GET"])
def learning_tasks_list(project_id: int) -> ...:
    """Learning tasks management dashboard."""
    res = update_session_project(project_id)
    if res is not None:
        return res

    user_id: int = session["user_id"]
    is_admin = has_permission("admin")

    # Annotators don't see the project split: their tasks from every project
    is_annotator = session.get("role") == "annotator"
    my_tasks = get_learning_tasks(None if is_annotator else project_id, assigned_to=user_id)
    all_tasks = get_learning_tasks(project_id) if is_admin else []
    users = get_users() if is_admin else []
    configurations = get_available_configurations()

    return render_template(
        "learning-tasks.html",
        my_tasks=my_tasks,
        all_tasks=all_tasks,
        users=users,
        configurations=configurations,
        available_states=list(STATE_REGISTRY.keys()),
        is_admin=is_admin,
    )


@app.route("/<int:project_id>/tasks/new", methods=["POST"])
def create_learning_task(project_id: int) -> ...:
    """Create a new learning task."""
    res = update_session_project(project_id)
    if res is not None:
        return res

    name = request.form.get("name", "").strip()
    if not name:
        flash(_("Task name is required"), "error")
        return redirect(url_for("learning_tasks_list", project_id=project_id))

    source = request.form.get("source", "preset")
    initial_setup = None
    initial_config: dict = {}

    if source == "preset":
        # Load from preconfigured file
        config_name = request.form.get("configuration", "")
        if config_name:
            config = load_configuration(config_name)
            if config:
                # Shipped presets were previously trusted unvalidated, so a bad state
                # name surfaced as a 500 partway through the task instead of here.
                valid, error_msg = validate_configuration(config)
                if not valid:
                    flash(error_msg, "error")
                    return redirect(url_for("learning_tasks_list", project_id=project_id))
                initial_setup = build_initial_setup(config)
                initial_config = config
            else:
                flash(_("Configuration not found"), "error")
                return redirect(url_for("learning_tasks_list", project_id=project_id))
        else:
            flash(_("Please select a configuration"), "error")
            return redirect(url_for("learning_tasks_list", project_id=project_id))

    elif source == "upload":
        # Load from uploaded JSON file
        uploaded_file = request.files.get("config_file")
        if uploaded_file and uploaded_file.filename:
            try:
                config = json.load(uploaded_file.stream)
                valid, error_msg = validate_configuration(config)
                if not valid:
                    flash(error_msg, "error")
                    return redirect(url_for("learning_tasks_list", project_id=project_id))
                initial_setup = build_initial_setup(config)
                initial_config = config
            except json.JSONDecodeError:
                flash(_("Invalid JSON file"), "error")
                return redirect(url_for("learning_tasks_list", project_id=project_id))
        else:
            flash(_("Please upload a configuration file"), "error")
            return redirect(url_for("learning_tasks_list", project_id=project_id))

    if not initial_setup or not initial_setup.get("sequence"):
        flash(_("Invalid configuration"), "error")
        return redirect(url_for("learning_tasks_list", project_id=project_id))

    try:
        initial_data = build_initial_data(initial_config, project_id)
    except ValueError as e:
        flash(str(e), "error")
        return redirect(url_for("learning_tasks_list", project_id=project_id))

    # Get initial state from first step
    initial_state = initial_setup["sequence"][0]["state"]

    assigned_to_raw = request.form.get("assigned_to", "").strip()
    assigned_to: int | None = int(assigned_to_raw) if assigned_to_raw.isdigit() else None

    task = new_learning_task(
        name=name,
        state=initial_state,
        initial_setup=initial_setup,
        user_id=session["user_id"],
        project_id=project_id,
        data=initial_data,
        assigned_to=assigned_to,
    )

    flash(_("Learning task created successfully"), "success")
    return redirect(url_for("learning_task_view", project_id=project_id, task_id=task.id))


@app.route("/<int:project_id>/tasks/<int:task_id>/delete", methods=["GET", "POST"])
def delete_learning_task_route(project_id: int, task_id: int) -> ...:
    """Delete a learning task."""
    res = update_session_project(project_id)
    if res is not None:
        return res

    if delete_learning_task(task_id, session["user_id"]):
        flash(_("Learning task deleted successfully"), "success")
    else:
        flash(_("Learning task not found"), "error")

    return redirect(url_for("learning_tasks_list", project_id=project_id))


@app.route("/<int:project_id>/tasks/<int:task_id>/assign", methods=["POST"])
def assign_learning_task_route(project_id: int, task_id: int) -> ...:
    """Assign a learning task to a user."""
    res = update_session_project(project_id)
    if res is not None:
        return res

    if not has_permission("admin"):
        abort(403)

    assigned_to_raw = request.form.get("assigned_to", "").strip()
    assigned_to: int | None = int(assigned_to_raw) if assigned_to_raw.isdigit() else None

    task = assign_learning_task(task_id, assigned_to)
    if task:
        flash(_("Task assigned successfully"), "success")
    else:
        flash(_("Task not found"), "error")

    return redirect(url_for("learning_tasks_list", project_id=project_id))


@app.route("/<int:project_id>/tasks/<int:task_id>/reset", methods=["POST"])
def reset_learning_task(project_id: int, task_id: int) -> ...:
    """Reset a learning task to its initial state."""
    res = update_session_project(project_id)
    if res is not None:
        return res

    task = get_learning_task(task_id)
    if task:
        # Get initial state from sequence
        initial_setup = task.initial_setup or {}
        sequence = initial_setup.get("sequence", [])
        initial_state = sequence[0]["state"] if sequence else "StaticContent"

        update_learning_task(
            task_id,
            state=initial_state,
            position=0,
        )
        flash(_("Learning task reset successfully"), "success")
    else:
        flash(_("Learning task not found"), "error")

    return redirect(url_for("learning_tasks_list", project_id=project_id))


# endregion


@app.route("/<int:project_id>/task/<int:task_id>", methods=["GET", "POST"])
def learning_task_view(project_id: int, task_id: int) -> ...:
    # Check project_id
    res = update_session_project(project_id)
    if res is not None:
        return res

    # Load task from database
    task = get_learning_task(task_id)
    if task is None:
        abort(404, "Learning task not found")

    # Verify task belongs to this project
    if task.project_id != project_id:
        abort(404, "Learning task not found in this project")

    # Annotators can only access tasks assigned to them
    if session.get("role") == "annotator" and task.assigned_to != session.get("user_id"):
        abort(403)

    # Get sequence from initial_setup
    initial_setup = task.initial_setup or {}
    sequence = initial_setup.get("sequence", [])
    if not sequence:
        abort(500, "Task has no sequence defined")

    # Get task data (make a copy to ensure SQLAlchemy detects changes)
    data = dict(task.data) if task.data else {}
    position = task.position

    # Get current step configuration
    current_step = get_current_step(initial_setup, position)
    if current_step is None:
        abort(500, f"Invalid position: {position}")

    # Get the state class for current step
    state_name = current_step.get("state")
    state_class = get_state_class(state_name)
    if state_class is None:
        abort(500, f"Unknown state: {state_name}")

    # Get step-specific parameters and inject context
    params = dict(current_step.get("params", {}))
    is_last_step = position == len(sequence) - 1
    params["is_last_step"] = is_last_step

    # Inject project context (accessible to all states)
    params["_task_id"] = task_id
    params["_project_id"] = project_id
    params["_datasets"] = list(get_datasets(project_id))

    # Get user_id from session (same way as labels.py and other modules)
    is_htmx = request.headers.get("HX-Request") == "true"
    try:
        params["_user_id"] = session["user_id"]
    except KeyError:
        params["_user_id"] = None

    # Instantiate state with data and params
    state = state_class(data, params)

    # Handle POST (state transition)
    if request.method == "POST":
        action = request.form.get("action", "")
        # Pass form directly to preserve multiple values (e.g., checkboxes)
        payload = request.form

        # Handle finish action
        if action == "finish":
            # Persist before leaving: the last interaction's data (final metrics,
            # the recorded stop reason) is otherwise dropped and the task comes back
            # in the list looking resumable.
            update_learning_task(
                task_id,
                state=state_name,
                position=len(sequence) - 1,
                data=data,
            )
            flash(_("Task completed!"), "success")
            if is_htmx:
                resp = make_response("")
                resp.headers["HX-Redirect"] = url_for("learning_tasks_list", project_id=project_id)
                return resp
            return redirect(url_for("learning_tasks_list", project_id=project_id))

        # Process interaction and get relative position change
        data_before = copy.deepcopy(data)
        try:
            delta = state.handle(action, payload)
        except Exception as e:
            app.logger.error(
                f"Error in task {task_id} state {state_name} handle: {e}", exc_info=True
            )
            err_msg = _("An error occurred while processing your request. Please try again.")
            if is_htmx:
                try:
                    body = state.render()
                except Exception:
                    body = ""
                resp = make_response(body, 200)
                if not body:
                    resp.headers["HX-Reswap"] = "none"
                resp.headers["HX-Trigger"] = json.dumps(
                    {"showFlash": [{"message": err_msg, "category": "error"}]}
                )
                return resp
            flash(err_msg, "error")
            return redirect(request.url)

        if delta < 0 and not can_go_back_steps():
            # Undo whatever the state cleared on its way back (a queue, LLM results)
            data.clear()
            data.update(data_before)
            delta = 0
            flash(_("You can't go back to a previous step of this task."), "error")

        # Calculate new position
        raw_new_position = position + delta

        # Check if task is complete (moved past the last step)
        if raw_new_position >= len(sequence):
            update_learning_task(
                task_id,
                state=state_name,
                position=len(sequence) - 1,
                data=data,
            )
            flash(_("Task completed!"), "success")
            if is_htmx:
                resp = make_response("")
                resp.headers["HX-Redirect"] = url_for("learning_tasks_list", project_id=project_id)
                return resp
            return redirect(url_for("learning_tasks_list", project_id=project_id))

        # Clamp position to valid range
        new_position = clamp_position(raw_new_position, len(sequence))

        # Get new step info for state name
        new_step = get_current_step(initial_setup, new_position)
        new_state_name = new_step["state"] if new_step else state_name

        # Persist state change to database
        update_learning_task(
            task_id,
            state=new_state_name,
            position=new_position,
            data=data,
        )

        # Reload state if position changed
        if new_position != position:
            position = new_position
            new_state_class = get_state_class(new_state_name)
            if new_state_class:
                new_params = dict(new_step.get("params", {})) if new_step else {}
                # Re-inject context
                new_params["is_last_step"] = new_position == len(sequence) - 1
                new_params["_project_id"] = project_id
                new_params["_datasets"] = list(get_datasets(project_id))
                state = new_state_class(data, new_params)

    # Check if progress bar should be shown (default: hidden)
    show_progress = initial_setup.get("show_progress", False)

    # HTMX partial response: return only the state content + OOB progress bar
    if is_htmx:
        try:
            body = state.render()
        except Exception as e:
            app.logger.error(
                f"Error rendering task {task_id} state {state_name}: {e}", exc_info=True
            )
            err_msg = _("An error occurred while loading the content. Please refresh the page.")
            resp = make_response("", 200)
            resp.headers["HX-Reswap"] = "none"
            resp.headers["HX-Trigger"] = json.dumps(
                {"showFlash": [{"message": err_msg, "category": "error"}]}
            )
            return resp

        # Append OOB progress bar update
        if show_progress:
            body += render_template(
                "learning_tasks/_progress_bar.html",
                task=task,
                position=position,
                total_steps=len(sequence),
                show_progress=True,
                oob=True,
            )

        resp = make_response(body)

        # Drain flash messages and send as HX-Trigger
        flash_messages = []
        for cat in ("success", "warning", "error", "info"):
            for msg in get_flashed_messages(category_filter=[cat]):
                flash_messages.append({"message": msg, "category": cat})
        if flash_messages:
            resp.headers["HX-Trigger"] = json.dumps({"showFlash": flash_messages})

        return resp

    # Get optional scripts from state
    state_scripts = ""
    if hasattr(state, "render_scripts"):
        state_scripts = state.render_scripts()

    return render_template(
        "task.html",
        task=task,
        state=state,
        content=state.render(),
        position=position,
        total_steps=len(sequence),
        show_progress=show_progress,
        state_scripts=state_scripts,
        oob=False,
    )


# Import states to register them
from . import states  # noqa: E402, F401
