import datetime as dt

import requests
from flask import flash, redirect, render_template, request, session
from flask_babel import _

from . import app, settings
from .database import get_user

TIMEZONE = dt.timezone(dt.timedelta(hours=-3))


@app.route("/help", methods=["GET"])
def get_help() -> ...:
    previous_url = request.referrer
    return render_template("help.html", previous_url=previous_url)


@app.route("/help/send", methods=["POST"])
def send_ticket() -> ...:
    previous_url = request.form.get("url", "/")
    if request.method == "POST":
        email = request.form.get("email")
        subject = request.form.get("subject")
        message = request.form.get("message")
        current_user = get_user(session["user_id"])
        if current_user is None:
            return
        data = {
            "app_key": settings.LEARNER_KEY,
            "user_id": session["user_id"],
            "username": current_user.username,
            "name": current_user.name,
            "subject": subject,
            "message": message,
            "email": email,
            "url": previous_url,
            "version": settings.VERSION,
            "time": dt.datetime.now(TIMEZONE).strftime("%d-%m-%Y %H:%M:%S"),
        }
        res = requests.post(settings.HELP_URL, data=data).json()
        if res["status"] == "error":
            flash(
                _(
                    "Error sending ticket. Please try again later or check your HELP_URL "
                    "environment variable."
                ),
                category="error",
            )
            return redirect(previous_url)
        flash(_("Ticket sent. Thank you very much."), category="success")
    return redirect(previous_url)
