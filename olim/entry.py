from . import app, entry_types
from .functions import get_queue, manage_label_in_session
from .database import get_labels, get_entry
from flask import request, render_template, flash, session
import json


@app.route("/entry", methods=["GET"])
@app.route("/entry/<entry_id>", methods=["GET"])
@app.route("/queue/<queue_id>", methods=["GET"])
@app.route("/queue/<queue_id>/<int:queue_pos>", methods=["GET"])
def entry(entry_id=None, queue_id=None, queue_pos=1):
    hidden_labels = request.args.get("hidden_labels", [])
    if len(hidden_labels) > 0:
        try:
            for label in json.loads(hidden_labels):
                manage_label_in_session(label, session, "add")
        except ValueError:
            pass

    hidden_labels = session.get("hidden_labels", [])
    show_hidden = request.args.get("show-hidden", False) == "True"
    highlight = request.args.get("highlight", [])

    data = {"valid_entry": False}

    # Load queue
    if queue_id != None:
        try:
            queue = get_queue(queue_id)
            entry_id = queue[queue_pos - 1]
        except:
            flash(f"Fila {queue_id} não encontrada", category="error")
            queue_id = None

    if entry_id != None:
        try:
            entry = get_entry(entry_id)
            print(entry)
            e_type = getattr(entry_types, entry.type)
            data.update(
                {
                    "entry_id": entry_id,
                    "entry_html": e_type.render(
                        entry_id,
                        show_hidden=show_hidden,
                        highlight=highlight,
                    ),
                    "entry": entry,
                    "labels_values": {
                        label.label_id: label.value
                        for label in entry.labels
                        if not label.is_deleted
                    },
                    "valid_entry": True,
                }
            )
        except:
            flash(f"Entrada {entry_id} não encontrada", category="error")
            data["valid_entry"] = False

    data.update(
        {
            "show_hidden": show_hidden,
            "labels": get_labels(),
            "highlight": highlight,
            "hidden_labels": hidden_labels,
        }
    )
    if queue_id != None:
        data.update(
            {
                "queue_id": queue_id,
                "queue_len": len(queue),
                "queue_pos": queue_pos,
            }
        )

    return render_template("entry.html", **data)
