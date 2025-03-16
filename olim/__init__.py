import json
import os
from datetime import timedelta

from flask import Flask, request
from flask_babel import Babel
from flask_migrate import Migrate
from flask_session import Session
from flask_sqlalchemy import SQLAlchemy

from .settings import (
    BABEL_DEFAULT_LOCALE,
    BABEL_TRANSLATION_DIRECTORIES,
    DEBUG,
    HELP_URL,
    LABELS,
    LANGUAGES,
    LEARNER_KEY,
    LEARNER_URL,
    SECRET_KEY,
    VERSION,
)

SESSION_TYPE = "filesystem"
SESSION_PERMANENT = True
SESSION_USE_SIGNER = False
PERMANENT_SESSION_LIFETIME = timedelta(days=30)

queue_dir = "queues"
if not os.path.isdir(queue_dir):
    os.mkdir(queue_dir)

db = SQLAlchemy()
app = Flask(__name__)
# if DEBUG:
#     from werkzeug.middleware.profiler import ProfilerMiddleware

#     app.wsgi_app = ProfilerMiddleware(app.wsgi_app, restrictions=("olim", ".py"))
app.config["DEBUG"] = DEBUG
# To not receive RuntimeError talking that the session is unavailable beacause no secret key was set
app.config["SESSION_TYPE"] = SESSION_TYPE
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///olim.sqlite"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = True
app.secret_key = SECRET_KEY
Session(app)
db.init_app(app)
migrate = Migrate(app, db)

app.jinja_env.add_extension("jinja2.ext.i18n")
app.config["LANGUAGES"] = LANGUAGES
app.config["BABEL_DEFAULT_LOCALE"] = BABEL_DEFAULT_LOCALE
app.config["BABEL_TRANSLATION_DIRECTORIES"] = BABEL_TRANSLATION_DIRECTORIES
babel = Babel(app)


def get_locale() -> str | None:
    return request.accept_languages.best_match(app.config["LANGUAGES"].keys())


babel.init_app(app, locale_selector=get_locale)


# with app.app_context():
#     db.create_all()

from . import active_learning  # noqa
from . import auth  # noqa
from . import cli  # noqa
from . import commands  # noqa
from . import database  # noqa
from . import entry  # noqa
from . import hidden  # noqa
from . import issue  # noqa
from . import labels  # noqa
from . import queue  # noqa
from . import search  # noqa
from . import upload_data  # noqa
from .utils.entry import have_hidden  # noqa

app.jinja_env.globals.update(
    have_hidden=have_hidden,
    has_permition=auth.role_has_permission,
    labels_types=LABELS,
    labels_rev=LABELS[::-1],
    labels_array=json.dumps(
        [label_values[0].replace(" ", "_") for label_values in LABELS]
    ),
    has_backend=not (LEARNER_URL in [None, ""] or LEARNER_KEY in [None, ""]),
    version=VERSION,
    has_help=HELP_URL is not None,
)
