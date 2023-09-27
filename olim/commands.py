from . import app
from . import entry_types
from .functions import manage_label_in_session
from .database import add_entry_label, get_label
from flask import request, session
import json
from flask_babel import _

def add_label(**args):
    entry_id = args.get("entry_id", None)
    label_id = args.get("label_id", None)
    value = args.get("value", "")
    label = get_label(label_id).name

    try:
        add_entry_label(label_id, entry_id, session["user_id"], value)
    except:
        return {
            "type": "error",
            "text": _("Failed writing to database"),
        }

    if value == "":
        msg = _(f"Removed the label {label} for the entry {entry_id}")
    else:
        msg = f"{label}: {value} for the entry {entry_id}"

    if entry_id == None:
        return {
            "type": "error",
            "text": _("No entry ID passed"),
        }
    elif label == None:
        return {
            "type": "error",
            "text": _("No label passed"),
        }
    else:
        return {
            "type": "OK",
            "text": msg,
        }


def manage_label(**args):
    str_label = args.get("label", None)
    label_id = args.get("label_id", None)
    mode = args.get("mode", "add")

    if str_label == None or label_id == None:
        return {
            "type": "error",
            "text": _("Missing data: label"),
        }

    try:
        manage_label_in_session(int(label_id), mode)
    except:
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


def update_session(**args):
    parameter = args.get("parameter", None)
    data = args.get("data", None)

    if parameter == None:
        return {
            "type": "error",
            "text": _("Missing parameter"),
        }
    if data == None:
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
def commands():
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
    response["cmd"] = cmd
    response["request"] = request.args
    if "callback" not in response and "callback" in request.args:
        response["callback"] = request.args["callback"]
    if "fail_callback" not in response and "fail_callback" in request.args:
        response["fail_callback"] = request.args["fail_callback"]
    return json.dumps(response)
