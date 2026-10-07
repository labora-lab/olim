import io
import json
import re
import secrets
import time

import pandas as pd
from flask import (
    Response,
    flash,
    make_response,
    redirect,
    render_template,
    request,
    session,
    stream_with_context,
    url_for,
)
from flask_babel import _

from . import app, db, entry_types
from .database import (
    CeleryTask,
    del_label,
    get_dataset,
    get_datasets,
    get_label,
    get_labeled,
    get_labels,
    get_project,
    is_label_isolation_enabled,
    new_label,
)
from .label_types import (
    get_label_type_module,
    get_preset_settings,
    is_free_text_label,
    is_open_label,
    parse_label_value,
)
from .project import update_session_project
from .settings import UPLOAD_PATH
from .utils.export import export_csv
from .utils.label import label_upload, new_label_names, suggest_label_config
from .utils.queues import store_queue

LABEL_UPLOAD_PATH = UPLOAD_PATH / "label-uploads"


@app.route("/<int:project_id>", methods=["GET"])
def project_home(project_id: int) -> ...:
    return redirect(url_for("learning_tasks_list", project_id=project_id))


def _value_counts(label) -> dict:
    """Count a label's annotated entries, per option for choice labels.

    A multi-select entry counts once toward each option it selected, so the
    option counts can add up to more than the total of annotated entries.
    """
    entries = [e for e in label.entries if not e.is_deleted]
    if is_free_text_label(label.label_type):
        total = sum(1 for e in entries if e.value and str(e.value).strip())
        return {"total": total, "options": None}

    # Seed with the declared options so an option nobody picked yet still shows
    # a zero. An unconfigured multiple_choice label only reports placeholders.
    options: dict[str, int] = {}
    settings = label.label_settings or {}
    if not is_open_label(label.label_type) or settings.get("options"):
        for opt in get_label_type_module(label.label_type).get_label_options(label):
            options[str(opt[0])] = 0

    total = 0
    for entry in entries:
        selected = parse_label_value(entry.value)
        if not selected:
            continue
        total += 1
        for value in selected:
            options[value] = options.get(value, 0) + 1
    return {"total": total, "options": options}


@app.route("/<int:project_id>/labels", methods=["GET"])
def labels(project_id: int) -> ...:
    # Check project_id and require data
    res = update_session_project(project_id, require_data=True)
    if res is not None:
        return res

    labels = get_labels(project_id)
    labels_values = {label.id: _value_counts(label) for label in labels}
    datasets = list(get_datasets(project_id, non_empty=True))
    return render_template(
        "labels.html",
        labels=labels,
        values=labels_values,
        datasets=datasets,
    )


@app.route("/<int:project_id>/labels/new", methods=["POST"])
def create_label(project_id: int) -> ...:
    # Check project_id
    res = update_session_project(project_id)
    if res is not None:
        return res

    label_name = request.form.get("label")
    label_type = request.form.get("label_type") or None
    label_settings = None

    if label_type == "multiple_choice":
        raw = request.form.get("label_settings", "").strip()
        if raw:
            try:
                label_settings = json.loads(raw)
            except json.JSONDecodeError:
                pass
    elif label_type:
        label_settings = get_preset_settings(label_type)

    label = new_label(
        label_name,
        session["user_id"],
        project_id,
        label_type=label_type,
        label_settings=label_settings,
    )
    flash(
        _("Label {label_name} successfully created").format(label_name=label.name),
        category="success",
    )

    return redirect(url_for("labels", project_id=project_id))


