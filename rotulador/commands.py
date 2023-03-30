from . import app
from .functions import (
    update_hidden,
    add_patient_label,
    create_new_label,
    add_text_to_hide,
)
from flask import request, render_template
import json


def hide_one(**args):
    txt_id = args.get("txt_id", None)
    patient_id = int(args.get("patient_id", None))

    try:
        update_hidden(txt_id, patient_id, True)
    except:
        return {
            "type": "error",
            "text": "Failed writing to database",
        }

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
    patient_id = int(args.get("patient_id", None))

    try:
        update_hidden(txt_id, patient_id, False)
    except:
        return {
            "type": "error",
            "text": "Failed writing to database",
        }

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

    try:
        add_patient_label(label, patient_id, value)
    except:
        return {
            "type": "error",
            "text": "Failed writing to database",
        }

    if patient_id == None:
        return {
            "type": "error",
            "text": "No patient ID passed",
        }
    elif label == None:
        return {
            "type": "error",
            "text": "No label passed",
        }
    else:
        return {
            "type": "OK",
            "text": f"{label}: {sim_nao} para o paciente {patient_id}",
        }


def new_label(**args):
    patient_id = args.get("patient_id", "")
    label = args.get("label", None)

    try:
        resp = create_new_label(label)
    except:
        return {
            "type": "error",
            "text": "Failed writing to database",
        }

    if patient_id == "":
        html = render_template(
            "label.html",
            label={"_source": {"label": label}, "_id": resp["_id"]},
        )
    else:
        html = render_template(
            "label.html",
            label={"_source": {"label": label}, "_id": resp["_id"]},
            patient_id=patient_id,
        )

    html = html.replace("'", "\\'").replace("\n", " ")

    if label == None:
        return {
            "type": "error",
            "text": "No label passed",
        }
    else:
        return {
            "type": "OK",
            "text": f"Criado rótulo {label}",
            "callback": f"add_label('{html}')",
        }


def hide_all(**args):
    patient_id = args.get("patient_id", None)
    text = args.get("text", None)
    text_id = args.get("text_id", None)

    try:
        add_text_to_hide(text, text_id, patient_id)
    except:
        return {
            "type": "error",
            "text": "Failed writing to database",
        }

    if patient_id == None or text == None or text_id == None:
        return {
            "type": "error",
            "text": f"Missing data: {patient_id}, {text_id}, {text}",
        }
    else:
        return {
            "type": "OK",
            "text": f"Sempre esconderá texto {text}",
        }


COMMANDS = {
    "hide-one": hide_one,
    "hide-all": hide_all,
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
