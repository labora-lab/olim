from . import app, db
from .database import (
    get_labels,
    get_users,
    get_entry,
    init_db,
)
import click
import sys


@app.cli.command("init-db", help="Inializes database and create Administrator user.")
def init_db_cli():
    init_db()


@app.cli.group("labels", help="Labels related commands.")
def labels():
    pass


@click.command("list", help="Print list of active labels.")
def labels_ls():
    for label in get_labels():
        print(label.name, label.created, label.creator.username)


labels.add_command(labels_ls)


@app.cli.group("users", help="Users related commands.")
def users():
    pass


@click.command("list", help="Print list of active users.")
def users_ls():
    for user in get_users():
        print(user.id, user.username, user.name, user.creator.name)


users.add_command(users_ls)


@app.cli.group("upload", help="Data upload related commands.")
def upload():
    # check if db is initialized
    try:
        get_entry(1)
    except db.exc.OperationalError:
        print("Failed to access OLIM database.")
        opt = ""
        while opt.lower().strip() not in ["y", "n", "yes", "no"]:
            opt = input("Do you want to run init-db now? ([y]/n) ")
            if opt.strip() == "":
                opt = "y"
        if opt.lower().strip()[0] == "y":
            init_db()
        else:
            print()
            sys.exit("Can't proceed!")