@app.route("/<int:project_id>/labels/export-all", methods=["GET"])
def export_all_labels(project_id: int) -> ...:
    """Download every entry with its original columns plus one column per label.

    Query: dataset_id=<id> for one dataset, or "all" (default) for every dataset of
    the project.
    """
    res = update_session_project(project_id)
    if res is not None:
        return res

    project_datasets = list(get_datasets(project_id))
    choice = request.args.get("dataset_id", "all")
    if choice == "all":
        selected = project_datasets
        suffix = "all"
    else:
        selected = [d for d in project_datasets if str(d.id) == choice]
        if not selected:
            flash(_("Invalid dataset selection"), category="warning")
            return redirect(url_for("labels", project_id=project_id))
        suffix = selected[0].name
    if not selected:
        flash(_("No datasets available for this project"), category="warning")
        return redirect(url_for("labels", project_id=project_id))

    project = get_project(project_id)
    filename = re.sub(r"[^\w.-]+", "_", f"{project.name if project else 'labels'}-{suffix}")
    return Response(
        stream_with_context(
            export_csv(
                selected,
                list(get_labels(project_id)),
                per_user=is_label_isolation_enabled(),
            )
        ),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}.csv"},
    )


@app.route("/<int:project_id>/labels/quick_create", methods=["POST"])
def quick_create_label(project_id: int) -> ...:
    """Create a label from the inline "New label" affordance on a task setup screen.

    Returns the refreshed label_selector component (not a redirect) so the setup
    form the user was filling in stays exactly where it was, with the new label
    already selected alongside whatever was checked before.
    """
    res = update_session_project(project_id)
    if res is not None:
        return res

    field_name = request.form.get("_selector_field", "labels")
    mode = request.form.get("_selector_mode", "multi")
    component_id = request.form.get("_selector_id") or f"{field_name}-selector"
    label_text = request.form.get("_selector_label_text") or None
    help_text = request.form.get("_selector_help_text") or None
    required = bool(request.form.get("_selector_required"))
    accent = request.form.get("_selector_accent") or "teal"
    checkbox_class = request.form.get("_selector_checkbox_class") or ""

    name = request.form.get("_new_label_name", "").strip()
    label_type = request.form.get("_new_label_type") or None
    error = None
    new_id = None
    toast = None
    if not name:
        error = _("Enter a name for the new label.")
    else:
        label_settings = get_preset_settings(label_type) if label_type else None
        label = new_label(
            name,
            session["user_id"],
            project_id,
            label_type=label_type,
            label_settings=label_settings,
        )
        new_id = label.id
        toast = _("Label {label_name} successfully created").format(label_name=label.name)

    selected_ids = {int(value) for value in request.form.getlist(field_name) if value.strip()}
    if new_id is not None:
        selected_ids.add(new_id)

    body = render_template(
        "macros/_label_selector_response.html",
        field_name=field_name,
        labels=get_labels(project_id),
        selected_ids=selected_ids,
        project_id=project_id,
        mode=mode,
        label_text=label_text,
        help_text=help_text,
        required=required,
        component_id=component_id,
        error=error,
        accent=accent,
        checkbox_class=checkbox_class,
    )
    # This response swaps only the selector component, not the full page, so a
    # flash() message would sit unseen in the session until the next full render —
    # the same HX-Trigger toast the task wizard's own error path already uses.
    resp = make_response(body)
    if toast:
        resp.headers["HX-Trigger"] = json.dumps(
            {"showFlash": [{"message": toast, "category": "success"}]}
        )
    return resp


@app.route("/labels/<int:label_id>/delete", methods=["GET"])
def delete_label(label_id: int) -> ...:
    label = get_label(label_id)
    if label is None:
        flash(
            _("Label id: {label_id} not found!").format(label_id=label_id),
            category="warning",
        )
        return redirect("/")

    # Check project_id
    res = update_session_project(label.project_id)
    if res is not None:
        return res

    label = del_label(label_id, session["user_id"])
    flash(
        _("Label {label_name} sucessfully deleted").format(label_name=label.name),
        category="success",
    )
    return redirect(url_for("labels", project_id=label.project_id))


