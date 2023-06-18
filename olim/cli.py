from . import app, db
from .database import (
    get_labels,
    get_users,
    get_entry,
    init_db,
)
from .functions import label_upload
import click
import sys
import pandas as pd


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


@click.command(
    "upload",
    help="Uploads labels values from a CSV file."
    "\n\n\tCSV_FILE\tPath to the CSV file to load data.",
)
def up_labels(csv_file):
    print("Loading labels values from CSV file...")
    df = pd.read_csv(csv_file)

    print("Uploading labels values...")
    label_upload(df)


labels.add_command(up_labels)
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
