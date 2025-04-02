import sys
from getpass import getpass

import click
import pandas as pd

from . import app, db
from .database import get_entry, get_labels, get_user, get_users, init_db, update_user_password
from .utils.label import label_upload


@app.cli.command("init-db", help="Inializes database and create Administrator user.")
def init_db_cli() -> None:
    init_db()


@app.cli.group("labels", help="Labels related commands.")
def labels() -> None:
    pass


@click.command("list", help="Print list of active labels.")
def labels_ls() -> None:
    for label in get_labels():
        print(label.name, label.created, label.creator.username)


@click.command(
    "upload",
    help="Uploads labels values from a CSV file."
    "\n\n\tCSV_FILE\tPath to the CSV file to load data."
    "\n\n\tUSERNAME\tUsername to register labels as.",
)
@click.argument("csv_file")
@click.argument("username")
def up_labels(csv_file: str, username: str) -> None:
    print("Loading labels values from CSV file...")
    df = pd.read_csv(csv_file)
    user = get_user(username, "username")
    if not user:
        print(f"Error: User {username} not found!")
        sys.exit(1)

    print(f"Uploading labels values as {user.name}...")
    label_upload(df, user.id)


labels.add_command(up_labels)
labels.add_command(labels_ls)


@app.cli.group("users", help="Users related commands.")
def users() -> None:
    pass


@click.command("list", help="Print list of active users.")
def users_ls() -> None:
    for user in get_users():
        print(user.id, user.username)


@click.command(
    "password",
    help="Change user password.",
)
@click.argument("username")
def change_passwd(username: str) -> None:
    user = get_user(username, by="username")
    if user:
        passwd = getpass("New password:")
        if passwd == getpass("Again:"):
            if update_user_password(user.id, passwd):
                print("Password changed!")
            else:
                print("Error updating password")
        else:
            print("Passwords don't match, try again.")
    else:
        print(f"Error: User {username} not found!")


users.add_command(users_ls)
users.add_command(change_passwd)


@app.cli.group("upload", help="Data upload related commands.")
def upload() -> None:
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
