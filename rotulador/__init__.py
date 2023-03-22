from flask import Flask

app = Flask(__name__)

from . import index
from . import patient
from . import search
from . import commands
