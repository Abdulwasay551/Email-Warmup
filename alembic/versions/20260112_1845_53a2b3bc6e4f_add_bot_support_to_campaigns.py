"""add_bot_support_to_campaigns

Revision ID: 53a2b3bc6e4f
Revises: 7e2ce598bb4b
Create Date: 2026-01-12 18:45:47.606674

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '53a2b3bc6e4f'
down_revision = '7e2ce598bb4b'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add bot_email_id column to email_messages table to track which bot received/replied to the email
    op.add_column('email_messages', sa.Column('bot_email_id', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_email_messages_bot_email', 'email_messages', 'bot_emails', ['bot_email_id'], ['id'], ondelete='SET NULL')
    op.create_index(op.f('ix_email_messages_bot_email_id'), 'email_messages', ['bot_email_id'], unique=False)
    
    # Add is_bot_reply column to indicate if this message is a bot's automated reply
    op.add_column('email_messages', sa.Column('is_bot_reply', sa.Boolean(), nullable=False, server_default='false'))
    
    # Add use_bot_system column to warmup_campaigns to enable/disable bot-based warmup
    op.add_column('warmup_campaigns', sa.Column('use_bot_system', sa.Boolean(), nullable=False, server_default='true'))


def downgrade() -> None:
    op.drop_column('warmup_campaigns', 'use_bot_system')
    op.drop_column('email_messages', 'is_bot_reply')
    op.drop_index(op.f('ix_email_messages_bot_email_id'), table_name='email_messages')
    op.drop_constraint('fk_email_messages_bot_email', 'email_messages', type_='foreignkey')
    op.drop_column('email_messages', 'bot_email_id')
