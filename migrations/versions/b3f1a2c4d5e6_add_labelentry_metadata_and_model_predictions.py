"""Add metadata to LabelEntry and create model_predictions table

Revision ID: b3f1a2c4d5e6
Revises: 7065dcc8ea90
Create Date: 2026-03-24 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = 'b3f1a2c4d5e6'
down_revision = '7065dcc8ea90'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    existing_tables = inspect(bind).get_table_names()

    # bfb791bf358b may have been skipped if the DB was stamped at a82bba690b03
    # via an old chain that didn't include the ML models branch. Create the
    # tables here if they are still missing so this migration is always safe.
    if 'ml_models' not in existing_tables:
        op.create_table(
            'ml_models',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('slug', sa.String(), nullable=False),
            sa.Column('name', sa.String(), nullable=False),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('project_id', sa.Integer(), nullable=False),
            sa.Column('label_id', sa.Integer(), nullable=True),
            sa.Column('model_type', sa.String(), nullable=False),
            sa.Column('algorithm', sa.String(), nullable=False),
            sa.Column('model_config', sa.JSON(), nullable=False),
            sa.Column('training_config', sa.JSON(), nullable=False),
            sa.Column('policy_type', sa.String(), nullable=True),
            sa.Column('subsample_config', sa.JSON(), nullable=True),
            sa.Column('status', sa.String(), nullable=False),
            sa.Column('created', sa.DateTime(), nullable=False),
            sa.Column('created_by', sa.Integer(), nullable=False),
            sa.Column('is_deleted', sa.Boolean(), nullable=False),
            sa.Column('deleted', sa.DateTime(), nullable=True),
            sa.Column('deleted_by', sa.Integer(), nullable=True),
            sa.ForeignKeyConstraint(['created_by'], ['users.id'], name='fk_ml_models_created_by'),
            sa.ForeignKeyConstraint(['label_id'], ['labels.id']),
            sa.ForeignKeyConstraint(['project_id'], ['projects.id']),
            sa.PrimaryKeyConstraint('id'),
        )
        with op.batch_alter_table('ml_models', schema=None) as batch_op:
            batch_op.create_index(batch_op.f('ix_ml_models_label_id'), ['label_id'], unique=False)
            batch_op.create_index(batch_op.f('ix_ml_models_slug'), ['slug'], unique=True)
            batch_op.create_index(batch_op.f('ix_ml_models_status'), ['status'], unique=False)

    if 'ml_model_versions' not in existing_tables:
        op.create_table(
            'ml_model_versions',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('model_id', sa.Integer(), nullable=False),
            sa.Column('version', sa.Integer(), nullable=False),
            sa.Column('artifact_path', sa.String(), nullable=False),
            sa.Column('trained_at', sa.DateTime(), nullable=False),
            sa.Column('training_duration', sa.Float(), nullable=True),
            sa.Column('n_train_samples', sa.Integer(), nullable=False),
            sa.Column('n_val_samples', sa.Integer(), nullable=False),
            sa.Column('class_distribution', sa.JSON(), nullable=True),
            sa.Column('metrics', sa.JSON(), nullable=False),
            sa.Column('conformal_threshold', sa.Float(), nullable=True),
            sa.Column('cache_entries', sa.JSON(), nullable=True),
            sa.Column('is_active', sa.Boolean(), nullable=False),
            sa.Column('created', sa.DateTime(), nullable=False),
            sa.Column('created_by', sa.Integer(), nullable=False),
            sa.Column('is_deleted', sa.Boolean(), nullable=False),
            sa.Column('deleted', sa.DateTime(), nullable=True),
            sa.Column('deleted_by', sa.Integer(), nullable=True),
            sa.ForeignKeyConstraint(['created_by'], ['users.id'], name='fk_ml_model_versions_created_by'),
            sa.ForeignKeyConstraint(['model_id'], ['ml_models.id']),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('model_id', 'version', name='uq_model_version'),
        )
        with op.batch_alter_table('ml_model_versions', schema=None) as batch_op:
            batch_op.create_index('ix_ml_model_versions_active', ['model_id', 'is_active'], unique=False)
            batch_op.create_index('ix_ml_model_versions_trained', ['trained_at'], unique=False)

    # Also add ml_model_id to labels if bfb791bf358b was skipped
    if 'ml_models' not in existing_tables:
        with op.batch_alter_table('labels', schema=None) as batch_op:
            batch_op.add_column(sa.Column('ml_model_id', sa.Integer(), nullable=True))
            batch_op.create_index(batch_op.f('ix_labels_ml_model_id'), ['ml_model_id'], unique=False)
            batch_op.create_foreign_key(None, 'ml_models', ['ml_model_id'], ['id'])

    # Add metadata column to LabelEntry
    with op.batch_alter_table('label-patient', schema=None) as batch_op:
        batch_op.add_column(sa.Column('metadata', sa.JSON(), nullable=True))

    # Create model_predictions table
    if 'model_predictions' not in existing_tables:
        op.create_table(
            'model_predictions',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('entry_id', sa.Integer(), sa.ForeignKey('entries.id'), nullable=False),
            sa.Column('label_id', sa.Integer(), sa.ForeignKey('labels.id'), nullable=False),
            sa.Column('model_id', sa.Integer(), sa.ForeignKey('ml_models.id'), nullable=False),
            sa.Column('version_id', sa.Integer(), sa.ForeignKey('ml_model_versions.id'), nullable=False),
            sa.Column('value', sa.String(), nullable=True),
            sa.Column('score', sa.Float(), nullable=True),
            sa.Column('prediction_set', sa.JSON(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index('ix_model_predictions_label', 'model_predictions', ['label_id'])
        op.create_index('ix_model_predictions_entry_label', 'model_predictions', ['entry_id', 'label_id'])


def downgrade():
    op.drop_index('ix_model_predictions_entry_label', table_name='model_predictions')
    op.drop_index('ix_model_predictions_label', table_name='model_predictions')
    op.drop_table('model_predictions')

    with op.batch_alter_table('label-patient', schema=None) as batch_op:
        batch_op.drop_column('metadata')
