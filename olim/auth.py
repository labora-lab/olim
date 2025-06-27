from elasticsearch import Elasticsearch
from flask import abort, flash, redirect, render_template, request, session, url_for
from flask_babel import _
from werkzeug.security import check_password_hash, generate_password_hash

from . import app, settings
from .database import (
    User,
    get_project,
    get_projects,
    get_setup_step,
    get_user,
    get_users,
    init_db,
    insert_user,
    load_session,
    new_label,
    new_project,
    save_session,
    update_user,
    update_user_password,
)
from .functions import check_is_setup
from .settings import CHUNK_SIZE


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
    if not check_is_setup():
        return redirect(url_for("init_config"))
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
            login_user(user.id)
            # flash("You have successfully logged in!", category="success")
            return redirect(redirect_url)
    return render_template("login.html", redirect=redirect_url)


@app.route("/logout")
def logout() -> ...:
    session.clear()
    return redirect("/login")


def verify_password(password, hashed_password) -> bool:
    return check_password_hash(hashed_password, password)


def login_user(user_id: int) -> None:
    session.update(load_session(user_id))
    session["user_id"] = user_id
    user = get_user(user_id)
    session["language"] = user.language  # type: ignore
    session["role"] = user.role  # type: ignore


def get_user_role(user_id: str | None = None) -> str:
    user_id = user_id or session.get("user_id")
    if user_id == "guest":
        return "guest"
    user = get_user(user_id, by="id") if user_id is not None else None
    if user is None:
        return "guest"
    else:
        return user.role


@app.before_request
def check_permission() -> ...:
    """Check user permission before each request"""
    # Aways allow static/guest routes
    if role_has_permission(role="guest"):
        return None

    # Check server setup
    step = get_setup_step()
    # If we are setting up and don't have user aways allow access
    if request.endpoint == "init_config" and step == "add-user":
        return None
    # If we are not set up redirect to init config
    if not check_is_setup() and request.endpoint != "init_config":
        if not (
            step == "add-data"
            and request.endpoint in ["upload_data", "handle_large_upload", "finalize_upload"]
        ):
            return redirect(url_for("init_config"))

    # Check user
    current_user_id = session.get("user_id")

    if current_user_id is None:  # the first request to the app
        set_guest_user()  # set user_id to 'guest' in session
        current_user_id = "guest"

    # Redirect guest to login page if they are trying to access resticted endpoint
    if current_user_id == "guest" and not role_has_permission(role="guest"):
        if request.path != "/":
            flash(_("You are not logged"), category="warning")
        return redirect(url_for("login") + f"?redirect={request.path}")

    if current_user_id != "guest":
        user = get_user(current_user_id, by="id")
        if user is None:
            flash(_("Your login has expired"), category="warning")
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
def check_elasticsearch() -> ...:
    if check_is_setup() and not role_has_permission(role="guest"):
        es = Elasticsearch([settings.ES_SERVER])
        try:
            # Attempt to ping the Elasticsearch server
            if es.ping():
                return None  # Elasticsearch is available, proceed with the request
            else:
                raise Exception("Elasticsearch server is not responding")

        except Exception as e:
            flash(
                _(
                    "Elasticsearch server is unavailable: {error}."
                    "If you just started the services, please wait for "
                    "a few minutes, contact admin if problem persists."
                ).format(error=str(e)),
                category="error",
            )
            # Render base.html immediately and stop further processing of this request
            return render_template("base.html")


@app.before_request  # type: ignore
def add_projects() -> ...:
    if check_is_setup():
        if "project_id" not in session:
            session["project_id"] = get_projects()[0].id
        app.jinja_env.globals.update(
            projects=list(get_projects()),
            project_id=session["project_id"],
            project_name=get_project(session["project_id"]).name,  # type: ignore
        )


@app.teardown_request
def save_database_session(exc=None) -> None:
    """Persist Flask session changes to database."""
    if "user_id" in session:
        if type(session["user_id"]) is int:
            # Only save if session was modified
            if session.modified:
                save_session(session["user_id"], dict(session))


# @app.context_processor
# def inject_session_vars():
#     """Make session data available in templates."""
#     return dict(session=session)


def set_guest_user() -> None:
    """Set user_id to 'guest' in session"""
    session["user_id"] = "guest"


def role_has_permission(endpoint=None, role=None) -> bool:
    """Check if user has permission to access current endpoint"""
    if role is None:
        role = get_user_role()
    endpoint = endpoint or request.endpoint
    permitted_endpoints = settings.PERMISSIONS.get(role, [])
    return endpoint in permitted_endpoints


