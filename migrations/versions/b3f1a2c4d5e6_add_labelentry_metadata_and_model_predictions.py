"""Add metadata to LabelEntry and create model_predictions table

Revision ID: b3f1a2c4d5e6
Revises: 7065dcc8ea90
Create Date: 2026-03-24 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b3f1a2c4d5e6'
down_revision = '7065dcc8ea90'
branch_labels = None
depends_on = None


def upgrade():
    # Add metadata column to LabelEntry
    with op.batch_alter_table('label-patient', schema=None) as batch_op:
        batch_op.add_column(sa.Column('metadata', sa.JSON(), nullable=True))

    # Create model_predictions table
    op.create_table(
        'model_predictions',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('entry_id', sa.Integer(), sa.ForeignKey('entries.id'), nullable=False),
        sa.Column('label_id', sa.Integer(), sa.ForeignKey('labels.id'), nullable=False),
        sa.Column('model_id', sa.Integer(), sa.ForeignKey('ml_models.id'), nullable=False),
        sa.Column('version_id', sa.Integer(), sa.ForeignKey('ml_model_versions.id'), nullable=False),
        sa.Column('value', sa.String(), nullable=True),
        sa.Column('score', sa.Float(), nullable=True),
        sa.Column('prediction_set', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )
    op.create_index('ix_model_predictions_label', 'model_predictions', ['label_id'])
    op.create_index('ix_model_predictions_entry_label', 'model_predictions', ['entry_id', 'label_id'])


def downgrade():
    op.drop_index('ix_model_predictions_entry_label', table_name='model_predictions')
    op.drop_index('ix_model_predictions_label', table_name='model_predictions')
    op.drop_table('model_predictions')

    with op.batch_alter_table('label-patient', schema=None) as batch_op:
        batch_op.drop_column('metadata')
