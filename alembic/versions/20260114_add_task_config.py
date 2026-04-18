"""Add task configuration table

Revision ID: a1b2c3d4e5f6
Revises: 9d8e7f6a5b4c
Create Date: 2026-01-14

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = '9d8e7f6a5b4c'
branch_labels = None
depends_on = None


def upgrade():
    # Create task_configurations table
    op.create_table(
        'task_configurations',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('task_name', sa.String(255), unique=True, nullable=False, index=True),
        sa.Column('display_name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text()),
        sa.Column('interval_minutes', sa.Integer(), nullable=False),
        sa.Column('is_enabled', sa.Boolean(), default=True, nullable=False),
        sa.Column('last_run', sa.DateTime(timezone=True)),
        sa.Column('next_run', sa.DateTime(timezone=True)),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.func.now())
    )
    
    # Insert default task configurations
    op.execute("""
        INSERT INTO task_configurations (task_name, display_name, description, interval_minutes, is_enabled)
        VALUES 
        ('execute_bot_campaigns', 'Send Bot Warmup Emails', 'Sends warmup emails from user inboxes to bot emails', 30, true),
        ('monitor_bot_inboxes', 'Check Bot Inboxes (Polling)', 'Fallback polling to check bot inboxes for new emails', 30, true),
        ('refresh_gmail_watches', 'Refresh Gmail Watches', 'Renew Gmail push notification subscriptions (runs once daily)', 1440, true),
        ('monitor_inboxes', 'Monitor User Inboxes', 'Check user inbox health and metrics', 15, true),
        ('aggregate_daily_stats', 'Aggregate Statistics', 'Generate daily reputation and engagement reports', 1440, true),
        ('check_safety_limits', 'Check Safety Limits', 'Monitor spam rates and bounce rates', 30, true)
    """)


def downgrade():
    op.drop_table('task_configurations')
