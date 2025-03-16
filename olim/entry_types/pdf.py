import pandas as pd
from flask import render_template


def render(entry_id, **pars) -> str:
    return render_template("entry_types/pdf.html", filename=entry_id, **pars)


def extract_texts(entry_id) -> pd.DataFrame:
    return pd.DataFrame({"entry_id": [entry_id], "filename": [str(entry_id) + ".pdf"]})
