from flask import abort, flash, redirect, render_template, request, session, url_for
from flask_babel import _
from werkzeug.security import check_password_hash, generate_password_hash

from . import app
from .database import get_user, get_users, insert_user, update_user_password
from .settings import LEARNER_KEY, LEARNER_URL, NEED_BACKEND, PERMISSIONS


@app.route("/login", methods=["GET", "POST"])
def login() -> ...:
    """
    This function handles the login process.
    It first checks if the user is already logged in, and flashes a warning message if they are.
    If the request method is POST, it gets the username and password from the request form, and
        calls the get_user function to get the user from the database.
    If the user is not found, or the password is incorrect, it flashes a warning message.
    If the user is found and the password is correct, it logs the user in and flashes a success
        message.
    Finally, it renders the login template.

    Return:
        The rendered login.html template.
    """
    redirect_url = request.args.get("redirect", "/")
    user_id = session["user_id"] if session.get("user_id") != "guest" else None
    if user_id is not None:
        return redirect("/")
    elif request.method == "POST":
        redirect_url = request.form.get("redirect", "/")
        username = request.form.get("username", default="")
        password = request.form.get("password")
        user = get_user(username, by="username")
        if user is None:
            flash(_("Incorrect Username and/or Password!"), category="error")
        elif not verify_password(password, user.password):
            flash(_("Incorrect Username and/or Password!"), category="error")
        else:
            login_user(user)
            # flash("You have successfully logged in!", category="success")
            return redirect(redirect_url)
    return render_template("login.html", redirect=redirect_url)


@app.route("/logout")
def logout() -> ...:
    session.clear()
    return redirect("/")


def verify_password(password, hashed_password) -> bool:
    return check_password_hash(hashed_password, password)


def login_user(user) -> None:
    session["user_id"] = user.id
    session["user"] = user.__dict__


def get_user_role(user_id: str | None = None) -> str:
    user_id = user_id or session.get("user_id")
    user = get_user(user_id, by="id") if user_id is not None else None
    if user is None:
        return "guest"
    else:
        return user.role


@app.before_request
def check_permission() -> ...:
    """Check user permission before each request"""
    current_user_id = session.get("user_id")
    if current_user_id is None:  # the first request to the app
        set_guest_user()  # set user_id to 'guest' in session
        flash(_("You are not logged"), category="warning")
        return redirect(url_for("login") + f"?redirect={request.path}")

    if current_user_id == "guest" and not role_has_permission(role="guest"):
        flash(_("You are not logged"), category="warning")
        return redirect(url_for("login") + f"?redirect={request.path}")

    if current_user_id != "guest":
        user = get_user(current_user_id, by="id")
        if user is None:
            flash(
                _(
                    "Your login has expired",
                ),
                category="warning",
            )
            set_guest_user()
            return redirect(url_for("login") + f"?redirect={request.path}")
        if not role_has_permission(role=user.role):
            if "favicon" in request.url:
                abort(403)
            else:
                flash(
                    _("You do not have permission to access {requested_url}.").format(
                        requested_url=request.url
                    ),
                    category="warning",
                )
                return redirect("/")


@app.before_request
def check_backend() -> ...:
    if request.endpoint in NEED_BACKEND and (LEARNER_KEY is None or LEARNER_URL is None):
        flash(
            _(
                "{requested_url} needs a backend connection, see https://gitlab.com/nanogennari/olim-backend."
            ).format(requested_url=request.url),
            category="error",
        )
        return redirect("/")


def set_guest_user() -> None:
    """Set user_id to 'guest' in session"""
    session["user_id"] = "guest"


def role_has_permission(endpoint=None, role=None) -> bool:
    """Check if user has permission to access current endpoint"""
    role = role or get_user_role()
    endpoint = endpoint or request.endpoint
    permitted_endpoints = PERMISSIONS.get(role, [])
    return endpoint in permitted_endpoints


@app.route("/users", methods=("POST", "GET"))
def users() -> ...:
    if request.method == "POST":
        if session["user"]["role"] != "admin":
            abort(403)
        username = request.form.get("username", default="")
        password = request.form.get("new_password", default="")
        password_check = request.form.get("password_check", default="")
        name = request.form.get("name", default="")
        role = request.form.get("role", default="")
        if password != password_check:
            flash(_("Passwords do not match"), category="warning")
        elif get_user(username, by="username") is None:
            insert_user(
                username,
                generate_password_hash(password),
                role,
                name=name,
                creator=session.get("user_id", -1),  # -1 bypass int type
            )
            flash(
                _("User {username} sucessfully registered!").format(username=username),
                category="success",
            )
        else:
            flash(
                _("User {username} already exists!").format(username=username),
                category="warning",
            )

    context = {
        "users": get_users(),
        "roles": list(PERMISSIONS.keys()),
    }

    return render_template("users.html", **context)


def security_edit_password(
    to_change_user, changer_user, old_password, new_password, new_password_check
) -> None:
    if new_password is None:
        flash(_("Please enter a new password!"), category="error")  # no new password
        return

    if new_password_check is None:
        flash(_("Please enter a new on both fields!"), category="error")  # no new password
        return

    if new_password != new_password_check:
        flash(_("Passwords do not match!"), category="error")
        return

    if changer_user["role"] != "admin" and old_password is None:
        flash(
            _("Please enter your old password!"), category="error"
        )  # no old password when is not admin
        return

    if changer_user["role"] != "admin" and not verify_password(
        old_password, changer_user["password"]
    ):
        flash(_("Incorrect old password!"), category="error")  # old password is incorrect
        return

    update_user_password(
        to_change_user.id, new_password
    )  # if old_password is corrrect and got here, update password
    flash(_("Password sucessfully updated!"), category="success")


@app.route("/edit-password", methods=("POST", "GET"))
def edit_password() -> ...:
    to_change_user_id = (
        request.args.get("user_id") or session_user["id"]
        if (session_user := session.get("user"))
        else None
    )

    if to_change_user_id is None:
        abort(403)

    to_change_user = get_user(to_change_user_id, by="id")
    changer_user = session.get("user")

    if changer_user is None:
        abort(404)

    # verify if user is non-admin and id that it wants to change
    if changer_user["role"] != "admin" and int(to_change_user_id) != changer_user["id"]:
        abort(403)
    if request.method == "POST":
        old_password = request.form.get("old_password")
        new_password = request.form.get("new_password")
        new_password_check = request.form.get("password_check")
        security_edit_password(
            to_change_user, changer_user, old_password, new_password, new_password_check
        )

    return render_template("edit-password.html", user=to_change_user)
