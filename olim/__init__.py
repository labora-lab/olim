from flask import Flask
from .settings import DEBUG, SECRET_KEY, LABELS
from flask_session import Session
from flask_sqlalchemy import SQLAlchemy
import os
import json
from datetime import timedelta

SESSION_TYPE = "filesystem"
SESSION_PERMANENT = True
SESSION_USE_SIGNER = False
PERMANENT_SESSION_LIFETIME = timedelta(days=30)

queue_dir = "queues"
if not os.path.isdir(queue_dir):
    os.mkdir(queue_dir)

db = SQLAlchemy()
app = Flask(__name__)
app.config["DEBUG"] = DEBUG
# To not receive RuntimeError talking that ths session is unavailable beaceuse no secret key was set.
app.config["SESSION_TYPE"] = SESSION_TYPE
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///olim.sqlite"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = True
app.secret_key = SECRET_KEY
Session(app)
db.init_app(app)


# with app.app_context():
#     db.create_all()

from . import entry
from . import search
from . import commands
from . import hidden
from . import labels
from . import queue
from . import database
from . import auth
from . import cli

from .functions import have_hidden

app.jinja_env.globals.update(
    have_hidden=have_hidden,
    has_permition=auth.role_has_permission,
    labels_types=LABELS,
    labels_rev=[l for l in LABELS[::-1]],
    labels_array=json.dumps([l[0].replace(" ", "_") for l in LABELS]),
)
