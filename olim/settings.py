import os

ES_INDEX = "patients-texts"
"""Elasticserach index to load patient data"""

ES_LABEL_INDEX = "labels"
"""Elasticserach index to load labels names"""

ES_TO_HIDE_INDEX = "hidden-texts"
"""Elasticserach index to store texts to hide everywhere"""

ES_SERVER = os.getenv("ES_SERVER")
if ES_SERVER == "":
    ES_SERVER = "http://rotulador_es:9200/"

debug = os.getenv("DEBUG")
debug = debug or "false"
DEBUG = debug.lower() == "true"
SECRET_KEY = os.getenv("SECRET_KEY")

DB_PATH = os.path.join(os.getcwd(), "database.sqlite")
"""Database Sqlite3 path"""

PERMISSIONS = {
    "admin": ["static", "login", "users", "commands", "hidden", "labels", "patient", "new_queue", "/", "search"],
    "user": ["static", "login", "commands", "hidden", "labels", "patient", "new_queue", "/", "search"],
    "guest": ["static", "login"]
}
"""Mapping of permissions to routes that can be accessed by roles"""