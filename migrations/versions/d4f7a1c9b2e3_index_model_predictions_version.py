"""Index model_predictions.version_id for maintenance health checks

The maintenance scan joins model_predictions to label-patient filtered by version_id.
ix_model_predictions_entry_label covers the join keys but not that filter, so without
this the scan degrades to a full table scan of every prediction ever stored — and
_store_full_predictions writes one row per unlabeled entry per training run.

Revision ID: d4f7a1c9b2e3
Revises: 1eba81f123cd
Create Date: 2026-08-18

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "d4f7a1c9b2e3"
down_revision = "1eba81f123cd"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {ix["name"] for ix in inspector.get_indexes("model_predictions")}
    if "ix_model_predictions_version" not in existing:
        op.create_index(
            "ix_model_predictions_version",
            "model_predictions",
            ["version_id"],
        )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {ix["name"] for ix in inspector.get_indexes("model_predictions")}
    if "ix_model_predictions_version" in existing:
        op.drop_index("ix_model_predictions_version", table_name="model_predictions")
