"""Add isolate_label_values global setting

Revision ID: 1eba81f123cd
Revises: c8f2e4a1b9d3
Create Date: 2026-05-27 04:16:17.703116

"""
from datetime import datetime

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '1eba81f123cd'
down_revision = 'c8f2e4a1b9d3'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        sa.text(
            """
            INSERT INTO global_settings
                (key, display_name, value, default_value, type, description, category,
                 created, created_by, is_deleted)
            VALUES
                ('isolate_label_values', 'Isolate Label Values', 'false', 'false', 'bool',
                 'When enabled, each user''s label values are stored and displayed independently. '
                 'Adding a label will not overwrite another user''s value for the same entry.',
                 'Labeling', :now, 1, false)
            ON CONFLICT (key) DO NOTHING
            """
        ).bindparams(now=datetime.now())
    )


def downgrade():
    op.execute(
        sa.text("DELETE FROM global_settings WHERE key = 'isolate_label_values'")
    )