@app.route("/labels/<label_id>/csv")
def extract_labels(label_id: int) -> ...:
    label = get_label(label_id)
    if label is None:
        flash(
            _("Label id: {label_id} not found!").format(label_id=label_id),
            category="warning",
        )
        return redirect("/")
    project_id = label.project_id

    # Check project_id
    res = update_session_project(project_id)
    if res is not None:
        return res
    if label is None:
        flash(_("Label not found"), category="error")
        return redirect(url_for("labels", project_id=project_id))

    label_str = label.name
    df = pd.read_sql(get_labeled(label_id), db.engine)

    # Replace __llm__ username with llm:<model_name> using stored metadata
    def _resolve_creator(row: pd.Series) -> str:
        if row["created_by"] == "__llm__":
            meta = row.get("label_metadata") or {}
            if isinstance(meta, str):
                try:
                    meta = json.loads(meta)
                except Exception:
                    meta = {}
            return f"llm:{meta.get('model', 'llm')}"
        return str(row["created_by"])

    df["created_by"] = df.apply(_resolve_creator, axis=1)
    df = df.drop(columns=["label_metadata"])

    # One row per value (every user's when values are isolated); fetch each entry's
    # texts once, or entries labelled by several users would be repeated in the merge
    dfs_entries = []
    seen_entries = set()
    for le in label.entries:
        if le.is_deleted or le.entry.id in seen_entries:
            continue
        seen_entries.add(le.entry.id)
        module = getattr(entry_types, le.entry.type)
        dfs_entries.append(module.extract_texts(le.entry.entry_id, le.entry.dataset.id))
    if dfs_entries:
        df = df.merge(pd.concat(dfs_entries, ignore_index=True), how="left", on="entry_id")
    return Response(
        df.to_csv(index=False),
        mimetype="text/csv",
        headers={"Content-disposition": f"attachment; filename={label_str}.csv"},
    )


@app.route("/labels/<label_id>/json")
def extract_labels_json(label_id: int) -> ...:
    label = get_label(label_id)
    if label is None:
        flash(
            _("Label id: {label_id} not found!").format(label_id=label_id),
            category="warning",
        )
        return redirect("/")
    project_id = label.project_id

    # Check project_id
    res = update_session_project(project_id)
    if res is not None:
        return res
    if label is None:
        flash(_("Label not found"), category="error")
        return redirect(url_for("labels", project_id=project_id))
    label_str = label.name
    entries_values = {}
    for le in label.entries:
        if not le.is_deleted:
            entries_values[(le.entry.dataset.name, le.entry.entry_id)] = le.value
    return Response(
        json.dumps(entries_values),
        mimetype="text/json",
        headers={"Content-disposition": f"attachment; filename={label_str}.json"},
    )


@app.route("/labels/<int:label_id>/queue", methods=["GET"])
def catch_queue(label_id: int) -> ...:
    label = get_label(label_id)
    if label is None:
        flash(
            _("Label id: {label_id} not found!").format(label_id=label_id),
            category="warning",
        )
        return redirect("/")
    project_id = label.project_id

    # Check project_id
    res = update_session_project(project_id)
    if res is not None:
        return res
    if label is None:
        flash(_("Label not found"), category="error")
        return redirect(url_for("labels", project_id=project_id))
    queue = [
        (label.entry.dataset_id, label.entry.entry_id)
        for label in label.entries
        if not label.is_deleted and label.value
    ]
    # Create queue with label name
    queue_name = _("Label: {label_name}").format(label_name=label.name)
    queue_id = store_queue(queue, project_id, name=queue_name)
    # Redirect to queue
    return redirect(url_for("entry", project_id=project_id, queue_id=queue_id))


@app.route("/labels/<int:label_id>/settings", methods=["GET"])
def label_settings(label_id: int) -> ...:
    label = get_label(label_id)
    if label is None:
        flash(
            _("Label id: {label_id} not found!").format(label_id=label_id),
            category="warning",
        )
        return redirect("/")
    project_id = label.project_id

    export_tasks = CeleryTask.query.filter_by(task_name="learner.export_predictions").all()[::-1]

    # Check project_id
    res = update_session_project(project_id)
    if res is not None:
        return res
    if label is None:
        flash(_("Label not found"), category="error")
        return redirect(url_for("labels", project_id=project_id))
    return render_template("label-settings.html", label=label, export_tasks=export_tasks)


