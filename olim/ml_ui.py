from flask import (
    Response as FlaskResponse,
    abort,
    flash,
    make_response,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_babel import _
from werkzeug.wrappers.response import Response

from . import app
from .celery_app import launch_task_with_tracking
from .database import (
    export_model_predictions_csv,
    get_label,
    get_labels,
    link_label_to_model,
    unlink_label_from_model,
)
from .ml.models import MLModel
from .ml.services import MLModelService
from .project import update_session_project
from .settings import WORK_PATH
from .tasks.active_learning import train_model


def get_model_or_404(project_id: int, model_id: int) -> MLModel:
    """Get model by ID, verifying it belongs to the given project."""
    service = MLModelService(WORK_PATH)
    model = service.get_model(model_id)

    if not model:
        abort(404)

    if model.project_id != project_id:
        abort(403)

    return model


@app.route("/<int:project_id>/models")
def models_list(project_id: int) -> str:
    """List ML models for the current project."""
    res = update_session_project(project_id)
    if res is not None:
        return res

    service = MLModelService(WORK_PATH)
    models = service.list_models(project_id=project_id, limit=100)

    return render_template("models/list.html", models=models)


@app.route("/<int:project_id>/models/create", methods=["GET", "POST"])
def model_create(project_id: int) -> str | Response:
    """Create new ML model for the current project."""
    res = update_session_project(project_id)
    if res is not None:
        return res

    if request.method == "POST":
        name = request.form.get("name")
        algorithm = request.form.get("algorithm", "TfidfXGBoostClassifier")
        description = request.form.get("description", "")

        if not name:
            flash(_("Name is required."), category="error")
            return redirect(url_for("model_create", project_id=project_id))

        service = MLModelService(WORK_PATH)
        try:
            model = service.registry.create_model(
                name=name,
                project_id=project_id,
                created_by=session["user_id"],
                algorithm=algorithm,
                description=description,
            )

            flash(
                _("Model {name} created successfully.").format(name=model.name),
                category="success",
            )
            return redirect(url_for("model_detail", project_id=project_id, model_id=model.id))

        except Exception as e:
            flash(_("Error creating model: {error}").format(error=str(e)), category="error")
            return redirect(url_for("model_create", project_id=project_id))

    return render_template("models/create.html")


@app.route("/<int:project_id>/models/<int:model_id>")
def model_detail(project_id: int, model_id: int) -> str | Response:
    """View model details with versions."""
    res = update_session_project(project_id)
    if res is not None:
        return res

    model = get_model_or_404(project_id, model_id)
    service = MLModelService(WORK_PATH)

    versions = service.list_versions(model_id, limit=50)
    active_version = service.get_active_version(model_id)

    linked_label = None
    if model.label_id:
        linked_label = get_label(model.label_id)

    training_jobs = service.list_training_jobs(model_id=model_id, limit=10)

    available_labels = sorted(get_labels(project_id), key=lambda lbl: lbl.name)

    return render_template(
        "models/detail.html",
        model=model,
        versions=versions,
        active_version=active_version,
        linked_label=linked_label,
        training_jobs=training_jobs,
        available_labels=available_labels,
    )


@app.route("/<int:project_id>/models/<int:model_id>/train", methods=["POST"])
def model_train(project_id: int, model_id: int) -> Response:
    """Start training job for model."""
    model = get_model_or_404(project_id, model_id)

    force_retrain = request.form.get("force_retrain") == "true"

    launch_task_with_tracking(
        train_model,
        user_id=session["user_id"],
        track_progress=True,
        description=_("Training model {name}").format(name=model.name),
        model_id=model_id,
        force_retrain=force_retrain,
    )

    flash(
        _("Training started for model {name}. Check back in a few minutes.").format(
            name=model.name
        ),
        category="success",
    )

    return redirect(url_for("model_detail", project_id=project_id, model_id=model_id))


@app.route(
    "/<int:project_id>/models/<int:model_id>/versions/<int:version_id>/activate", methods=["POST"]
)
def version_activate(project_id: int, model_id: int, version_id: int) -> Response:
    """Activate a specific version."""
    get_model_or_404(project_id, model_id)
    service = MLModelService(WORK_PATH)

    try:
        version = service.activate_version(version_id)
        flash(
            _("Version {version} activated.").format(version=version.version),
            category="success",
        )
    except Exception as e:
        flash(_("Error activating version: {error}").format(error=str(e)), category="error")

    return redirect(url_for("model_detail", project_id=project_id, model_id=model_id))


@app.route("/<int:project_id>/models/<int:model_id>/link-label", methods=["POST"])
def model_link_label(project_id: int, model_id: int) -> Response:
    """Link model to a label."""
    model = get_model_or_404(project_id, model_id)
    service = MLModelService(WORK_PATH)

    label_id = request.form.get("label_id", type=int)

    if not label_id:
        flash(_("Label ID is required."), category="error")
        return redirect(url_for("model_detail", project_id=project_id, model_id=model_id))

    label = get_label(label_id)
    if not label:
        flash(_("Label not found."), category="error")
        return redirect(url_for("model_detail", project_id=project_id, model_id=model_id))

    if label.project_id != project_id:
        flash(_("Label must belong to the same project as the model."), category="error")
        return redirect(url_for("model_detail", project_id=project_id, model_id=model_id))

    if label.ml_model_id and label.ml_model_id != model_id:
        old_model = service.get_model(label.ml_model_id)
        flash(
            _(
                "Label {label} is already linked to model {model}. "
                "Unlink it first or choose another label."
            ).format(label=label.name, model=old_model.name if old_model else "unknown"),
            category="warning",
        )
        return redirect(url_for("model_detail", project_id=project_id, model_id=model_id))

    link_label_to_model(label_id, model_id)

    flash(
        _("Model {model} linked to label {label}.").format(model=model.name, label=label.name),
        category="success",
    )

    return redirect(url_for("model_detail", project_id=project_id, model_id=model_id))


@app.route("/<int:project_id>/models/<int:model_id>/unlink-label", methods=["POST"])
def model_unlink_label(project_id: int, model_id: int) -> Response:
    """Unlink model from its label."""
    model = get_model_or_404(project_id, model_id)

    if not model.label_id:
        flash(_("Model is not linked to any label."), category="warning")
        return redirect(url_for("model_detail", project_id=project_id, model_id=model_id))

    unlink_label_from_model(model.label_id, model_id)

    flash(_("Model unlinked from label."), category="success")

    return redirect(url_for("model_detail", project_id=project_id, model_id=model_id))


@app.route("/<int:project_id>/models/<int:model_id>/delete", methods=["POST"])
def model_delete(project_id: int, model_id: int) -> Response:
    """Delete model (soft delete)."""
    model = get_model_or_404(project_id, model_id)
    service = MLModelService(WORK_PATH)

    if model.label_id:
        flash(
            _("Cannot delete model linked to a label. Unlink it first."),
            category="error",
        )
        return redirect(url_for("model_detail", project_id=project_id, model_id=model_id))

    try:
        service.registry.delete_model(model_id)
        flash(_("Model deleted successfully."), category="success")
        return redirect(url_for("models_list", project_id=project_id))
    except Exception as e:
        flash(_("Error deleting model: {error}").format(error=str(e)), category="error")
        return redirect(url_for("model_detail", project_id=project_id, model_id=model_id))


@app.route("/<int:project_id>/models/<int:model_id>/predict", methods=["GET", "POST"])
def model_predict(project_id: int, model_id: int) -> str | Response:
    """Test predictions on model."""
    res = update_session_project(project_id)
    if res is not None:
        return res

    model = get_model_or_404(project_id, model_id)
    service = MLModelService(WORK_PATH)

    prediction_result = None

    if request.method == "POST":
        text = request.form.get("text", "")
        version_id = request.form.get("version_id", type=int)

        if text:
            try:
                result = service.predict(model_id, text, version_id=version_id)
                prediction_result = {
                    "text": text,
                    "predicted_class": result.predicted_class,
                    "prediction_set": result.prediction_set,
                    "confidence": result.confidence,
                    "probabilities": result.probabilities,
                }
            except Exception as e:
                flash(_("Error making prediction: {error}").format(error=str(e)), category="error")

    versions = service.list_versions(model_id, limit=20)
    active_version = service.get_active_version(model_id)

    return render_template(
        "models/predict.html",
        model=model,
        versions=versions,
        active_version=active_version,
        prediction_result=prediction_result,
    )


@app.route("/<int:project_id>/models/<int:model_id>/export-predictions")
def model_export_predictions(project_id: int, model_id: int) -> FlaskResponse:
    """Export model predictions as CSV."""
    model = get_model_or_404(project_id, model_id)
    version_id = request.args.get("version_id", type=int)

    trusted_only = request.args.get("trusted_only") == "1"
    csv_content = export_model_predictions_csv(
        model_id, version_id=version_id, trusted_only=trusted_only
    )

    filename = f"predictions_{model.slug}"
    if trusted_only:
        filename += "_trusted"
    if version_id:
        filename += f"_v{version_id}"
    filename += ".csv"

    response = make_response(csv_content)
    response.headers["Content-Type"] = "text/csv; charset=utf-8"
    response.headers["Content-Disposition"] = f"attachment; filename={filename}"
    return response


@app.route("/<int:project_id>/models/<int:model_id>/update-alpha", methods=["POST"])
def model_update_alpha(project_id: int, model_id: int) -> Response:
    """Update per-model conformal alpha (confidence level) override."""
    model = get_model_or_404(project_id, model_id)
    alpha_raw = request.form.get("alpha", "").strip()
    config = dict(model.training_config or {})
    if alpha_raw:
        try:
            alpha = float(alpha_raw)
            if not 0.01 <= alpha <= 0.5:
                raise ValueError
            config["alpha"] = alpha
        except ValueError:
            flash(_("Alpha must be a number between 0.01 and 0.5"), "error")
            return redirect(url_for("model_detail", project_id=project_id, model_id=model_id))
    else:
        config.pop("alpha", None)
    service = MLModelService(WORK_PATH)
    service.update_model(model_id, training_config=config)
    flash(_("Confidence level updated. Re-train to apply."), "success")
    return redirect(url_for("model_detail", project_id=project_id, model_id=model_id))
