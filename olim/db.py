import sqlite3
import os
from .settings import DB_PATH
from flask import session, abort
from . import app

def get_conn(ignore_errors=False):
    """
    Returns a connection to the SQLite database located at DB_PATH if it exists.
    
    :return: A connection object to the SQLite database located at DB_PATH.
    :rtype: sqlite3.Connection
    
    :raises: 503 error if the database file does not exist.
    """
    if not os.path.isfile(DB_PATH) and not ignore_errors:
        print("The db file does not exist.")
        abort(503)
    
    # TODO: Make this more robust.
    try:
        session_db = session.get("db")
    except RuntimeError:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn
    else:
        if session_db is not None:
            conn = sqlite3.connect(DB_PATH)
            conn.row_factory = sqlite3.Row
            session["db"] = conn
    return session["db"]

def get_user(identification: int, by:str="id"):
    """
    Retrieves a user from the database by either their ID or username.

    :param identification: An integer representing the user's ID or a string representing their username.
    :param by: A string indicating whether to search by ID or username. Defaults to "id".
    :return: A tuple representing the user's information from the database or None if not found.
    :raises: Exception if an invalid 'by' parameter is provided.
    """
    conn = get_conn()
    if by == "id":
        return conn.execute("SELECT * FROM users WHERE id = ?", (identification,)).fetchone()
    elif by == "username":
        return conn.execute("SELECT * FROM users WHERE username = ?", (identification,)).fetchone()
    raise Exception("Invalid by parameter")

def insert_user(username: str, hashed_password: str, role: str, **kwargs):
    """
    Inserts a user into the database.

    :param username: A string representing the user's username.
    :param hashed_password: A string representing the user's hashed password.
    :param role: A string representing the user's role. Can be "user" or "admin".
    :param kwargs: Additional parameters where "name" is the user's name.
    """
    if kwargs.get("name") is not None:
        name = kwargs.get("name")
    else:
        name = username.capitalize()

    conn = get_conn()
    conn.execute("INSERT INTO users (username, password, role, name) VALUES (?, ?, ?, ?)", (username, hashed_password, role, name))
    conn.commit()


@app.cli.command("initdb")
def init_db():
    """
    Initializes the database.
    """
    print("Initializing database...")
    db = get_conn(ignore_errors=True)
    with app.open_resource(os.path.join(os.getcwd(), "schema.sql"), mode="r") as f:
        db.cursor().executescript(f.read())
    db.commit()
    print("Database initialized.")