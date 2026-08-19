"""Model health scan for the maintenance active learning task.

Runs on demand when a user opens the maintenance task — there is no scheduler in this
deployment, and adding one would mean a beat service nobody is watching. Scanning at
the moment somebody is ready to act on the answer is the honest trade.
"""

from __future__ import annotations

from typing import Any

from .. import app as flask_app, settings
from ..celery_app import app
from ..database import get_label
from ..ml.monitoring import ModelHealth, prediction_agreement, unchecked_prediction_ids
from ..ml.services import MLModelService


@app.task(bind=True, name="maintenance.scan_models", track_progress=True)
def scan_models(
    self,
    user_id: int,
    project_id: int,
    measure_coverage: bool = True,
    **__,
) -> dict[str, Any]:
    """Report the health of every trained model in a project.

    Args:
        user_id: User triggering the scan
        project_id: Project whose models to scan
        measure_coverage: Re-score the unlabelled pool to compare confidence against
            training time. Accurate but the expensive part — one full pass per model.

    Returns:
        {"success": True, "reports": [ModelHealth-shaped dicts]}
    """
    with flask_app.app_context():
        service = MLModelService(settings.WORK_PATH)
        models = service.list_models(project_id=project_id)
        reports: list[dict[str, Any]] = []

        for index, model in enumerate(models):
            self.update_state(
                state="PROCESSING",
                meta={
                    "progress": int(100 * index / max(len(models), 1)),
                    "status": f"Checking {model.name}",
                },
            )

            label = get_label(model.label_id) if model.label_id else None
            report = ModelHealth(
                model_id=model.id,
                model_name=model.name,
                label_id=model.label_id,
                label_name=label.name if label else "—",
            )

            version = service.get_active_version(model.id)
            if version is None or model.label_id is None:
                report.reasons.append("never trained")
                reports.append(report.to_dict())
                continue

            report.version_id = version.id
            report.version_number = version.version
            report.trained_at = version.trained_at.isoformat() if version.trained_at else None

            agreement = prediction_agreement(model.label_id, version.id, version.trained_at)
            report.n_checked = agreement["n_checked"]
            report.n_agree = agreement["n_agree"]
            report.audit_accuracy = agreement["accuracy"]
            report.per_class = agreement["per_class"]

            report.unchecked_predictions = len(unchecked_prediction_ids(model.label_id, version.id))

            report.coverage_at_training = (version.metrics or {}).get("coverage")
            if measure_coverage:
                try:
                    report.coverage_now = _current_coverage(service, model.id)
                except Exception as error:  # a scan must not die on one bad model
                    report.reasons.append(f"coverage unavailable: {error}")
            if report.coverage_at_training is not None and report.coverage_now is not None:
                report.coverage_drop = report.coverage_at_training - report.coverage_now

            reports.append(report.to_dict())

        return {"success": True, "reports": reports}


def _current_coverage(service: MLModelService, model_id: int) -> float | None:
    """Fraction of the unlabelled pool the active model still commits to a single class.

    Reuses the training pipeline's own ranking pass, which already computes exactly
    this as its `coverage` metric — so the number is comparable with the one stored on
    the version at training time.
    """
    from ..database import get_labeled_entry_ids
    from ..ml.artifacts import ArtifactManager

    model = service.get_model(model_id)
    version = service.get_active_version(model_id)
    if model is None or version is None or model.label_id is None:
        return None

    artifacts = ArtifactManager(service.work_path / "ml_models").load_artifacts(
        model_id, version.version
    )
    conformal = artifacts["model"]
    fields = artifacts.get("fields") or ["text"]

    orchestrator = service.orchestrator
    _cache, coverage = orchestrator._rank_entries_batched(
        conformal,
        model,
        fields,
        get_labeled_entry_ids(model.label_id),
        overrides={"pool_size": 10, "cache_size": 1, "n_clusters": 1, "certain_rate": 0.0},
    )
    return coverage
