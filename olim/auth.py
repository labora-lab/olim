from . import app
from .db import get_user, insert_user
from flask import session, flash, abort, request, url_for, redirect, render_template
from werkzeug.security import generate_password_hash, check_password_hash
from .settings import PERMISSIONS


@app.route("/login", methods=("GET", "POST"))
def login():
    """
    This function handles the login process. 
    It first checks if the user is already logged in, and flashes a warning message if they are. 
    If the request method is POST, it gets the username and password from the request form, and calls the get_user function to get the user from the database. 
    If the user is not found, or the password is incorrect, it flashes a warning message. 
    If the user is found and the password is correct, it logs the user in and flashes a success message. 
    Finally, it renders the login template.
    :return: The rendered login.html template.
    """
    user_id = session["user_id"] if session.get("user_id") != "guest" else None
    if user_id is not None:
        flash("You are already logged in.", category="warning")
    elif request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        user = get_user(username, by="username")
        if user is None:
            flash("Incorrect username and/or password!", category="warning")
        elif not verify_password(password, user["password"]):
            flash("Incorrect username and/or password!", category="warning")
        else:
            login_user(user)
            flash("You have successfully logged in!", category="success")
    return render_template("login.html")

    
def verify_password(password, hashed_password):
    return check_password_hash(hashed_password, password)
    
def login_user(user):
    session["user_id"] = user["id"]

@app.before_request
def check_permission():
    """Check user permission before each request"""
    current_user_id = session.get("user_id")
    if current_user_id is None: # the first request to the app
        set_guest_user() # set user_id to 'guest' in session
        flash("You are not logged in.", category="warning")
        return redirect(url_for("login")) # redirect to login page
    
    if current_user_id != "guest": # if user_id is not 'guest' 
        user = get_user(current_user_id, by="id")
        if user is None:
            abort(404) # user not found
        if not role_has_permission(user["role"]):
            abort(403) # user does not have permission
    
    if not role_has_permission("guest"):
        flash("You are not logged in.", category="warning")
        return redirect(url_for("login"))


def set_guest_user():
    """Set user_id to 'guest' in session"""
    session["user_id"] = "guest"


def role_has_permission(role):
    """Check if user has permission to access current endpoint"""
    permitted_endpoints = PERMISSIONS.get(role, [])
    return request.endpoint in permitted_endpoints
    


@app.route("/users", methods=("POST", "GET"))
def users():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        role = request.form.get("role")
        hashed_password = generate_password_hash(password)
        if get_user(username, by="username") is None:
            insert_user(username, password, role)
    
    return render_template("users.html")