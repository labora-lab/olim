"""Add api_key column to users table

Revision ID: b3c4d5e6f7a8
Revises: f2a646872d44
Create Date: 2026-03-30 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

revision = "b3c4d5e6f7a8"
down_revision = "f2a646872d44"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("api_key", sa.String(length=64), nullable=True))
        batch_op.create_index("ix_users_api_key", ["api_key"], unique=True)


def downgrade() -> None:
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_index("ix_users_api_key")
        batch_op.drop_column("api_key")
