"""remove ml_training_jobs table - use celery_tasks instead

Revision ID: 7a445fdba8d5
Revises: bfb791bf358b
Create Date: 2026-02-17 15:31:59.536143

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '7a445fdba8d5'
down_revision = 'bfb791bf358b'
branch_labels = None
depends_on = None


def upgrade():
    op.drop_table('ml_training_jobs')


def downgrade():
    op.create_table(
        'ml_training_jobs',
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('model_id', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('version_id', sa.Integer(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('config_snapshot', sa.JSON(), nullable=False),
        sa.Column('created', sa.DateTime(), nullable=False),
        sa.Column('created_by', sa.Integer(), nullable=False),
        sa.Column('modified', sa.DateTime(), nullable=True),
        sa.Column('modified_by', sa.Integer(), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), nullable=False),
        sa.Column('deleted', sa.DateTime(), nullable=True),
        sa.Column('deleted_by', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['model_id'], ['ml_models.id']),
        sa.ForeignKeyConstraint(['version_id'], ['ml_model_versions.id']),
        sa.ForeignKeyConstraint(['created_by'], ['users.id']),
        sa.ForeignKeyConstraint(['modified_by'], ['users.id']),
        sa.ForeignKeyConstraint(['deleted_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_ml_training_jobs_model', 'ml_training_jobs', ['model_id'])
    op.create_index('ix_ml_training_jobs_status', 'ml_training_jobs', ['status'])
