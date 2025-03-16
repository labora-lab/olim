from flask import flash, render_template, request, session
from flask_babel import _

from . import app
from .database import get_labels
from .functions import get_highlights, get_queue, render_entry


@app.route("/entry", methods=["GET"])
@app.route("/entry/<entry_id>", methods=["GET"])
@app.route("/queue/<queue_id>", methods=["GET"])
@app.route("/queue/<queue_id>/<int:queue_pos>", methods=["GET"])
def entry(entry_id: int | None = None, queue_id: str | None = None, queue_pos: int = 1) -> ...:
    hidden_labels = session.get("hidden_labels", [])

    show_hidden = request.args.get("show-hidden", False) == "True"

    data: dict = {
        "valid_entry": False,
        "show_hidden": show_hidden,
    }

    # Load queue (queue must be loaded before highlight)
    if queue_id is not None:
        try:
            queue = get_queue(queue_id)
            entry_id = queue[queue_pos - 1]  # type: ignore [confia no nano, deve ter type errado só]
            data.update(
                {
                    "queue_id": queue_id,
                    "queue_len": len(queue),
                    "queue_pos": queue_pos,
                }
            )
        except Exception:
            flash(
                _("Queue {queue_id} not found").format(queue_id=queue_id),
                category="error",
            )
            queue_id = None

    # Check if entry exists ans try to render it
    data = render_entry(entry_id, data)

    data.update(
        {
            "show_hidden": show_hidden,
            "labels": get_labels(),
            "highlight": get_highlights(),
            "hidden_labels": hidden_labels,
        }
    )
    return render_template("entry.html", **data)
