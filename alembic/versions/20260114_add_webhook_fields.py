"""add webhook fields to bot emails

Revision ID: 9d8e7f6a5b4c
Revises: 8c3d4e5f6a7b
Create Date: 2026-01-14

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '9d8e7f6a5b4c'
down_revision = '8c3d4e5f6a7b'
branch_labels = None
depends_on = None


def upgrade():
    # Add webhook-related fields to bot_emails table
    op.add_column('bot_emails', sa.Column('watch_history_id', sa.String(255), nullable=True))
    op.add_column('bot_emails', sa.Column('watch_expiration', sa.BigInteger(), nullable=True))
    
    # Add index for faster lookups
    op.create_index('ix_bot_emails_watch_history_id', 'bot_emails', ['watch_history_id'])


def downgrade():
    # Remove the added columns
    op.drop_index('ix_bot_emails_watch_history_id', table_name='bot_emails')
    op.drop_column('bot_emails', 'watch_expiration')
    op.drop_column('bot_emails', 'watch_history_id')
