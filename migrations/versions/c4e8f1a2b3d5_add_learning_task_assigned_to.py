"""Add assigned_to column to learning_tasks

Revision ID: c4e8f1a2b3d5
Revises: b3f1a2c4d5e6
Create Date: 2026-03-24 00:00:01.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "c4e8f1a2b3d5"
down_revision = "b3f1a2c4d5e6"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("learning_tasks", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("assigned_to", sa.Integer(), sa.ForeignKey("users.id"), nullable=True)
        )
        batch_op.create_index("ix_learning_tasks_assigned_to", ["assigned_to"])


def downgrade():
    with op.batch_alter_table("learning_tasks", schema=None) as batch_op:
        batch_op.drop_index("ix_learning_tasks_assigned_to")
        batch_op.drop_column("assigned_to")
