"""merge learning_tasks and datasets_sep heads

Revision ID: 7065dcc8ea90
Revises: 11999b1fb8f6, a82bba690b03
Create Date: 2026-03-18 19:07:43.931997

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '7065dcc8ea90'
down_revision = ('11999b1fb8f6', 'a82bba690b03')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