@app.route("/label/<int:label_id>/update-learner-parameters", methods=["POST"])
def update_learner_parameters(label_id: int) -> ...:
    """Update learner parameters for a label"""
    # Check admin role
    if session.get("role") != "admin":
        flash(_("Admin access required"), category="error")
        return redirect(url_for("label_settings", label_id=label_id))

    label = get_label(label_id)
    if label is None:
        flash(_("Label not found"), category="error")
        return redirect("/")

    try:
        # Get form data
        param_names = request.form.getlist("param_names[]")
        param_types = request.form.getlist("param_types[]")
        param_values = request.form.getlist("param_values[]")
        param_is_list = request.form.getlist("param_is_list[]")

        # Convert form data to parameters dictionary
        parameters = {}

        for i, name in enumerate(param_names):
            if not name.strip():  # Skip empty names
                continue

            if i >= len(param_types) or i >= len(param_values):
                continue

            base_type = param_types[i]
            value_str = param_values[i]
            is_list = str(i + 1) in param_is_list  # Check if checkbox was checked

            # Type conversion function
            def convert_value(val_str: str, val_type: str) -> ...:
                val_str = val_str.strip()
                if val_type == "int":
                    return int(val_str)
                elif val_type == "float":
                    return float(val_str)
                elif val_type == "bool":
                    return val_str.lower() in ("true", "1", "yes", "on")
                else:  # str
                    return val_str

            # Process value based on whether it's a list or single value
            if is_list:
                # Split by comma and convert each value
                if value_str.strip():
                    list_values = [v.strip() for v in value_str.split(",") if v.strip()]
                    parameters[name] = [convert_value(v, base_type) for v in list_values]
                else:
                    parameters[name] = []
            else:
                # Single value - always store the parameter, even if empty
                parameters[name] = convert_value(value_str, base_type) if value_str.strip() else ""

        # Update label with new parameters
        label.learner_parameters = parameters if parameters else None
        db.session.commit()

        flash(_("Learner parameters updated successfully"), category="success")

    except ValueError as e:
        flash(
            _("Error converting parameter values: {error}").format(error=str(e)),
            category="error",
        )
    except Exception as e:
        flash(
            _("Error updating parameters: {error}").format(error=str(e)),
            category="error",
        )

    return redirect(url_for("label_settings", label_id=label_id))


@app.route("/label/<int:label_id>/upload-auto-labels", methods=["POST"])
def upload_auto_labels(label_id: int) -> ...:
    """Upload and process auto-labels CSV file"""
    # Check admin role
    if session.get("role") != "admin":
        flash(_("Admin access required"), category="error")
        return redirect(url_for("label_settings", label_id=label_id))

    label = get_label(label_id)
    if label is None:
        flash(_("Label not found"), category="error")
        return redirect("/")

    if "auto_label_file" not in request.files:
        flash(_("No file selected"), category="error")
        return redirect(url_for("label_settings", label_id=label_id))

    file = request.files["auto_label_file"]
    if file.filename == "":
        flash(_("No file selected"), category="error")
        return redirect(url_for("label_settings", label_id=label_id))

    try:
        # Read CSV file
        df = pd.read_csv(file.stream)

        # Validate required columns
        required_columns = {"dataset_id", "entry_id", "value"}
        if not required_columns.issubset(df.columns):
            missing = required_columns - set(df.columns)
            flash(
                _("Missing required columns: {columns}").format(columns=", ".join(missing)),
                category="error",
            )
            return redirect(url_for("label_settings", label_id=label_id))

        # Convert to {COMPOSITE_ID: value} format
        new_auto_labels = {}
        from .tasks.active_learning import COMPOSITE_ID

        for __, row in df.iterrows():
            composite_id = COMPOSITE_ID.format(
                dataset_id=int(row["dataset_id"]), entry_id=row["entry_id"]
            )
            new_auto_labels[composite_id] = str(row["value"])

        # Merge with existing auto-labels if they exist
        existing_auto_labels = label.auto_labels if label.auto_labels else {}
        merged_auto_labels = {**existing_auto_labels, **new_auto_labels}

        # Update label with merged auto-labels
        label.auto_labels = merged_auto_labels
        db.session.commit()

        flash(
            _("Successfully uploaded {count} auto-labels").format(count=len(new_auto_labels)),
            category="success",
        )

    except Exception as e:
        flash(_("Error processing file: {error}").format(error=str(e)), category="error")

    return redirect(url_for("label_settings", label_id=label_id))


