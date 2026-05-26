"""add project_id to learning_tasks

Revision ID: 9708028a5f9a
Revises: af8ef6d637cd
Create Date: 2026-05-26 23:35:42.243980

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


# revision identifiers, used by Alembic.
revision = '9708028a5f9a'
down_revision = 'af8ef6d637cd'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = [c['name'] for c in inspector.get_columns('learning_tasks')]

    if 'project_id' in columns:
        return  # fresh installs via a82bba690b03 already have the column

    # Add nullable first so existing rows don't violate the constraint
    with op.batch_alter_table('learning_tasks', schema=None) as batch_op:
        batch_op.add_column(sa.Column('project_id', sa.Integer(), nullable=True))

    # Backfill: assign all existing tasks to the first project
    bind.execute(text(
        "UPDATE learning_tasks "
        "SET project_id = (SELECT id FROM projects ORDER BY id LIMIT 1) "
        "WHERE project_id IS NULL"
    ))

    # Enforce NOT NULL and the FK
    with op.batch_alter_table('learning_tasks', schema=None) as batch_op:
        batch_op.alter_column('project_id', nullable=False)
        batch_op.create_foreign_key(
            'fk_learning_task_project', 'projects', ['project_id'], ['id']
        )


def downgrade():
    with op.batch_alter_table('learning_tasks', schema=None) as batch_op:
        batch_op.drop_constraint('fk_learning_task_project', type_='foreignkey')
        batch_op.drop_column('project_id')
