from flask import Flask
from .settings import DEBUG, SECRET_KEY
from flask_session import Session
from flask_sqlalchemy import SQLAlchemy
import tempfile
from datetime import timedelta

SESSION_TYPE = "filesystem"
SESSION_PERMANENT = True
SESSION_USE_SIGNER = False
PERMANENT_SESSION_LIFETIME = timedelta(days=30)

tmp_dir = tempfile.mkdtemp(prefix="olim_")

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
