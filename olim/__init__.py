import json

from flask import Flask, request, session
from flask_babel import Babel
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy

from flask_session import Session

# from werkzeug.middleware.profiler import ProfilerMiddleware
from .settings import (
    BABEL_DEFAULT_LOCALE,
    BABEL_TRANSLATION_DIRECTORIES,
    DB_HOST,
    DB_NAME,
    DB_PASSWORD,
    DB_PORT,
    DB_USER,
    DEBUG,
    HELP_URL,
    LABELS,
    LANGUAGES,
    PERMANENT_SESSION_LIFETIME,
    SECRET_KEY,
    SESSION_PERMANENT,
    SESSION_TYPE,
    SESSION_USE_SIGNER,
    VERSION,
)

db = SQLAlchemy()
sess = Session()
app = Flask(__name__)
app.config["DEBUG"] = DEBUG

# Database configuration
if all([DB_HOST, DB_NAME, DB_USER, DB_PASSWORD]):
    app.config["SQLALCHEMY_DATABASE_URI"] = (
        f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    )
else:
    print("Warning: Missing PostgreSQL configuration. Falling back to SQLite.")
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///olim.sqlite"


# Session and database init
db.init_app(app)
migrate = Migrate(app, db)

# Session configuration
app.config["SESSION_TYPE"] = SESSION_TYPE
app.config["SESSION_PERMANENT"] = SESSION_PERMANENT
app.config["SESSION_USE_SIGNER"] = SESSION_USE_SIGNER
app.config["PERMANENT_SESSION_LIFETIME"] = PERMANENT_SESSION_LIFETIME
app.secret_key = SECRET_KEY
app.config["SESSION_SQLALCHEMY"] = db
sess.init_app(app)

# Babel configuration
app.jinja_env.add_extension("jinja2.ext.i18n")
app.config["LANGUAGES"] = LANGUAGES
app.config["BABEL_DEFAULT_LOCALE"] = BABEL_DEFAULT_LOCALE
app.config["BABEL_TRANSLATION_DIRECTORIES"] = BABEL_TRANSLATION_DIRECTORIES


def get_locale() -> str | None:
    if "language" not in session:
        return request.accept_languages.best_match(app.config["LANGUAGES"].keys())
    if session["language"]:
        return session["language"]
    else:
        return request.accept_languages.best_match(app.config["LANGUAGES"].keys())


babel = Babel(app, locale_selector=get_locale)

# # Profiling
# app.wsgi_app = ProfilerMiddleware(
#     app.wsgi_app,
#     profile_dir="profiles",
#     restrictions=("olim", ".py"),
# )

# with app.app_context():
#     db.create_all()

from . import active_learning  # noqa
from . import auth  # noqa
from . import cli  # noqa
from . import commands  # noqa
from . import database  # noqa
from . import issue  # noqa
from . import labels  # noqa
from . import project  # noqa
from . import upload_data  # noqa
from .utils.entry import have_hidden  # noqa

# Global variables to templates
app.jinja_env.globals.update(
    have_hidden=have_hidden,
    has_permition=auth.role_has_permission,
    labels_types=LABELS,
    labels_rev=LABELS[::-1],
    labels_array=json.dumps([label_values[0].replace(" ", "_") for label_values in LABELS]),
    has_learner=True,
    version=VERSION,
    has_help=HELP_URL is not None,
    debug=DEBUG,
)
