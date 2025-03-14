import os

VERSION = "0.1.0"
"""Version of the application"""

ES_INDEX = "patients-texts"
"""Elasticserach index to load patient data"""

ES_LABEL_INDEX = "labels"
"""Elasticserach index to load labels names"""

ES_TO_HIDE_INDEX = "hidden-texts"
"""Elasticserach index to store texts to hide everywhere"""

ES_SERVER = os.getenv("ES_SERVER")
if ES_SERVER == "":
    ES_SERVER = "http://localhost:9200/"

debug = os.getenv("DEBUG")
debug = debug or "false"
DEBUG = debug.lower() == "true"
SECRET_KEY = os.getenv("SECRET_KEY", "6DUUwdKqwkaXPvjqCS4y")

DB_PATH = os.path.join(os.getcwd(), "database.sqlite")
"""Database Sqlite3 path"""

LEARNER_URL = os.getenv("LEARNER_URL", None)
LEARNER_KEY = os.getenv("LEARNER_KEY", None)

HELP_URL = os.getenv("HELP_URL", None)
"""URL to the API help page"""


class LABELS_TYPES:
    SIM_NAO = [
        ("sim", "icon", "check", "green"),
        ("não", "icon", "clear", "red"),
    ]
    SIM_NAO_NS = [
        ("sim", "icon", "check", "green"),
        ("não", "icon", "clear", "red"),
        ("não sei", "text", "?", "orange"),
    ]
    YES_NO = [
        ("yes", "icon", "check", "green"),
        ("no", "icon", "clear", "red"),
    ]
    CHECK = [
        ("check", "icon", "check", "green"),
    ]
    YES_NO_UNKNOWN = [
        ("yes", "icon", "check", "green"),
        ("no", "icon", "clear", "red"),
        ("unknown", "text", "?", "orange"),
    ]
    YES_NO_IDK = [
        ("yes", "icon", "check", "green"),
        ("no", "icon", "clear", "red"),
        ("don't know", "text", "?", "orange"),
    ]


labels = os.getenv("LABELS")
try:
    LABELS = eval(labels)
except TypeError:
    LABELS = LABELS_TYPES.SIM_NAO_NS

"""List of endpoints that need a setup backend."""
NEED_BACKEND = [
    "active_learning",
    "create_al",
    "catch_al",
]

"""Lists of permited endpoints for each user."""
PERMISSIONS = {
    "admin": [
        "static",
        "login",
        "users",
        "commands",
        "hidden",
        "labels",
        "create_label",
        "delete_label",
        "extract_labels",
        "extract_labels_json",
        "label_settings",
        "label_up",
        "entry",
        "new_queue",
        "catch_queue",
        "/",
        "search",
        "edit_password",
        "logout",
        "active_learning",
        "create_al",
        "catch_al",
        "upload_data",
        "sync_label",
        "export_label",
        "get_help",
        "send_ticket"
    ],
    "user": [
        "static",
        "login",
        "commands",
        "hidden",
        "labels",
        "create_label",
        "delete_label",
        "entry",
        "new_queue",
        "catch_queue",
        "/",
        "search",
        "edit_password",
        "logout",
        "active_learning",
        "create_al",
        "catch_al",
        "export_label",
        "get_help",
        "send_ticket"
    ],
    "guest": ["static", "login", "init_config"],
}
"""Mapping of permissions to routes that can be accessed by roles"""


LANGUAGES = {
    "pt_BR": "Português (Brasil)",
    "en_US": "English (United States)",
}

BABEL_DEFAULT_LOCALE = "pt_BR"
BABEL_TRANSLATION_DIRECTORIES = "/app/olim/translations"
