from flask import abort, flash, redirect, render_template, request, session, url_for
from flask_babel import _
from werkzeug.wrappers.response import Response

from . import app, db
from .celery_app import launch_task_with_tracking
from .database import Project, get_label
from .ml.models import MLModel
from .ml.services import MLModelService
from .settings import WORK_PATH
from .tasks.ml_training import train_ml_model


def get_model_or_404(model_id: int) -> MLModel:
    """Get model by ID or return 404 if not found or user doesn't have access"""
    service = MLModelService(WORK_PATH)
    model = service.get_model(model_id)

    if not model:
        abort(404)

    # Check if user has access to this model's project
    # Users can only access models from their current project (stored in session)
    current_project_id = session.get("project_id")
    if current_project_id and model.project_id != current_project_id:
        # If user is trying to access a model from a different project, return 403
        abort(403)

    return model


@app.route("/models")
def models_list() -> str:
    """List all ML models"""
    # Get models with optional project filter
    project_id = request.args.get("project_id", type=int)

    service = MLModelService(WORK_PATH)
    models = service.list_models(project_id=project_id, limit=100)

    # Get projects for filter dropdown
    projects = db.session.query(Project).all()

    return render_template(
        "models/list.html",
        models=models,
        projects=projects,
        selected_project_id=project_id,
    )


@app.route("/models/<int:model_id>")
def model_detail(model_id: int) -> str | Response:
    """View model details with versions"""
    model = get_model_or_404(model_id)
    service = MLModelService(WORK_PATH)

    # Get versions
    versions = service.list_versions(model_id, limit=50)

    # Get active version
    active_version = service.get_active_version(model_id)

    # Get linked label if any
    linked_label = None
    if model.label_id:
        linked_label = get_label(model.label_id)

    # Get training jobs
    training_jobs = service.list_training_jobs(model_id=model_id, limit=10)

    return render_template(
        "models/detail.html",
        model=model,
        versions=versions,
        active_version=active_version,
        linked_label=linked_label,
        training_jobs=training_jobs,
    )


@app.route("/models/create", methods=["GET", "POST"])
def model_create() -> str | Response:
    """Create new ML model"""
    if request.method == "POST":
        name = request.form.get("name")
        project_id = request.form.get("project_id", type=int)
        algorithm = request.form.get("algorithm", "TfidfXGBoostClassifier")
        description = request.form.get("description", "")

        if not name or not project_id:
            flash(_("Name and project are required."), category="error")
            return redirect(url_for("model_create"))

        # Create model
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
            return redirect(url_for("model_detail", model_id=model.id))

        except Exception as e:
            flash(_("Error creating model: {error}").format(error=str(e)), category="error")
            return redirect(url_for("model_create"))

    # GET - show form
    projects = db.session.query(Project).all()
    return render_template("models/create.html", projects=projects)


@app.route("/models/<int:model_id>/train", methods=["POST"])
def model_train(model_id: int) -> Response:
    """Start training job for model"""
    model = get_model_or_404(model_id)

    force_retrain = request.form.get("force_retrain") == "true"

    # Launch training task
    launch_task_with_tracking(
        train_ml_model,
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

    return redirect(url_for("model_detail", model_id=model_id))


@app.route("/models/<int:model_id>/versions/<int:version_id>/activate", methods=["POST"])
def version_activate(model_id: int, version_id: int) -> Response:
    """Activate a specific version"""
    service = MLModelService(WORK_PATH)

    try:
        version = service.activate_version(version_id)
        flash(
            _("Version {version} activated.").format(version=version.version),
            category="success",
        )
    except Exception as e:
        flash(_("Error activating version: {error}").format(error=str(e)), category="error")

    return redirect(url_for("model_detail", model_id=model_id))


@app.route("/models/<int:model_id>/link-label", methods=["POST"])
def model_link_label(model_id: int) -> Response:
    """Link model to a label"""
    model = get_model_or_404(model_id)
    service = MLModelService(WORK_PATH)

    label_id = request.form.get("label_id", type=int)

    if not label_id:
        flash(_("Label ID is required."), category="error")
        return redirect(url_for("model_detail", model_id=model_id))

    label = get_label(label_id)
    if not label:
        flash(_("Label not found."), category="error")
        return redirect(url_for("model_detail", model_id=model_id))

    # Security check: ensure label belongs to same project as model
    if label.project_id != model.project_id:
        flash(_("Label must belong to the same project as the model."), category="error")
        return redirect(url_for("model_detail", model_id=model_id))

    # Check if label already has a model
    if label.ml_model_id and label.ml_model_id != model_id:
        old_model = service.get_model(label.ml_model_id)
        flash(
            _(
                "Label {label} is already linked to model {model}. "
                "Unlink it first or choose another label."
            ).format(label=label.name, model=old_model.name if old_model else "unknown"),
            category="warning",
        )
        return redirect(url_for("model_detail", model_id=model_id))

    # Link label to model
    label.ml_model_id = model_id
    model.label_id = label_id
    db.session.commit()

    flash(
        _("Model {model} linked to label {label}.").format(model=model.name, label=label.name),
        category="success",
    )

    return redirect(url_for("model_detail", model_id=model_id))


@app.route("/models/<int:model_id>/unlink-label", methods=["POST"])
def model_unlink_label(model_id: int) -> Response:
    """Unlink model from its label"""
    model = get_model_or_404(model_id)

    if not model.label_id:
        flash(_("Model is not linked to any label."), category="warning")
        return redirect(url_for("model_detail", model_id=model_id))

    # Unlink
    label = get_label(model.label_id)
    if label:
        label.ml_model_id = None

    model.label_id = None
    db.session.commit()

    flash(_("Model unlinked from label."), category="success")

    return redirect(url_for("model_detail", model_id=model_id))


@app.route("/models/<int:model_id>/delete", methods=["POST"])
def model_delete(model_id: int) -> Response:
    """Delete model (soft delete)"""
    model = get_model_or_404(model_id)
    service = MLModelService(WORK_PATH)

    # Check if linked to label
    if model.label_id:
        flash(
            _("Cannot delete model linked to a label. Unlink it first."),
            category="error",
        )
        return redirect(url_for("model_detail", model_id=model_id))

    try:
        service.registry.delete_model(model_id)
        flash(_("Model deleted successfully."), category="success")
        return redirect(url_for("models_list"))
    except Exception as e:
        flash(_("Error deleting model: {error}").format(error=str(e)), category="error")
        return redirect(url_for("model_detail", model_id=model_id))


@app.route("/models/<int:model_id>/predict", methods=["GET", "POST"])
def model_predict(model_id: int) -> str | Response:
    """Test predictions on model"""
    model = get_model_or_404(model_id)
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

    # Get versions for dropdown
    versions = service.list_versions(model_id, limit=20)
    active_version = service.get_active_version(model_id)

    return render_template(
        "models/predict.html",
        model=model,
        versions=versions,
        active_version=active_version,
        prediction_result=prediction_result,
    )