@app.route("/label/<int:label_id>/update-type-settings", methods=["POST"])
def update_label_type_settings(label_id: int) -> ...:
    """Update the label_settings JSON for a configurable label type."""
    if session.get("role") != "admin":
        flash(_("Admin access required"), category="error")
        return redirect(url_for("label_settings", label_id=label_id))

    label = get_label(label_id)
    if label is None:
        flash(_("Label not found"), category="error")
        return redirect("/")

    raw = request.form.get("label_settings", "").strip()
    if raw:
        try:
            label.label_settings = json.loads(raw)
            db.session.commit()
            flash(_("Label settings updated successfully"), category="success")
        except json.JSONDecodeError:
            flash(_("Invalid settings format"), category="error")
    else:
        flash(_("No settings provided"), category="warning")

    return redirect(url_for("label_settings", label_id=label_id))


@app.route("/<int:project_id>/label-upload", methods=["POST"])
def label_up(project_id: int) -> ...:
    # Check project_id
    res = update_session_project(project_id)
    if res is not None:
        return res

    # Get datasets for this project
    datasets = list(get_datasets(project_id))
    if not datasets:
        flash(_("No datasets available for this project"), category="warning")
        return redirect(url_for("labels", project_id=project_id))

    # Handle dataset selection
    if len(datasets) == 1:
        # Auto-select if only one dataset
        dataset_id = datasets[0].id
    else:
        # Multiple datasets - require selection
        dataset_id = request.form.get("dataset_id")
        if not dataset_id:
            flash(_("Dataset selection required"), category="warning")
            return redirect(url_for("labels", project_id=project_id))

    # Verify dataset exists and is valid
    try:
        dataset_id = int(dataset_id)
        dataset = get_dataset(dataset_id)
        if not dataset or dataset not in datasets:
            flash(_("Invalid dataset selection"), category="warning")
            return redirect(url_for("labels", project_id=project_id))
    except (ValueError, TypeError):
        flash(_("Invalid dataset selection"), category="warning")
        return redirect(url_for("labels", project_id=project_id))

    # Create a df from csv passed by POST; read as text so IDs like "007" stay intact
    try:
        df = read_label_file(request.files["file"].read())
    except (KeyError, ValueError) as e:
        flash(_("Could not read the labelling file: {error}").format(error=str(e)), "error")
        return redirect(url_for("labels", project_id=project_id))

    # Labels the file introduces are configured by the user before uploading
    if new_label_names(df, project_id):
        token = secrets.token_hex(12)
        LABEL_UPLOAD_PATH.mkdir(parents=True, exist_ok=True)
        df.to_csv(LABEL_UPLOAD_PATH / f"{token}.csv", index=False)
        (LABEL_UPLOAD_PATH / f"{token}.json").write_text(
            json.dumps({"project_id": project_id, "dataset_id": dataset.id})
        )
        return redirect(url_for("label_upload_configure", project_id=project_id, token=token))

    label_upload(df, session["user_id"], project_id, dataset.id)

    # Wait 1 seconds for write operations to finish and redirect back to labels page
    time.sleep(1)
    return redirect(url_for("labels", project_id=project_id))

    label_upload(df, session["user_id"], project_id, dataset.id)

    # Wait 1 seconds for write operations to finish and redirect back to labels page
    time.sleep(1)
    return redirect(url_for("labels", project_id=project_id))


