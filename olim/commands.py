import json

from flask import request, session
from flask_babel import _

from . import app, entry_types
from .database import add_entry_label, get_label
from .functions import manage_label_in_session


def add_label(**args) -> dict[str, str]:
    entry_id = args.get("entry_id")
    label_id = args.get("label_id")
    value = args.get("value", "")
    # TODO: handle the typecheck correctly
    label_obj = get_label(label_id)  # type: ignore [label_id as str | Unknown is safe]
    if label_obj is None:
        raise Exception("Label not found")

    label = label_obj.name

    try:
        add_entry_label(label_id, entry_id, session["user_id"], value)
    except Exception as e:
        print(e)
        return {
            "type": "error",
            "text": _("Failed writing to database"),
        }

    if value == "":
        msg = _("Removed the label {label} for the entry {entry_id}").format(
            label=label, entry_id=entry_id
        )
    else:
        msg = f"{label}: {value} for the entry {entry_id}"

    if entry_id is None:
        return {
            "type": "error",
            "text": _("No entry ID passed"),
        }
    elif label is None:
        return {
            "type": "error",
            "text": _("No label passed"),
        }
    else:
        return {
            "type": "OK",
            "text": msg,
        }


def manage_label(**args) -> dict[str, str] | None:
    str_label = args.get("label", None)
    label_id = args.get("label_id", None)
    mode = args.get("mode", "add")

    if str_label is None or label_id is None:
        return {
            "type": "error",
            "text": _("Missing data: label"),
        }

    try:
        manage_label_in_session(label_id, mode)
    except Exception as e:
        print(e)
        return {
            "type": "error",
            "text": _("Error hidding label."),
        }

    if mode == "add":
        return {
            "type": "OK",
            "text": _("Label {label} hidden").format(label=str_label),
        }

    elif mode == "remove":
        return {
            "type": "OK",
            "text": _("Label {label} unhidden").format(label=str_label),
        }


def update_session(**args) -> dict[str, str]:
    parameter = args.get("parameter", None)
    data = args.get("data", None)

    if parameter is None:
        return {
            "type": "error",
            "text": _("Missing parameter"),
        }
    if data is None:
        return {
            "type": "error",
            "text": _("Missing data"),
        }

    session[parameter] = json.loads(data)
    return {
        "type": "silentOK",
    }


COMMANDS = {
    "add-label": add_label,
    "manage-label": manage_label,
    "update-session": update_session,
}

for mod in dir(entry_types):
    module = getattr(entry_types, mod)
    if hasattr(module, "COMMANDS"):
        COMMANDS.update(module.COMMANDS)

ERROR_NO_CMD = {"type": "error", "text": _("No command passed")}

ERROR_NOT_FOUND = {"type": "error", "text": _("Command {command} not found")}


@app.route("/commands")
def commands() -> str:
    if "cmd" in request.args:
        cmd = request.args["cmd"]
        if cmd in COMMANDS:
            f = COMMANDS[cmd]
            response = f(**request.args)
        else:
            response = ERROR_NOT_FOUND.copy()
            response["text"] = response["text"].format(command=cmd)
    else:
        cmd = None
        response = ERROR_NO_CMD
    response["cmd"] = cmd  # type: ignore [response is a generic dict]
    response["request"] = request.args  # type: ignore [response is a generic dict]
    if "callback" not in response and "callback" in request.args:
        response["callback"] = request.args["callback"]
    if "fail_callback" not in response and "fail_callback" in request.args:
        response["fail_callback"] = request.args["fail_callback"]

    # TODO: json.dumps is the correct serializer for API?
    return json.dumps(response)
