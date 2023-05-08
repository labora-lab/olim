from flask import Flask
from .settings import DEBUG
import tempfile

tmp_dir = tempfile.mkdtemp(prefix="olim_")

app = Flask(__name__)
app.config['DEBUG'] = DEBUG

from . import patient
from . import search
from . import commands
from . import hidden
from . import labels
from . import queue
