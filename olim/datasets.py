"""Dataset management: list, edit, delete, add rows or columns, configure columns, edit entries."""

import re
from pathlib import Path
from typing import Any

from flask import abort, flash, jsonify, redirect, render_template, request, session, url_for
from flask_babel import _

from . import app
from .celery_app import launch_task_with_tracking
from .database import (
    Dataset,
    check_entries_exist,
    get_dataset,
    get_dataset_entries_page,
    get_dataset_entry_type,
    get_dataset_stats,
    get_datasets,
    get_projects,
    get_projects_for_dataset,
    set_dataset_projects,
    soft_delete_dataset,
    update_dataset,
)
from .entry_types.flexible_text import current_column_config, normalize_column_config
from .settings import CHUNK_SIZE, ES_INDEX, UPLOAD_PATH
from .tasks.upload_data import (
    add_dataset_columns,
    check_append_columns,
    check_new_columns,
    update_entries,
    upload_dataset,
)
from .upload_data import _validate_csv_options, read_csv_header
from .utils.es import es_fields_with_values, es_search
from .utils.export import cell_text

PAGE_SIZES = (10, 25, 50, 100)
APPENDABLE_TYPES = ("single_text", "flexible_text")
APPEND_MODES = ("rows", "columns")
MAX_SAVE_ENTRIES = 1000


def _get_dataset_or_404(dataset_id: int) -> Dataset:
    dataset = get_dataset(dataset_id)
    if dataset is None:
        abort(404)
    return dataset


def _es_fields(dataset_id: int) -> list[str]:
    """Fields with values in the dataset's index, or an empty list if it can't be read."""
    try:
        return es_fields_with_values(ES_INDEX.format(dataset_id=dataset_id))
    except Exception:
        return []


def dataset_entry_type(dataset: Dataset) -> str:
    """Entry type of a dataset, inferred from its config when it has no entries yet."""
    entry_type = get_dataset_entry_type(dataset.id)
    if entry_type:
        return entry_type
    return "flexible_text" if dataset.column_config else "single_text"


def display_fields(dataset: Dataset, es_fields: list[str] | None = None) -> list[dict[str, str]]:
    """Editable document fields of a dataset, in CSV order when the layout is known.

    Returns:
        List of {"field": ES field name, "label": column name shown to the user}
    """
    fields = [{"field": "text", "label": dataset.text_column or "text"}]
    if dataset.columns and dataset.id_column and dataset.text_column:
        for column in dataset.columns:
            if column in (dataset.id_column, dataset.text_column):
                continue
            # Upload renames a metadata column called "text" to keep the main text
            field = "metadata_text" if column == "text" else column
            fields.append({"field": field, "label": column})
        return fields

    if es_fields is None:
        es_fields = _es_fields(dataset.id)
    for field in sorted(f for f in es_fields if f != "text"):
        fields.append({"field": field, "label": "text" if field == "metadata_text" else field})
    return fields


def existing_columns(dataset: Dataset, es_fields: list[str] | None = None) -> list[str]:
    """Column names already used by the dataset, ID column included when known."""
    labels = [f["label"] for f in display_fields(dataset, es_fields)]
    return [dataset.id_column, *labels] if dataset.id_column else labels


def config_fields(
    dataset: Dataset, column_config: dict, es_fields: list[str] | None = None
) -> list[dict[str, str]]:
    """Columns the column configuration editor offers as extra columns.

    Columns named by the current config are kept even when the dataset doesn't
    list them (e.g. legacy PDF datasets), so saving doesn't drop them.
    """
    fields = display_fields(dataset, es_fields)[1:]
    known = {f["field"] for f in fields}
    for item in column_config.get("extra_columns", []):
        if item.get("column") not in known:
            known.add(item["column"])
            fields.append({"field": item["column"], "label": item["column"]})
    return fields


def resolve_layout(
    dataset: Dataset,
    id_column: str | None,
    text_column: str | None,
    es_fields: list[str] | None = None,
) -> tuple[str, str, list[str]]:
    """Work out which columns an appended file must have.

    Legacy datasets don't store their CSV layout; the user picks the id and
    text columns and the remaining ones are taken from the search index.

    Returns:
        (id_column, text_column, expected_columns)

    Raises:
        ValueError: with a user-facing message if the layout can't be resolved
    """
    if dataset.columns and dataset.id_column and dataset.text_column:
        return dataset.id_column, dataset.text_column, list(dataset.columns)

    if not id_column or not text_column:
        raise ValueError(_("Select the ID and text columns of the file."))
    if id_column == text_column:
        raise ValueError(_("The ID and text columns must be different."))

    if es_fields is None:
        es_fields = _es_fields(dataset.id)
    metadata = ["text" if f == "metadata_text" else f for f in es_fields if f != "text"]
    expected = [id_column, text_column, *sorted(set(metadata) - {id_column, text_column})]
    return id_column, text_column, expected


