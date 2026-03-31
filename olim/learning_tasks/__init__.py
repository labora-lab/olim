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
from flask_babel import _

from .. import app
from ..auth import role_has_permission as has_permission
from ..database import (
    assign_learning_task,
    delete_learning_task,
    get_datasets,
    get_learning_task,
    get_learning_tasks,
    get_users,
    new_learning_task,
    update_learning_task,
)
from ..project import update_session_project
from .base import BaseState

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
                            "name": config.get("name", file_path.stem),
                            "description": config.get("description", ""),
                            "steps": len(config.get("sequence", [])),
                            "order": config.get("order", 999),
                        }
                    )
            except (OSError, json.JSONDecodeError):
                continue
    configurations.sort(key=lambda c: (c["order"], c["name"].lower()))
    return configurations


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

    my_tasks = get_learning_tasks(project_id, assigned_to=user_id)
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

    if source == "preset":
        # Load from preconfigured file
        config_name = request.form.get("configuration", "")
        if config_name:
            config = load_configuration(config_name)
            if config:
                initial_setup = {"sequence": config.get("sequence", [])}
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
                initial_setup = {"sequence": config.get("sequence", [])}
            except json.JSONDecodeError:
                flash(_("Invalid JSON file"), "error")
                return redirect(url_for("learning_tasks_list", project_id=project_id))
        else:
            flash(_("Please upload a configuration file"), "error")
            return redirect(url_for("learning_tasks_list", project_id=project_id))

    if not initial_setup or not initial_setup.get("sequence"):
        flash(_("Invalid configuration"), "error")
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
        data={},
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
            flash(_("Task completed!"), "success")
            if is_htmx:
                resp = make_response("")
                resp.headers["HX-Redirect"] = url_for("learning_tasks_list", project_id=project_id)
                return resp
            return redirect(url_for("learning_tasks_list", project_id=project_id))

        # Process interaction and get relative position change
        delta = state.handle(action, payload)

        # Calculate new position
        raw_new_position = position + delta

        # Check if task is complete (moved past the last step)
        if raw_new_position >= len(sequence):
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
        body = state.render()

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