@app.route("/init-config", methods=("POST", "GET"))
def init_config() -> ...:
    if not get_setup_step():
        flash(_("Initial configuration already done!"), category="warning")
        return redirect("/")
    if request.method == "POST" and request.form["step"] == "add-user":
        username = request.form["username"]
        password = request.form["new_password"]
        password_check = request.form["password_check"]
        name = request.form["name"]
        if password != password_check:
            flash(_("Passwords do not match"), category="warning")
            return render_template("init-config.html", step=get_setup_step())
        if len(name) == 0:
            flash(_("Name can't be empty."), category="warning")
            return render_template("init-config.html", step=get_setup_step())
        if len(username) == 0:
            flash(_("Username can't be empty."), category="warning")
            return render_template("init-config.html", step=get_setup_step())
        if len(password) < 8:
            flash(_("Minimum password lenght is 8."), category="warning")
            return render_template("init-config.html", step=get_setup_step())
        init_db(admin_user=username, admin_passwd=password, admin_name=name)
        flash(
            _("Database initialized!").format(username=username),
            category="success",
        )
        flash(
            _("User {username} sucessfully registered!").format(username=username),
            category="success",
        )
        user = get_user(username, by="username")
        if user is not None:
            login_user(user.id)
        else:
            raise ValueError("Error initializing database.")
    if request.method == "POST" and request.form["step"] == "add-project":
        name = request.form["name"]
        labels = [label.strip() for label in request.form.getlist("labels") if label.strip()]
        if len(name) == 0:
            flash(_("Project name can't be empty."), category="warning")
            return render_template("init-config.html", step=get_setup_step())
        user_id = session["user_id"]
        project = new_project(name, user_id)
        flash(
            _("Project {project_name} successfully created!").format(project_name=name),
            category="success",
        )
        if not project:
            flash(_("Falied creating project."), category="error")
            return render_template("init-config.html", step=get_setup_step())
        for label in labels:
            if new_label(label, user_id, project.id):
                flash(
                    _("Label {label_name} successfully created!").format(label_name=label),
                    category="success",
                )
            else:
                flash(
                    _(f"Falied creating label {label}."),
                    category="warning",
                )
        session["project_id"] = project.id
    if get_setup_step() == "add-data":
        return render_template(
            "init-config.html",
            step=get_setup_step(),
            projects=list(get_projects()),
            CHUNK_SIZE=CHUNK_SIZE,
        )
    return render_template("init-config.html", step=get_setup_step())


@app.route("/users", methods=("POST", "GET"))
def users() -> ...:
    if request.method == "POST":
        if session["role"] != "admin":
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
        "roles": list(settings.PERMISSIONS.keys()),
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

    if changer_user.role != "admin" and old_password is None:
        flash(
            _("Please enter your old password!"), category="error"
        )  # no old password when is not admin
        return

    if changer_user.role != "admin" and not verify_password(old_password, changer_user.password):
        flash(_("Incorrect old password!"), category="error")  # old password is incorrect
        return

    update_user_password(
        to_change_user.id, new_password
    )  # if old_password is corrrect and got here, update password
    flash(_("Password sucessfully updated!"), category="success")


def get_user_obj(user_id: int | None) -> User | None:
    user_id = user_id or session["user_id"]

    if (user_id is None) or (session["role"] != "admin" and session["user_id"] != user_id):
        return None

    user = get_user(user_id, by="id")
    return user


@app.route("/user", methods=["GET"])
@app.route("/user/<int:user_id>", methods=["GET"])
def user_settings(user_id: int | None = None) -> ...:
    user = get_user_obj(user_id)

    if user is None:
        flash(
            _("You do not have permission to change user id {user_id} settings.").format(
                user_id=user_id
            ),
            category="error",
        )
        return redirect(url_for("user_settings"))

    return render_template("account-settings.html", user=user, languages=settings.LANGUAGES)


@app.route("/user/<int:user_id>/set/password", methods=["POST"])
def edit_password(user_id: int | None = None) -> ...:
    to_change_user = get_user_obj(user_id)
    changer_user = get_user(session["user_id"])

    if to_change_user is None or changer_user is None:
        flash(
            _(
                "You do not have permission to change password for user id {user_id} settings."
            ).format(user_id=user_id),
            category="error",
        )
        return redirect(url_for("user_settings"))

    if request.method == "POST":
        old_password = request.form.get("old_password")
        new_password = request.form.get("new_password")
        new_password_check = request.form.get("password_check")
        security_edit_password(
            to_change_user, changer_user, old_password, new_password, new_password_check
        )

    return redirect(url_for("user_settings", user_id=to_change_user.id))


@app.route("/user/<int:user_id>/set/language", methods=["POST"])
def edit_language(user_id: int | None = None) -> ...:
    to_change_user = get_user_obj(user_id)

    if to_change_user is None:
        flash(
            _("You have no permission to change language for user id {user_id} settings.").format(
                user_id=user_id
            ),
            category="error",
        )
        return redirect(url_for("user_settings"))

    if request.method == "POST":
        language = request.form.get("language") or None
        to_change_user.language = language
        user = update_user(to_change_user.id, language=language)
        if user is not None:
            # Update user on session for babel to use the correct language
            session["language"] = language
            if user.language is not None:
                flash(
                    _("Changed language for {user_name} to {language}!").format(
                        user_name=user.name, language=settings.LANGUAGES[user.language]
                    ),
                    category="success",
                )
            else:
                flash(
                    _("Changed language for {user_name} to Automatic!").format(user_name=user.name),
                    category="success",
                )

    return redirect(url_for("user_settings", user_id=to_change_user.id))


@app.route("/print_session")
def print_session() -> ...:
    return render_template("base.html", content=dict(session))