def read_label_file(content: bytes) -> pd.DataFrame:
    """Read a labelling CSV as text, accepting UTF-8 (with or without BOM) or CP1252."""
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = content.decode("cp1252")
    return pd.read_csv(io.StringIO(text), dtype=str)


def _pending_label_upload(project_id: int, token: str) -> tuple[pd.DataFrame, dict] | None:
    """Load a labelling file waiting for its new labels to be configured."""
    if not re.fullmatch(r"[0-9a-f]{24}", token):
        return None
    csv_path = LABEL_UPLOAD_PATH / f"{token}.csv"
    meta_path = LABEL_UPLOAD_PATH / f"{token}.json"
    if not csv_path.exists() or not meta_path.exists():
        return None
    meta = json.loads(meta_path.read_text())
    if meta.get("project_id") != project_id:
        return None
    return pd.read_csv(csv_path, dtype=str, keep_default_na=False, na_values=[""]), meta


def _discard_label_upload(token: str) -> None:
    for suffix in (".csv", ".json"):
        (LABEL_UPLOAD_PATH / f"{token}{suffix}").unlink(missing_ok=True)


def _new_label_form(index: int, name: str, df: pd.DataFrame) -> dict:
    """Form data for one new label, with options pre-filled from the file."""
    suggestion = suggest_label_config(df, name)
    return {
        "index": index,
        "name": name,
        **suggestion,
        "settings": {
            "options": [
                {"value": v, "color": "blue", "type": "text", "icon": "", "helper": ""}
                for v in suggestion["options"]
            ],
            "single_select": not suggestion["multi_select"],
            "items_per_line": 2,
        },
    }


@app.route("/<int:project_id>/label-upload/<token>", methods=["GET", "POST"])
def label_upload_configure(project_id: int, token: str) -> ...:
    """Let the user choose type and settings for labels a labelling file introduces."""
    res = update_session_project(project_id)
    if res is not None:
        return res

    pending = _pending_label_upload(project_id, token)
    if pending is None:
        flash(_("This label upload has expired. Please upload the file again."), "warning")
        return redirect(url_for("labels", project_id=project_id))
    df, meta = pending
    names = new_label_names(df, project_id)

    if request.method == "GET":
        return render_template(
            "label-upload-configure.html",
            project_id=project_id,
            token=token,
            new_labels=[_new_label_form(i, name, df) for i, name in enumerate(names)],
            dataset=get_dataset(meta["dataset_id"]),
        )

    if request.form.get("action") == "cancel":
        _discard_label_upload(token)
        flash(_("Label upload cancelled"), "info")
        return redirect(url_for("labels", project_id=project_id))

    skipped = []
    for i in range(int(request.form.get("count", 0))):
        name = request.form.get(f"name_{i}", "")
        if name not in names:
            continue  # Created meanwhile, or not part of this file
        label_type = request.form.get(f"type_{i}") or None
        if label_type is None:
            skipped.append(name)
            continue
        label_settings = None
        if label_type == "multiple_choice":
            try:
                label_settings = json.loads(request.form.get(f"settings_{i}") or "null")
            except json.JSONDecodeError:
                label_settings = None
            if not label_settings or not label_settings.get("options"):
                flash(_("Add at least one option to the label {name}.").format(name=name), "error")
                return redirect(
                    url_for("label_upload_configure", project_id=project_id, token=token)
                )
        else:
            label_settings = get_preset_settings(label_type)
        new_label(
            name,
            session["user_id"],
            project_id,
            label_type=label_type,
            label_settings=label_settings,
        )

    if skipped:
        df = df.loc[~df["label"].astype(str).str.strip().isin(skipped)]
        flash(
            _("Rows of these labels were not uploaded: {names}").format(names=", ".join(skipped)),
            "info",
        )

    label_upload(df, session["user_id"], project_id, meta["dataset_id"])
    _discard_label_upload(token)
    return redirect(url_for("labels", project_id=project_id))
