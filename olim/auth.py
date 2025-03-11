from flask import session, flash, abort, request, url_for, redirect, render_template
from werkzeug.security import generate_password_hash, check_password_hash
from flask_babel import _

from elasticsearch import Elasticsearch

from .settings import PERMISSIONS, NEED_BACKEND, LEARNER_KEY, LEARNER_URL, ES_SERVER
from . import app, db
from .database import (
    get_user,
    insert_user,
    get_users,
    update_user_password,
    check_db_initialized,
    init_db,
)


@app.route("/login", methods=["GET", "POST"])
def login():
    """
    This function handles the login process.
    It first checks if the user is already logged in, and flashes a warning message if they are.
    If the request method is POST, it gets the username and password from the request form, and calls the get_user function to get the user from the database.
    If the user is not found, or the password is incorrect, it flashes a warning message.
    If the user is found and the password is correct, it logs the user in and flashes a success message.
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
        username = request.form.get("username")
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
def logout():
    session.clear()
    return redirect("/")


def verify_password(password, hashed_password):
    return check_password_hash(hashed_password, password)


def login_user(user):
    session["user_id"] = user.id
    session["user"] = user.__dict__


def get_user_role(user_id=None):
    user_id = user_id or session.get("user_id")
    user = get_user(user_id, by="id")
    if user == None:
        return "guest"
    else:
        return user.role


@app.before_request
def check_permission():
    """Check user permission before each request"""
    if not check_db_initialized():
        if role_has_permission(role="guest"):
            return None
        else:
            return render_template("init-config.html")

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
def check_elasticsearch():
    if check_db_initialized() and not role_has_permission(role="guest"):
        es = es = Elasticsearch([ES_SERVER])
        try:
            # Attempt to ping the Elasticsearch server
            if es.ping():
                return  # Elasticsearch is available, proceed with the request
            else:
                raise Exception("Elasticsearch server is not responding")

        except Exception as e:
            flash(
                _(
                    "Elasticsearch server is unavailable: {}. If you just started the services, please wait for a few minutes, contact admin if problem persists."
                ).format(str(e)),
                category="error",
            )
            # Render base.html immediately and stop further processing of this request
            return render_template("base.html")


@app.before_request
def check_backend():
    if request.endpoint in NEED_BACKEND and (
        LEARNER_KEY is None or LEARNER_URL is None
    ):
        flash(
            _(
                "{requested_url} needs a backend connection, see https://gitlab.com/nanogennari/olim-backend."
            ).format(requested_url=request.url),
            category="error",
        )
        return redirect("/")


def set_guest_user():
    """Set user_id to 'guest' in session"""
    session["user_id"] = "guest"


def role_has_permission(endpoint=None, role=None):
    """Check if user has permission to access current endpoint"""
    if role is None:
        role = get_user_role()
    endpoint = endpoint or request.endpoint
    permitted_endpoints = PERMISSIONS.get(role, [])
    return endpoint in permitted_endpoints


@app.route("/init-config", methods=("POST", "GET"))
def init_config():
    if check_db_initialized():
        flash(_("Initial configuration already done!"), category="warning")
    if (
        request.method == "POST"
        and ("username" in request.form)
        and ("name" in request.form)
        and ("new_password" in request.form)
        and ("password_check" in request.form)
    ):
        username = request.form.get("username")
        password = request.form.get("new_password")
        password_check = request.form.get("password_check")
        name = request.form.get("name")
        if password != password_check:
            flash(_("Passwords do not match"), category="warning")
            return redirect("/")
        init_db(admin_user=username, admin_passwd=password, admin_name=name)
        flash(
            _("Database initialized!").format(username=username),
            category="success",
        )
        flash(
            _("User {username} sucessfully registered!").format(username=username),
            category="success",
        )
        login_user(get_user(username, by="username"))
        return redirect(url_for("upload_data"))
    return redirect("/")


@app.route("/users", methods=("POST", "GET"))
def users():
    if request.method == "POST":
        if session["user"]["role"] != "admin":
            abort(403)
        username = request.form.get("username")
        password = request.form.get("new_password")
        password_check = request.form.get("password_check")
        name = request.form.get("name")
        role = request.form.get("role")
        if password != password_check:
            flash(_("Passwords do not match"), category="warning")
        elif get_user(username, by="username") is None:
            insert_user(
                username,
                generate_password_hash(password),
                role,
                name=name,
                creator=session.get("user_id"),
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
):
    if new_password is None:
        flash(_("Please enter a new password!"), category="error")  # no new password
        return

    if new_password_check is None:
        flash(
            _("Please enter a new on both fields!"), category="error"
        )  # no new password
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
        flash(
            _("Incorrect old password!"), category="error"
        )  # old password is incorrect
        return

    update_user_password(
        to_change_user.id, new_password
    )  # if old_password is corrrect and got here, update password
    flash(_("Password sucessfully updated!"), category="success")


@app.route("/edit-password", methods=("POST", "GET"))
def edit_password():
    to_change_user_id = request.args.get("user_id") or session.get("user")["id"]
    to_change_user = get_user(to_change_user_id, by="id")
    changer_user = session.get("user")
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
