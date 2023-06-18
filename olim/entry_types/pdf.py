from flask import render_template


def render(entry_id, **pars):
    return render_template("entry_types/pdf.html", filename=entry_id, **pars)


def extract_texts(entry_id):
    import pandas as pd

    return pd.DataFrame({"entry_id": [entry_id], "filename": [str(entry_id) + ".pdf"]})
