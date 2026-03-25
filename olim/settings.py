import os
from datetime import timedelta
from pathlib import Path
from typing import ClassVar

from dotenv import load_dotenv

load_dotenv()

VERSION = "0.4.0-rc1"
"""Version of the application"""

ES_INDEX = "dataset-{dataset_id}"
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

DB_URL = os.getenv("DB_URL")

SESSION_TYPE = "sqlalchemy"
SESSION_PERMANENT = True
SESSION_USE_SIGNER = False
PERMANENT_SESSION_LIFETIME = timedelta(days=30)

QUEUES_PATH = Path("/app/queues")

UPLOAD_BATCH_SIZE = 1000

INTERFACE_SETTINGS = {
    "show_apply_to_all": True,
    "show_highlights": True,
    "show_hidden_options": True,
    "show_al": True,
}

WORK_PATH = Path(os.getenv("WORK_FOLDER", "/app/work"))

UPLOAD_PATH = WORK_PATH / "uploads"
CHUNK_SIZE = 5 * 1024 * 1024
ALLOWED_EXTENSIONS = {"csv", "tsv"}
MAX_FILE_SIZE = 10 * 1024 * 1024 * 1024  # 10GB

RANDOM_SEED = os.getenv("RANDOM_SEED", None)

if RANDOM_SEED is not None:
    RANDOM_SEED = int(RANDOM_SEED)

HELP_URL = os.getenv("HELP_URL", "")
"""URL to the API help page"""


class LabelTypes:
    SIM_NAO: ClassVar = [
        ("sim", "icon", "check-circle-fill", "green"),
        ("não", "icon", "x-circle-fill", "red"),
    ]
    SIM_NAO_NS: ClassVar = [
        ("sim", "icon", "check-circle-fill", "green"),
        ("não", "icon", "x-circle-fill", "red"),
        ("não sei", "text", "?", "orange"),
    ]
    YES_NO: ClassVar = [
        ("yes", "icon", "check-circle-fill", "green"),
        ("no", "icon", "x-circle-fill", "red"),
    ]
    CHECK: ClassVar = [
        ("check", "icon", "check-circle-fill", "green"),
    ]
    YES_NO_UNKNOWN: ClassVar = [
        ("yes", "icon", "check-circle-fill", "green"),
        ("no", "icon", "x-circle-fill", "red"),
        ("unknown", "text", "?", "orange"),
    ]
    YES_NO_IDK: ClassVar = [
        ("yes", "icon", "check-circle-fill", "green"),
        ("no", "icon", "x-circle-fill", "red"),
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

# Label types are now configured at the individual label level
# See olim.label_types module for available label types

"""List of endpoints that need a setup backend."""
NEED_LEARNER = [
    "active_learning",
    "create_al",
    "catch_al",
]

"""List of error handler endpoints that should always be allowed."""
ERROR_ENDPOINTS = [
    "bad_request",
    "unauthorized",
    "forbidden",
    "not_found",
    "method_not_allowed",
    "request_timeout",
    "payload_too_large",
    "too_many_requests",
    "internal_server_error",
    "bad_gateway",
    "service_unavailable",
    "gateway_timeout",
    "handle_exception",
    "test_error",
    "test_exception",
]

"""Lists of permited endpoints for each user."""
PERMISSIONS = {
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
        "data_navigation",
        "data_navigation_component",
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
        "redirect_to_project",
        # ML Models Management (UI)
        "models_list",
        "model_detail",
        "model_create",
        "model_train",
        "version_activate",
        "model_link_label",
        "model_unlink_label",
        "model_delete",
        "model_predict",
        # ML Models API (REST)
        "api.health_check",
        "api.get_model_info",
        "api.predict_single",
        "api.predict_batch",
        # Project home (redirects to learning tasks)
        "project_home",
        # Learning Tasks (assigned tasks visible to all users)
        "learning_tasks_list",
        "learning_task_view",
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
