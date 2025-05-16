import os
from datetime import timedelta
from typing import ClassVar

VERSION = "0.2.0-dev"
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

DB_HOST = os.getenv("DB_HOST")
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_PORT = os.getenv("DB_PORT", "5432")

SESSION_TYPE = "sqlalchemy"
SESSION_PERMANENT = True
SESSION_USE_SIGNER = False
PERMANENT_SESSION_LIFETIME = timedelta(days=30)

QUEUES_PATH = "./queues"

LEARNER_URL = os.getenv("LEARNER_URL", None)
LEARNER_KEY = os.getenv("LEARNER_KEY", None)

HAS_LEARNER = not (LEARNER_URL in [None, ""] or LEARNER_KEY in [None, ""])

HELP_URL = os.getenv("HELP_URL", "")
"""URL to the API help page"""


class LabelTypes:
    SIM_NAO: ClassVar = [
        ("sim", "icon", "check", "green"),
        ("não", "icon", "clear", "red"),
    ]
    SIM_NAO_NS: ClassVar = [
        ("sim", "icon", "check", "green"),
        ("não", "icon", "clear", "red"),
        ("não sei", "text", "?", "orange"),
    ]
    YES_NO: ClassVar = [
        ("yes", "icon", "check", "green"),
        ("no", "icon", "clear", "red"),
    ]
    CHECK: ClassVar = [
        ("check", "icon", "check", "green"),
    ]
    YES_NO_UNKNOWN: ClassVar = [
        ("yes", "icon", "check", "green"),
        ("no", "icon", "clear", "red"),
        ("unknown", "text", "?", "orange"),
    ]
    YES_NO_IDK: ClassVar = [
        ("yes", "icon", "check", "green"),
        ("no", "icon", "clear", "red"),
        ("don't know", "text", "?", "orange"),
    ]


labels = os.getenv("LABELS", "LabelTypes.YES_NO")
if "LABELS_TYPES" in labels:
    labels = labels.replace("LABELS_TYPES", "LabelTypes")
    print("WARNING: LABELS_TYPES is deprecated, replace it with LabelTypes!")
try:
    LABELS = eval(labels)
except (TypeError, NameError):
    print(f"WARNING: Failed to parse LABELS={labels}, continuing with default 'LabelTypes.YES_NO'!")
    LABELS = LabelTypes.YES_NO

"""List of endpoints that need a setup backend."""
NEED_LEARNER = [
    "active_learning",
    "create_al",
    "catch_al",
]

"""Lists of permited endpoints for each user."""
PERMISSIONS = {
    "admin": [
        "static",
        "login",
        "init_config",
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
        "queue",
        "catch_queue",
        "search",
        "user_settings",
        "edit_password",
        "edit_language",
        "logout",
        "active_learning",
        "create_al",
        "catch_al",
        "upload_data",
        "check_task_status",
        "sync_label",
        "export_label",
        "get_help",
        "send_ticket",
        "projects",
        "delete_project",
        "create_project",
        "redirect_to_project",
        "print_session",
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
        "queue",
        "catch_queue",
        "search",
        "user_settings",
        "edit_password",
        "edit_language",
        "logout",
        "active_learning",
        "create_al",
        "catch_al",
        "export_label",
        "get_help",
        "send_ticket",
        "projects",
        "redirect_to_project",
    ],
    "guest": ["static", "login"],
}
"""Mapping of permissions to routes that can be accessed by roles"""


LANGUAGES = {
    "pt_BR": "Português (Brasil)",
    "en_US": "English (United States)",
}

BABEL_DEFAULT_LOCALE = "pt_BR"
BABEL_TRANSLATION_DIRECTORIES = "/app/olim/translations"
