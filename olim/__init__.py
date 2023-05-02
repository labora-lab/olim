from flask import Flask
from .settings import DEBUG

app = Flask(__name__)
app.config['DEBUG'] = DEBUG

from . import patient
from . import search
from . import commands
from . import hidden
from . import labels
