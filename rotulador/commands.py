from . import app
from flask import request
import json
import time


def hide_one(**args):
    txt_id = args.get("txt_id", None)
    time.sleep(3)
    if txt_id == None:
        return {
            "type": "error",
            "text": "No ID passed",
        }
    else:
        return {
            "type": "OK",
            "text": f"Ocultado texto {txt_id}",
        }


def show(**args):
    txt_id = args.get("txt_id", None)
    time.sleep(3)
    if txt_id == None:
        return {
            "type": "error",
            "text": "No ID passed",
        }
    else:
        return {
            "type": "OK",
            "text": f"Desocultado texto {txt_id}",
        }


def add_label(**args):
    patient_id = args.get("patient_id", None)
    label = args.get("label", None)
    value = args.get("value", False) in ["True", "true"]
    sim_nao = "sim" if value else "não"

    return {
        "type": "OK",
        "text": f"{label}: {sim_nao} para o paciente {patient_id}",
    }


def new_label(**args):
    label = args.get("label", None)
    if label == None:
        return {
            "type": "error",
            "text": "No label passed",
        }
    else:
        return {
            "type": "OK",
            "text": f"Criado {label}",
            "callback": f"add_label('{label}', 'sadfbiub')",
        }


COMMANDS = {
    "hide-one": hide_one,
    "show": show,
    "add-label": add_label,
    "new-label": new_label,
}

ERROR_NO_CMD = {"type": "error", "text": "No command passed"}

ERROR_NOT_FOUND = {"type": "error", "text": "Command {} not found"}


@app.route("/commands")
def commands():
    if "cmd" in request.args:
        cmd = request.args["cmd"]
        if cmd in COMMANDS:
            f = COMMANDS[cmd]
            response = f(**request.args)
        else:
            response = ERROR_NOT_FOUND.copy()
            response["text"] = response["text"].format(cmd)
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
