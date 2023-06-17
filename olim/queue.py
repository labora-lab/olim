from . import app
from .functions import parse_queue, store_queue
from flask import request, render_template
from typing import List


@app.route("/new-queue", methods=["POST", "GET"])
def new_queue():
    queue = parse_queue(request.form.get("text", ""))
    if len(queue) > 0:
        queue_h = store_queue(queue)
        return render_template("queue.html", queue=queue, queue_hash=queue_h)
    else:
        return render_template("queue.html")
