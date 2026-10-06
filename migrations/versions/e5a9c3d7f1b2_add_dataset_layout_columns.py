"""add id_column, text_column and columns to datasets

Revision ID: e5a9c3d7f1b2
Revises: d4f7a1c9b2e3
Create Date: 2026-10-06 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = 'e5a9c3d7f1b2'
down_revision = 'd4f7a1c9b2e3'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    existing = [c['name'] for c in inspector.get_columns('datasets')]

    with op.batch_alter_table('datasets', schema=None) as batch_op:
        if 'id_column' not in existing:
            batch_op.add_column(sa.Column('id_column', sa.String(), nullable=True))
        if 'text_column' not in existing:
            batch_op.add_column(sa.Column('text_column', sa.String(), nullable=True))
        if 'columns' not in existing:
            batch_op.add_column(sa.Column('columns', sa.JSON(), nullable=True))


def downgrade():
    with op.batch_alter_table('datasets', schema=None) as batch_op:
        batch_op.drop_column('columns')
        batch_op.drop_column('text_column')
        batch_op.drop_column('id_column')
