from flask import Flask

app = Flask(__name__)

from . import patient
from . import search
from . import commands
from . import hidden
from . import labels
