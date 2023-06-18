ES_INDEX = "patients_index"
ES_TO_HIDE_INDEX = "patients_hidden_texts"
ENTRY_TYPE = "patient"

from .commands import COMMANDS
from .render import render
from .search import search
from .upload import up_patients
from .extract import extract_texts
from .hidden import have_hidden, get_all_hidden
