from flask import render_template


def render(entry_id, **pars):
    return render_template("entry_types/pdf.html", filename=entry_id, **pars)
