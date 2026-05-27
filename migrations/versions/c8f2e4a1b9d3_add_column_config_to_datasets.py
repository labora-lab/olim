"""add column_config to datasets

Revision ID: c8f2e4a1b9d3
Revises: 9708028a5f9a
Create Date: 2026-05-26 23:50:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = 'c8f2e4a1b9d3'
down_revision = '9708028a5f9a'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = [c['name'] for c in inspector.get_columns('datasets')]

    if 'column_config' in columns:
        return

    with op.batch_alter_table('datasets', schema=None) as batch_op:
        batch_op.add_column(sa.Column('column_config', sa.JSON(), nullable=True))


def downgrade():
    with op.batch_alter_table('datasets', schema=None) as batch_op:
        batch_op.drop_column('column_config')
