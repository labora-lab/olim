# import json
# from datetime import datetime
# from typing import Any

# from .. import app as flask_app
# from ..celery_app import app
# from ..database import CeleryTask, Label, db


# class LearnerInterface:
#     """Celery task interface for learner operations"""

#     @staticmethod
#     def _update_label_metrics(label_id: int, metrics: dict[str, Any],
#                             cache: dict[str, Any] = None) -> None:
#         """Helper to update label metrics and cache"""
#         with flask_app.app_context():
#             label = db.session.get(Label, label_id)
#             if not label:
#                 raise ValueError(f"Label {label_id} not found")

#             if metrics:
#                 label.metrics = json.dumps(metrics)
#             if cache:
#                 label.cache = json.dumps(cache)

#             db.session.commit()

#     @app.task(bind=True, name="learner.create_label")  # type: ignore
#     def create_label(self, values: list[str], label_id: int) -> dict[str, Any]:
#         """Create new active learning label"""
#         try:
#             with flask_app.app_context():
#                 label = db.session.get(Label, label_id)
#                 if not label:
#                     raise ValueError(f"Label {label_id} not found")

#                 # Initialize learner (implementation specific)
#                 learner = flask_app.extensions['learner'].create_learner(
#                     label.project.datasets[0].id,
#                     values
#                 )

#                 # Store the learner key
#                 label.al_key = learner.label_id
#                 db.session.commit()

#                 # Register task using Celery's task ID
#                 CeleryTask.create_task(
#                     task_id=self.request.id,
#                     task_name=self.name,
#                     user_id=self.request.get('user_id', 0),
#                     kwargs={"label_id": label_id}
#                 )

#                 return {"success": True, "errors": None}

#         except Exception as e:
#             self.retry(exc=e, countdown=60, max_retries=3)
#             return {"success": False, "errors": [str(e)]}

#     @app.task(bind=True, name="learner.train_model")  # type: ignore
#     def train_model(self, label_id: int) -> dict[str, Any]:
#         """Train model and store results in label"""
#         try:
#             with flask_app.app_context():
#                 label = db.session.get(Label, label_id)
#                 if not label or not label.al_key:
#                     raise ValueError("Label or learner not initialized")

#                 learner = flask_app.extensions['learner'].get_learner(
#                     label.project.datasets[0].id,
#                     label.al_key
#                 )

#                 # Train and get metrics
#                 learner._train()
#                 metrics = {
#                     "last_trained": datetime.utcnow().isoformat(),
#                     "performance": learner.get_performance_metrics(),
#                     "subsample_size": len(learner._cached_subsample)
#                 }

#                 # Update label with metrics and cache
#                 self._update_label_metrics(
#                     label_id,
#                     metrics=metrics,
#                     cache={"subsample": learner._cached_subsample}
#                 )

#                 # Register task
#                 CeleryTask.create_task(
#                     task_id=self.request.id,
#                     task_name=self.name,
#                     user_id=self.request.get('user_id', 0),
#                     kwargs={"label_id": label_id}
#                 )

#                 return {"success": True, "metrics": metrics}

#         except Exception as e:
#             self.retry(exc=e, countdown=120, max_retries=3)
#             return {"success": False, "errors": [str(e)]}

#     @app.task(bind=True, name="learner.add_label_value")  # type: ignore
#     def add_label_value(self, label_id: int, entry_id: str, value: str) -> dict[str, Any]:
#         """Submit a labeled value and update metrics"""
#         try:
#             with flask_app.app_context():
#                 label = db.session.get(Label, label_id)
#                 if not label or not label.al_key:
#                     raise ValueError("Label or learner not initialized")

#                 learner = flask_app.extensions['learner'].get_learner(
#                     label.project.datasets[0].id,
#                     label.al_key
#                 )
#                 learner.submit_labelling(entry_id, value)

#                 # Update metrics
#                 metrics = {
#                     "last_update": datetime.utcnow().isoformat(),
#                     "total_labels": len(label.entries) + 1
#                 }
#                 self._update_label_metrics(label_id, metrics=metrics)

#                 # Register task
#                 CeleryTask.create_task(
#                     task_id=self.request.id,
#                     task_name=self.name,
#                     user_id=self.request.get('user_id', 0),
#                     kwargs={
#                         "label_id": label_id,
#                         "entry_id": entry_id
#                     }
#                 )

#                 return {"success": True}

#         except Exception as e:
#             self.retry(exc=e, countdown=30, max_retries=5)
#             return {"success": False, "errors": [str(e)]}

#     @app.task(bind=True, name="learner.sync_label")  # type: ignore
#     def sync_label(self, label_id: int) -> dict[str, Any]:
#         """Synchronize label state and update metrics"""
#         try:
#             with flask_app.app_context():
#                 label = db.session.get(Label, label_id)
#                 if not label or not label.al_key:
#                     raise ValueError("Label or learner not initialized")

#                 learner = flask_app.extensions['learner'].get_learner(
#                     label.project.datasets[0].id,
#                     label.al_key
#                 )

#                 # Get current entries
#                 entries = {e.entry.entry_id: e.value for e in label.entries}
#                 learner.sync_labelling(entries)

#                 # Update metrics
#                 metrics = {
#                     "last_sync": datetime.utcnow().isoformat(),
#                     "total_labels": len(entries),
#                     "consistency_check": learner.check_consistency()
#                 }
#                 self._update_label_metrics(label_id, metrics=metrics)

#                 return {"success": True}

#         except Exception as e:
#             self.retry(exc=e, countdown=60, max_retries=3)
#             return {"success": False, "errors": [str(e)]}

#     @app.task(bind=True, name="learner.export_predictions")  # type: ignore
#     def export_predictions(self, label_id: int, alpha: float = 0.95) -> dict[str, Any]:
#         """Export model predictions"""
#         try:
#             with flask_app.app_context():
#                 label = db.session.get(Label, label_id)
#                 if not label or not label.al_key:
#                     raise ValueError("Label or learner not initialized")

#                 learner = flask_app.extensions['learner'].get_learner(
#                     label.project.datasets[0].id,
#                     label.al_key
#                 )
#                 preds = learner.export_predictions(alpha=alpha)

#                 return {
#                     "success": True,
#                     "predictions": preds,
#                     "metrics": label.get_metrics()
#                 }

#         except Exception as e:
#             self.retry(exc=e, countdown=30, max_retries=2)
#             return {"success": False, "errors": [str(e)]}

#     # Add to LearnerInterface class
#     @app.task(bind=True, name="learner.get_next_entry")  # type: ignore
#     def get_next_entry(self, label_id: int) -> dict[str, Any]:
#         """Get next entry for labelling"""
#         try:
#             with flask_app.app_context():
#                 label = db.session.get(Label, label_id)
#                 learner = flask_app.extensions['learner'].get_learner(
#                     label.project.datasets[0].id,
#                     label.al_key
#                 )
#                 return {
#                     "entry_id": learner.request_next_entry(),
#                     "messages": learner.metrics_strs
#                 }
#         except Exception as e:
#             self.retry(exc=e, countdown=30, max_retries=3)
