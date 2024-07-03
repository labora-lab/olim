from . import app
from .functions import (
    parse_queue,
    store_queue,
    get_queue,
    get_def_nentries,
    get_all_queues,
)
from .database import random_entries
from flask import request, render_template, flash, redirect, session
from flask_babel import _


@app.route("/new-queue", methods=["POST", "GET"])
@app.route("/new-queue/<queue_id>", methods=["GET"])
def new_queue(queue_id=None):
    # If a we have a queue_id load that queue
    if queue_id != None:
        queue = get_queue(queue_id)
        return render_template("queue.html", queue=queue, queue_hash=queue_id)

    # Check if we have a rquest
    type = request.form.get("type", "")
    queue = []
    # If our request is of type random
    if type == "random":
        try:
            # Try to parse the number and store it
            number = int(request.form.get("number"))
            session["number_of_entries"] = number
            # Generate the queue
            queue = [entry.entry_id for entry in random_entries(number)]
        except ValueError:
            flash(_("Invalid number of entries"), category="error")
    # If our request is of type list
    elif type == "list":
        # Try to parse the list and store it
        queue = parse_queue(request.form.get("text", ""))

    # If we have a populated queue store it and redirect by the id
    if len(queue) > 0:
        queue_id = store_queue(queue)
        return redirect(f"/new-queue/{queue_id}")
    # If not render blank page
    else:
        return render_template(
            "queue.html", number=get_def_nentries(), queues=get_all_queues()
        )