def _uploaded_file(payload: dict) -> tuple[str, str, str]:
    """Validate the uploaded file reference and CSV options from a request payload.

    Returns:
        (path, sep, encoding)
    """
    file_id = str(payload.get("file_id") or "")
    filename = Path(str(payload.get("filename") or "")).name
    if not re.fullmatch(r"[A-Za-z0-9]+", file_id) or not filename:
        raise ValueError(_("File upload incomplete"))
    sep, encoding = _validate_csv_options(payload.get("sep", ","), payload.get("encoding", "utf-8"))
    path = UPLOAD_PATH / f"{file_id}_{filename}"
    if not path.exists():
        raise ValueError(_("Uploaded file not found. Please try uploading again."))
    return str(path), sep, encoding


def _run_append_validation(dataset: Dataset, payload: dict) -> tuple[dict, dict]:
    """Check a file's columns against a dataset, for new rows or new columns.

    Returns:
        (report, context) where context holds what the append task needs
    """
    mode = payload.get("mode", "rows")
    if mode not in APPEND_MODES:
        raise ValueError(_("Invalid upload mode."))
    path, sep, encoding = _uploaded_file(payload)
    columns = read_csv_header(path, sep, encoding)
    if not columns:
        raise ValueError(_("Could not read the file's columns. Check the separator and encoding."))

    if mode == "columns":
        id_column = payload.get("id_column")
        if not id_column or id_column not in columns:
            raise ValueError(_("Select the ID column of the file."))
        # IDs are checked by the task before anything is written
        report = check_new_columns(columns, id_column, existing_columns(dataset))
        context = {
            "path": path,
            "sep": sep,
            "encoding": encoding,
            "id_column": id_column,
            "new_columns": report["new_columns"],
        }
        return {"mode": mode, **report}, context

    id_column, text_column, expected = resolve_layout(
        dataset, payload.get("id_column"), payload.get("text_column")
    )
    # Legacy datasets get their layout stored once a file matching it is appended
    layout = (
        None
        if dataset.columns
        else {"id_column": id_column, "text_column": text_column, "columns": columns}
    )

    # Only the header is checked here; IDs are checked batch by batch while the data
    # is added, and the upload is undone on the first conflict
    report = {"mode": mode, **check_append_columns(columns, expected)}

    context = {
        "path": path,
        "sep": sep,
        "encoding": encoding,
        "id_column": id_column,
        "text_column": text_column,
        "layout": layout,
    }
    return report, context


@app.route("/datasets")
def datasets() -> ...:
    """List all datasets."""
    all_datasets = get_datasets()
    return render_template(
        "datasets/list.html",
        datasets=all_datasets,
        stats=get_dataset_stats(),
        entry_types={d.id: dataset_entry_type(d) for d in all_datasets},
    )


@app.route("/datasets/new")
def dataset_new() -> ...:
    """Create a dataset from an uploaded file."""
    return render_template(
        "datasets/new.html",
        CHUNK_SIZE=CHUNK_SIZE,
        projects=list(get_projects()),
    )


@app.route("/datasets/<int:dataset_id>", methods=["GET", "POST"])
def dataset_edit(dataset_id: int) -> ...:
    """Edit a dataset's details, append data and edit its entries."""
    dataset = _get_dataset_or_404(dataset_id)

    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        if not name:
            flash(_("Dataset name is required"), "error")
            return redirect(url_for("dataset_edit", dataset_id=dataset_id))
        try:
            project_ids = [int(p) for p in request.form.getlist("projects")]
            update_dataset(dataset_id, name=name)
            set_dataset_projects(dataset_id, project_ids, session["user_id"])
        except Exception as e:
            flash(_("Error updating dataset: {error}").format(error=str(e)), "error")
        else:
            flash(_("Dataset updated successfully"), "success")
        return redirect(url_for("dataset_edit", dataset_id=dataset_id))

    es_fields = _es_fields(dataset_id)
    entry_type = dataset_entry_type(dataset)
    column_config = current_column_config(dataset.column_config, es_fields)
    return render_template(
        "datasets/edit.html",
        dataset=dataset,
        stats=get_dataset_stats().get(dataset_id, {"entry_count": 0, "projects": []}),
        projects=list(get_projects()),
        linked_project_ids={p.id for p in get_projects_for_dataset(dataset_id)},
        entry_type=entry_type,
        can_append=entry_type in APPENDABLE_TYPES,
        is_legacy=not dataset.columns,
        expected_columns=(
            dataset.columns
            if dataset.columns
            else [f["label"] for f in display_fields(dataset, es_fields)[1:]]
        ),
        CHUNK_SIZE=CHUNK_SIZE,
        page_sizes=PAGE_SIZES,
        grid_fields=display_fields(dataset, es_fields),
        column_config=column_config,
        column_config_fields=config_fields(dataset, column_config, es_fields),
    )


