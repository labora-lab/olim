from flask import Flask
from .settings import DEBUG, SECRET_KEY
from flask_session import Session
import tempfile
from datetime import timedelta

SESSION_TYPE = "filesystem"
SESSION_PERMANENT = True
SESSION_USE_SIGNER = False
PERMANENT_SESSION_LIFETIME = timedelta(days=30)

tmp_dir = tempfile.mkdtemp(prefix="olim_")

app = Flask(__name__)
app.config["DEBUG"] = DEBUG
app.secret_key = SECRET_KEY
Session(app)

from . import patient
from . import search
from . import commands
from . import hidden
from . import labels
from . import queue
