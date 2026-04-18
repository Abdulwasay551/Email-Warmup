"""merge_heads

Revision ID: 2f707dfb2473
Revises: 0c40bdcb8bf3, a1b2c3d4e5f6
Create Date: 2026-01-19 19:09:19.808704

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '2f707dfb2473'
down_revision = ('0c40bdcb8bf3', 'a1b2c3d4e5f6')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