@app.route("/datasets/<int:dataset_id>/delete", methods=["POST"])
def dataset_delete(dataset_id: int) -> ...:
    """Soft-delete a dataset."""
    dataset = _get_dataset_or_404(dataset_id)
    soft_delete_dataset(dataset_id, session["user_id"])
    flash(_("Dataset '{name}' deleted").format(name=dataset.name), "success")
    return redirect(url_for("datasets"))


def build_grid_rows(
    entries: list, docs: dict[str, dict], fields: list[dict[str, str]]
) -> list[dict[str, Any]]:
    """Rows for the entries grid: the entry ID plus each field as text.

    Entries missing from the search index are flagged so the grid keeps them
    read-only instead of showing editable blanks.
    """
    rows = []
    for entry in entries:
        doc = docs.get(entry.entry_id)
        row: dict[str, Any] = {"_id": entry.entry_id, "_missing": doc is None}
        for f in fields:
            row[f["field"]] = cell_text(doc.get(f["field"])) if doc else ""
        rows.append(row)
    return rows


@app.route("/datasets/<int:dataset_id>/entries")
def dataset_entries(dataset_id: int) -> ...:
    """One page of the dataset's entries for the editing grid (Tabulator remote pagination).

    Query: page (1-based), size (rows per page). Returns {"last_page", "last_row", "data"}.
    """
    dataset = _get_dataset_or_404(dataset_id)

    size = request.args.get("size", 25, type=int)
    if size not in PAGE_SIZES:
        size = 25
    page = max(request.args.get("page", 1, type=int), 1)

    entries, total = get_dataset_entries_page(dataset_id, (page - 1) * size, size)
    last_page = max((total + size - 1) // size, 1)

    docs: dict[str, dict] = {}
    error = None
    es_fields = None
    if entries:
        ids = [e.entry_id for e in entries]
        try:
            hits = es_search(
                index=ES_INDEX.format(dataset_id=dataset_id),
                query={"ids": {"values": ids}},
                size=len(ids),
            )["hits"]["hits"]
            docs = {hit["_id"]: hit["_source"] for hit in hits}
        except Exception as e:
            error = _("Could not load entries from the search engine: {error}").format(error=str(e))
        if not dataset.columns:
            es_fields = _es_fields(dataset_id)

    return jsonify(
        last_page=last_page,
        last_row=total,
        data=build_grid_rows(entries, docs, display_fields(dataset, es_fields or [])),
        error=error,
    )


@app.route("/datasets/<int:dataset_id>/entries", methods=["POST"])
def dataset_entries_save(dataset_id: int) -> ...:
    """Save edited entry fields. Body: {"changes": {entry_id: {field: value}}}."""
    dataset = _get_dataset_or_404(dataset_id)
    payload = request.get_json(silent=True) or {}
    changes = payload.get("changes")
    if not isinstance(changes, dict) or not changes:
        return jsonify(error=_("No changes to save.")), 400
    if len(changes) > MAX_SAVE_ENTRIES:
        return jsonify(
            error=_("Too many entries changed at once (maximum {max}).").format(
                max=MAX_SAVE_ENTRIES
            )
        ), 400

    allowed = {f["field"] for f in display_fields(dataset)}
    clean: dict[str, dict[str, Any]] = {}
    for entry_id, fields in changes.items():
        if not isinstance(fields, dict):
            return jsonify(error=_("Invalid change format.")), 400
        unknown = set(fields) - allowed
        if unknown:
            return jsonify(
                error=_("These fields can't be edited: {fields}").format(
                    fields=", ".join(sorted(unknown))
                )
            ), 400
        clean[str(entry_id)] = {
            # An emptied metadata cell removes the value, like empty cells on upload
            field: (None if field != "text" and value in ("", None) else str(value or ""))
            for field, value in fields.items()
        }

    _existing, missing = check_entries_exist(list(clean), dataset_id)
    if missing:
        return jsonify(
            error=_("These entries don't belong to this dataset: {ids}").format(
                ids=", ".join(missing[:20])
            )
        ), 400

    try:
        failed = update_entries(dataset_id, clean)
    except Exception as e:
        return jsonify(error=_("Could not save changes: {error}").format(error=str(e))), 500

    return jsonify(
        success=not failed,
        saved=len(clean) - len(failed),
        failed=failed,
    ), (200 if not failed else 207)


@app.route("/datasets/<int:dataset_id>/columns", methods=["POST"])
def dataset_columns_save(dataset_id: int) -> ...:
    """Save how a flexible text dataset displays its columns. Body: {"column_config": {...}}."""
    dataset = _get_dataset_or_404(dataset_id)
    if dataset_entry_type(dataset) != "flexible_text":
        return jsonify(error=_("Column display options are only available for Flexible Text.")), 400

    es_fields = _es_fields(dataset_id)
    current = current_column_config(dataset.column_config, es_fields)
    allowed = [f["field"] for f in config_fields(dataset, current, es_fields)]
    payload = request.get_json(silent=True) or {}
    try:
        column_config = normalize_column_config(payload.get("column_config"), allowed)
        update_dataset(dataset_id, column_config=column_config)
    except ValueError as e:
        return jsonify(error=str(e)), 400
    return jsonify(success=True, column_config=column_config)


@app.route("/datasets/<int:dataset_id>/append/validate", methods=["POST"])
def dataset_append_validate(dataset_id: int) -> ...:
    """Check an uploaded file of new rows or new columns against the dataset."""
    dataset = _get_dataset_or_404(dataset_id)
    try:
        report, _context = _run_append_validation(dataset, request.get_json(silent=True) or {})
    except ValueError as e:
        return jsonify(error=str(e)), 400
    except Exception as e:
        return jsonify(error=_("Validation failed: {error}").format(error=str(e))), 500
    return jsonify(report)


@app.route("/datasets/<int:dataset_id>/append", methods=["POST"])
def dataset_append(dataset_id: int) -> ...:
    """Validate the uploaded file again and start adding its rows or columns to the dataset."""
    dataset = _get_dataset_or_404(dataset_id)
    entry_type = dataset_entry_type(dataset)
    if entry_type not in APPENDABLE_TYPES:
        return jsonify(error=_("Adding data is not supported for this data format.")), 400

    try:
        report, context = _run_append_validation(dataset, request.get_json(silent=True) or {})
    except ValueError as e:
        return jsonify(error=str(e)), 400
    except Exception as e:
        return jsonify(error=_("Validation failed: {error}").format(error=str(e))), 500

    if not report["ok"]:
        return jsonify(report), 409

    if report["mode"] == "columns":
        try:
            launch_task_with_tracking(
                add_dataset_columns,
                description=_("Adding columns to dataset {name}").format(name=dataset.name),
                dataset_id=dataset_id,
                filename=context["path"],
                id_column=context["id_column"],
                new_columns=context["new_columns"],
                sep=context["sep"],
                encoding=context["encoding"],
                user_id=session["user_id"],
                track_progress=True,
            )
        except Exception as e:
            return jsonify(error=_("Error starting upload: {error}").format(error=str(e))), 500
        flash(_("Adding columns started. They will appear when processing finishes."), "success")
        return jsonify(report)

    try:
        launch_task_with_tracking(
            upload_dataset,
            description=_("Adding data to dataset {name}").format(name=dataset.name),
            upload_type=entry_type,
            upload_params={
                "filename": context["path"],
                "id_column": context["id_column"],
                "text_column": context["text_column"],
                "sep": context["sep"],
                "encoding": context["encoding"],
            },
            dataset_id=dataset_id,
            append=True,
            dataset_layout=context["layout"],
            user_id=session["user_id"],
            track_progress=True,
        )
    except Exception as e:
        return jsonify(error=_("Error starting upload: {error}").format(error=str(e))), 500

    flash(
        _("Adding data started. The new entries will appear when processing finishes."), "success"
    )
    return jsonify(report)
