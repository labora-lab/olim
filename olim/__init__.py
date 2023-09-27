from flask import Flask, request
from .settings import (
    DEBUG, 
    SECRET_KEY, 
    LABELS, 
    LANGUAGES, 
    BABEL_DEFAULT_LOCALE, 
    BABEL_TRANSLATION_DIRECTORIES
)
from flask_session import Session
from flask_sqlalchemy import SQLAlchemy
from flask_babel import Babel
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
# To not receive RuntimeError talking that the session is unavailable beacause no secret key was set.
app.config["SESSION_TYPE"] = SESSION_TYPE
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///olim.sqlite"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = True
app.secret_key = SECRET_KEY
Session(app)
db.init_app(app)

app.jinja_env.add_extension("jinja2.ext.i18n")
app.config["LANGUAGES"] = LANGUAGES
app.config["BABEL_DEFAULT_LOCALE"] = BABEL_DEFAULT_LOCALE
app.config['BABEL_TRANSLATION_DIRECTORIES'] = BABEL_TRANSLATION_DIRECTORIES
babel = Babel(app)

def get_locale():
    return request.accept_languages.best_match(app.config["LANGUAGES"].keys())

babel.init_app(app, locale_selector=get_locale)


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
