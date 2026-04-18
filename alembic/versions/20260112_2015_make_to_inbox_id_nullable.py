"""make to_inbox_id nullable

Revision ID: 8c3d4e5f6a7b
Revises: 53a2b3bc6e4f
Create Date: 2026-01-12 20:15:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '8c3d4e5f6a7b'
down_revision = '53a2b3bc6e4f'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Make to_inbox_id nullable since bot emails don't have a recipient inbox
    op.alter_column('email_messages', 'to_inbox_id',
                    existing_type=sa.INTEGER(),
                    nullable=True)


def downgrade() -> None:
    # Revert to non-nullable
    op.alter_column('email_messages', 'to_inbox_id',
                    existing_type=sa.INTEGER(),
                    nullable=False)
