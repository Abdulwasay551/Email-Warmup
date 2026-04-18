"""add_warmup_tracking_fields

Revision ID: 0c40bdcb8bf3
Revises: 9d8e7f6a5b4c
Create Date: 2026-01-19 19:02:04.092959

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = '0c40bdcb8bf3'
down_revision = '9d8e7f6a5b4c'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add last_volume_increase_date to warmup_campaigns
    op.add_column('warmup_campaigns', 
        sa.Column('last_volume_increase_date', sa.Date(), nullable=True))
    
    # Add last_stage_update to email_inboxes
    op.add_column('email_inboxes', 
        sa.Column('last_stage_update', sa.DateTime(timezone=True), nullable=True))
    
    # Create system_settings table for admin-configurable values
    op.create_table('system_settings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('setting_key', sa.String(255), nullable=False),
        sa.Column('setting_value', sa.Text(), nullable=True),
        sa.Column('setting_type', sa.String(50), nullable=False),  # 'int', 'float', 'bool', 'string'
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('setting_key')
    )
    
    # Insert default warmup settings
    op.execute("""
        INSERT INTO system_settings (setting_key, setting_value, setting_type, description) VALUES
        ('warmup_increment_days', '7', 'int', 'Days between volume increases'),
        ('warmup_increment_amount', '15', 'int', 'Number of emails to add per increment'),
        ('min_daily_emails', '5', 'int', 'Minimum emails per day'),
        ('max_daily_emails', '100', 'int', 'Maximum emails per day'),
        ('max_spam_complaint_rate', '0.01', 'float', 'Maximum allowed spam complaint rate'),
        ('max_bounce_rate', '0.05', 'float', 'Maximum allowed bounce rate'),
        ('auto_pause_on_spam', 'true', 'bool', 'Auto-pause campaigns on spam detection')
    """)


def downgrade() -> None:
    op.drop_table('system_settings')
    op.drop_column('email_inboxes', 'last_stage_update')
    op.drop_column('warmup_campaigns', 'last_volume_increase_date')
