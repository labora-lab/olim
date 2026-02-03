import json
from pathlib import Path

from flask import abort, flash, redirect, render_template, request, session, url_for
from flask_babel import _

from .. import app
from ..database import (
    delete_learning_task,
    get_learning_task,
    get_learning_tasks,
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
                    configurations.append({
                        "filename": file_path.stem,
                        "name": config.get("name", file_path.stem),
                        "description": config.get("description", ""),
                        "steps": len(config.get("sequence", [])),
                    })
            except (json.JSONDecodeError, IOError):
                continue
    return configurations


def load_configuration(filename: str) -> dict | None:
    """Load a configuration by filename."""
    file_path = CONFIGURATIONS_PATH / f"{filename}.json"
    if file_path.exists():
        try:
            with open(file_path, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
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
    except IOError:
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

    tasks = get_learning_tasks()
    configurations = get_available_configurations()
    return render_template(
        "learning-tasks.html",
        tasks=tasks,
        configurations=configurations,
        available_states=list(STATE_REGISTRY.keys()),
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

    task = new_learning_task(
        name=name,
        state=initial_state,
        initial_setup=initial_setup,
        user_id=session["user_id"],
        data={"position": 0},
    )

    flash(_("Learning task created successfully"), "success")
    return redirect(url_for("learning_task_view", project_id=project_id, task_id=task.id))


@app.route("/<int:project_id>/tasks/configurations/upload", methods=["POST"])
def upload_configuration(project_id: int) -> ...:
    """Upload a new configuration to the configurations folder."""
    res = update_session_project(project_id)
    if res is not None:
        return res

    uploaded_file = request.files.get("config_file")
    if not uploaded_file or not uploaded_file.filename:
        flash(_("Please upload a configuration file"), "error")
        return redirect(url_for("learning_tasks_list", project_id=project_id))

    try:
        config = json.load(uploaded_file.stream)
        valid, error_msg = validate_configuration(config)
        if not valid:
            flash(error_msg, "error")
            return redirect(url_for("learning_tasks_list", project_id=project_id))

        # Use provided name or filename
        config_name = request.form.get("config_name", "").strip()
        if not config_name:
            config_name = Path(uploaded_file.filename).stem

        # Sanitize filename
        config_name = "".join(c for c in config_name if c.isalnum() or c in "-_")

        if save_configuration(config_name, config):
            flash(_("Configuration uploaded successfully"), "success")
        else:
            flash(_("Failed to save configuration"), "error")

    except json.JSONDecodeError:
        flash(_("Invalid JSON file"), "error")

    return redirect(url_for("learning_tasks_list", project_id=project_id))


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

    # Get step-specific parameters and inject is_last_step
    params = dict(current_step.get("params", {}))
    is_last_step = position == len(sequence) - 1
    params["is_last_step"] = is_last_step

    # Instantiate state with data and params
    state = state_class(data, params)

    # Handle POST (state transition)
    if request.method == "POST":
        action = request.form.get("action", "")
        payload = request.form.to_dict()
        payload.pop("action", None)

        # Handle finish action
        if action == "finish":
            flash(_("Task completed!"), "success")
            return redirect(url_for("learning_tasks_list", project_id=project_id))

        # Process interaction and get relative position change
        delta = state.handle(action, payload)

        # Calculate new position
        raw_new_position = position + delta

        # Check if task is complete (moved past the last step)
        if raw_new_position >= len(sequence):
            flash(_("Task completed!"), "success")
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
                new_params = new_step.get("params", {}) if new_step else {}
                state = new_state_class(data, new_params)

    # Check if progress bar should be shown
    show_progress = initial_setup.get("show_progress", True)

    return render_template(
        "task.html",
        task=task,
        state=state,
        content=state.render(),
        position=position,
        total_steps=len(sequence),
        show_progress=show_progress,
    )


# Import states to register them
from . import states  # noqa: E402, F401
