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


COMMANDS = {
    "hide-one": hide_one,
    "show": show,
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
    return json.dumps(response)
