from sqlalchemy import Column, Integer, String, Boolean, DateTime, Float, ForeignKey, Text, Enum, Date
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from datetime import datetime
import enum
import sqlalchemy
from app.core.database import Base


class UserRole(str, enum.Enum):
    """User role enumeration"""
    ADMIN = "admin"
    USER = "user"


class InboxStatus(str, enum.Enum):
    """Inbox status enumeration"""
    ACTIVE = "active"
    PAUSED = "paused"
    DISCONNECTED = "disconnected"
    ERROR = "error"


class CampaignStatus(str, enum.Enum):
    """Campaign status enumeration"""
    DRAFT = "draft"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"


class EmailProvider(str, enum.Enum):
    """Email provider enumeration"""
    GMAIL = "gmail"
    OUTLOOK = "outlook"
    CUSTOM = "custom"


class InboxRole(str, enum.Enum):
    """Inbox role in campaign"""
    SENDER = "sender"
    RECEIVER = "receiver"
    MIXED = "mixed"


class EmailDirection(str, enum.Enum):
    """Email direction"""
    OUTBOUND = "outbound"
    INBOUND = "inbound"


class BotEmailStatus(str, enum.Enum):
    """Bot email status"""
    ACTIVE = "active"
    PAUSED = "paused"
    ERROR = "error"
    DISCONNECTED = "disconnected"


class User(Base):
    """User model"""
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    full_name = Column(String(255))
    role = Column(Enum(UserRole), default=UserRole.USER, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    inboxes = relationship("EmailInbox", back_populates="user", cascade="all, delete-orphan")
    campaigns = relationship("WarmupCampaign", back_populates="user", cascade="all, delete-orphan")


class EmailInbox(Base):
    """Connected email inbox model"""
    __tablename__ = "email_inboxes"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    email_address = Column(String(255), unique=True, index=True, nullable=False)
    provider = Column(Enum(EmailProvider), default=EmailProvider.GMAIL, nullable=False)
    domain = Column(String(255), index=True)
    
    # OAuth tokens (encrypted)
    access_token = Column(Text)  # Encrypted
    refresh_token = Column(Text)  # Encrypted
    token_expiry = Column(DateTime(timezone=True))
    
    # Status and limits
    status = Column(Enum(InboxStatus), default=InboxStatus.ACTIVE, nullable=False)
    daily_send_limit = Column(Integer, default=50)
    warmup_stage = Column(Integer, default=1)  # Progressive warm-up stage
    last_stage_update = Column(DateTime(timezone=True))  # Track last stage update
    
    # Metrics
    total_sent = Column(Integer, default=0)
    total_received = Column(Integer, default=0)
    last_activity = Column(DateTime(timezone=True))
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    user = relationship("User", back_populates="inboxes")
    campaign_inboxes = relationship("CampaignInbox", back_populates="inbox", cascade="all, delete-orphan")
    sent_messages = relationship("EmailMessage", foreign_keys="EmailMessage.from_inbox_id", back_populates="from_inbox")
    received_messages = relationship("EmailMessage", foreign_keys="EmailMessage.to_inbox_id", back_populates="to_inbox")
    reputation_stats = relationship("ReputationStats", back_populates="inbox", cascade="all, delete-orphan")


class WarmupCampaign(Base):
    """Warm-up campaign model"""
    __tablename__ = "warmup_campaigns"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    
    # Campaign settings
    start_date = Column(Date)
    end_date = Column(Date)
    target_daily_volume = Column(Integer, default=50)  # Target emails per day
    current_daily_volume = Column(Integer, default=5)  # Current sending volume
    last_volume_increase_date = Column(Date)  # Track last time volume was increased
    
    # AI settings
    use_ai_replies = Column(Boolean, default=True)
    reply_rate = Column(Float, default=0.7)  # 70% of emails get replies
    use_bot_system = Column(Boolean, default=True)  # Use admin bot emails for replies
    
    # Status
    status = Column(Enum(CampaignStatus), default=CampaignStatus.DRAFT, nullable=False)
    last_run_at = Column(DateTime(timezone=True))
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    user = relationship("User", back_populates="campaigns")
    campaign_inboxes = relationship("CampaignInbox", back_populates="campaign", cascade="all, delete-orphan")
    messages = relationship("EmailMessage", back_populates="campaign", cascade="all, delete-orphan")


class CampaignInbox(Base):
    """Many-to-many relationship between campaigns and inboxes"""
    __tablename__ = "campaign_inboxes"
    
    id = Column(Integer, primary_key=True, index=True)
    campaign_id = Column(Integer, ForeignKey("warmup_campaigns.id", ondelete="CASCADE"), nullable=False)
    inbox_id = Column(Integer, ForeignKey("email_inboxes.id", ondelete="CASCADE"), nullable=False)
    role = Column(Enum(InboxRole), default=InboxRole.MIXED, nullable=False)
    is_active = Column(Boolean, default=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationships
    campaign = relationship("WarmupCampaign", back_populates="campaign_inboxes")
    inbox = relationship("EmailInbox", back_populates="campaign_inboxes")


class EmailMessage(Base):
    """Email message tracking model"""
    __tablename__ = "email_messages"
    
    id = Column(Integer, primary_key=True, index=True)
    campaign_id = Column(Integer, ForeignKey("warmup_campaigns.id", ondelete="CASCADE"), nullable=False)
    from_inbox_id = Column(Integer, ForeignKey("email_inboxes.id", ondelete="CASCADE"), nullable=False)
    to_inbox_id = Column(Integer, ForeignKey("email_inboxes.id", ondelete="CASCADE"), nullable=False)
    bot_email_id = Column(Integer, ForeignKey("bot_emails.id", ondelete="SET NULL"), nullable=True, index=True)
    
    # Message identifiers
    message_id = Column(String(255), unique=True, index=True)  # Provider message ID
    thread_id = Column(String(255), index=True)  # Conversation thread
    
    # Content
    subject = Column(String(500), nullable=False)
    body = Column(Text, nullable=False)
    direction = Column(Enum(EmailDirection), nullable=False)
    
    # Engagement metrics
    opened = Column(Boolean, default=False)
    replied = Column(Boolean, default=False)
    spam_reported = Column(Boolean, default=False)
    bounced = Column(Boolean, default=False)
    
    # AI generation
    ai_generated = Column(Boolean, default=False)
    is_bot_reply = Column(Boolean, default=False)  # True if this is bot's automated reply
    
    # Timestamps
    sent_at = Column(DateTime(timezone=True), server_default=func.now())
    opened_at = Column(DateTime(timezone=True))
    replied_at = Column(DateTime(timezone=True))
    
    # Relationships
    campaign = relationship("WarmupCampaign", back_populates="messages")
    from_inbox = relationship("EmailInbox", foreign_keys=[from_inbox_id], back_populates="sent_messages")
    to_inbox = relationship("EmailInbox", foreign_keys=[to_inbox_id], back_populates="received_messages")
    bot_email = relationship("BotEmail")


class ReputationStats(Base):
    """Daily reputation statistics per inbox"""
    __tablename__ = "reputation_stats"
    
    id = Column(Integer, primary_key=True, index=True)
    inbox_id = Column(Integer, ForeignKey("email_inboxes.id", ondelete="CASCADE"), nullable=False)
    date = Column(Date, nullable=False, index=True)
    
    # Daily metrics
    emails_sent = Column(Integer, default=0)
    emails_received = Column(Integer, default=0)
    emails_opened = Column(Integer, default=0)
    emails_replied = Column(Integer, default=0)
    spam_complaints = Column(Integer, default=0)
    bounce_count = Column(Integer, default=0)
    
    # Calculated rates
    open_rate = Column(Float, default=0.0)
    reply_rate = Column(Float, default=0.0)
    spam_rate = Column(Float, default=0.0)
    bounce_rate = Column(Float, default=0.0)
    
    # Reputation score (0-100)
    reputation_score = Column(Float, default=50.0)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    inbox = relationship("EmailInbox", back_populates="reputation_stats")
    
    # Unique constraint: one record per inbox per day
    __table_args__ = (
        sqlalchemy.UniqueConstraint('inbox_id', 'date', name='unique_inbox_date'),
    )


class EmailTemplate(Base):
    """Email template model for manual email creation"""
    __tablename__ = "email_templates"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    subject = Column(String(500), nullable=False)
    body = Column(Text, nullable=False)
    category = Column(String(50), nullable=False)  # welcome, follow-up, engagement, re-engagement, newsletter, custom
    
    # Template variables (JSON array of variable names like ["first_name", "email", "company"])
    variables = Column(Text)  # Stored as JSON string
    
    # Status
    is_active = Column(Boolean, default=True)
    
    # Usage stats
    times_used = Column(Integer, default=0)
    last_used_at = Column(DateTime(timezone=True))
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class BotEmail(Base):
    """Bot email accounts managed by admin"""
    __tablename__ = "bot_emails"
    
    id = Column(Integer, primary_key=True, index=True)
    email_address = Column(String(255), unique=True, index=True, nullable=False)
    provider = Column(Enum(EmailProvider), default=EmailProvider.GMAIL, nullable=False)
    
    # OAuth credentials
    client_id = Column(Text, nullable=False)  # Encrypted
    client_secret = Column(Text, nullable=False)  # Encrypted
    access_token = Column(Text)  # Encrypted
    refresh_token = Column(Text)  # Encrypted
    token_expiry = Column(DateTime(timezone=True))
    
    # Webhook/Push notification support
    watch_history_id = Column(String(255), index=True)  # Gmail history ID for watch
    watch_expiration = Column(Integer)  # Expiration timestamp for watch
    
    # Status and monitoring
    status = Column(Enum(BotEmailStatus), default=BotEmailStatus.ACTIVE, nullable=False)
    last_check_at = Column(DateTime(timezone=True))
    last_error = Column(Text)
    
    # Statistics
    total_emails_processed = Column(Integer, default=0)
    spam_moved_to_inbox = Column(Integer, default=0)
    last_activity = Column(DateTime(timezone=True))
    
    # Health metrics
    is_healthy = Column(Boolean, default=True)
    consecutive_errors = Column(Integer, default=0)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    user_assignments = relationship("UserBotAssignment", back_populates="bot_email", cascade="all, delete-orphan")
    bot_activities = relationship("BotActivity", back_populates="bot_email", cascade="all, delete-orphan")


class UserBotAssignment(Base):
    """Assignment of user emails to bot emails for monitoring"""
    __tablename__ = "user_bot_assignments"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    bot_email_id = Column(Integer, ForeignKey("bot_emails.id", ondelete="CASCADE"), nullable=False)
    user_email_address = Column(String(255), nullable=False)  # The user's email that sends to this bot
    
    # Monitoring settings
    is_active = Column(Boolean, default=True)
    check_spam = Column(Boolean, default=True)  # Check spam folder
    auto_report_not_spam = Column(Boolean, default=True)  # Auto report as not spam
    
    # Statistics
    emails_received = Column(Integer, default=0)
    emails_in_spam = Column(Integer, default=0)
    spam_reports_made = Column(Integer, default=0)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    user = relationship("User")
    bot_email = relationship("BotEmail", back_populates="user_assignments")
    
    # Unique constraint
    __table_args__ = (
        sqlalchemy.UniqueConstraint('user_id', 'bot_email_id', 'user_email_address', name='unique_user_bot_assignment'),
    )


class BotActivity(Base):
    """Activity log for bot emails"""
    __tablename__ = "bot_activities"
    
    id = Column(Integer, primary_key=True, index=True)
    bot_email_id = Column(Integer, ForeignKey("bot_emails.id", ondelete="CASCADE"), nullable=False)
    
    activity_type = Column(String(50), nullable=False)  # email_received, spam_reported, error, etc.
    from_email = Column(String(255))  # Who sent the email
    subject = Column(String(500))
    was_in_spam = Column(Boolean, default=False)
    action_taken = Column(String(100))  # reported_not_spam, opened, etc.
    
    details = Column(Text)  # JSON details
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationships
    bot_email = relationship("BotEmail", back_populates="bot_activities")


class TaskConfiguration(Base):
    """Configuration for scheduled Celery tasks - allows dynamic interval control"""
    __tablename__ = "task_configurations"
    
    id = Column(Integer, primary_key=True, index=True)
    task_name = Column(String(255), unique=True, index=True, nullable=False)  # Celery task name
    display_name = Column(String(255), nullable=False)  # Human-readable name
    description = Column(Text)  # What this task does
    
    # Scheduling
    interval_minutes = Column(Integer, nullable=False)  # How often to run (in minutes)
    is_enabled = Column(Boolean, default=True, nullable=False)  # Can be disabled
    
    # Tracking
    last_run = Column(DateTime(timezone=True))  # Last execution time
    next_run = Column(DateTime(timezone=True))  # Next scheduled run
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class SystemSetting(Base):
    """System-wide configuration settings"""
    __tablename__ = "system_settings"
    
    id = Column(Integer, primary_key=True, index=True)
    setting_key = Column(String(255), unique=True, nullable=False)
    setting_value = Column(Text)
    setting_type = Column(String(50), nullable=False)  # 'int', 'float', 'bool', 'string'
    description = Column(Text)
    
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class SecurityEventType(str, enum.Enum):
    """Security event types for Cross-Account Protection"""
    TOKEN_REVOKED = "token_revoked"
    ACCOUNT_DISABLED = "account_disabled"
    ACCOUNT_ENABLED = "account_enabled"
    ACCOUNT_PURGED = "account_purged"
    CREDENTIAL_CHANGE = "credential_change"
    SESSIONS_REVOKED = "sessions_revoked"


class SecurityEventLog(Base):
    """Log of security events from Google Cross-Account Protection (CAP)"""
    __tablename__ = "security_event_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    
    # Event details
    event_type = Column(Enum(SecurityEventType), nullable=False, index=True)
    subject_email = Column(String(255), nullable=False, index=True)
    subject_id = Column(String(255))  # Google user ID (sub)
    
    # Impact
    user_inboxes_affected = Column(Integer, default=0)
    bot_emails_affected = Column(Integer, default=0)
    
    # Raw data
    raw_event_token = Column(Text)  # The original JWT token
    event_data = Column(Text)  # JSON of parsed event
    
    # Actions taken
    action_taken = Column(Text)
    reauthentication_required = Column(Boolean, default=False)
    
    # Timestamps
    event_issued_at = Column(DateTime(timezone=True))  # When Google issued the event
    received_at = Column(DateTime(timezone=True), server_default=func.now())  # When we received it
    processed_at = Column(DateTime(timezone=True))  # When we finished processing


class ReauthenticationRequest(Base):
    """Track reauthentication requests for disconnected accounts"""
    __tablename__ = "reauthentication_requests"
    
    id = Column(Integer, primary_key=True, index=True)
    
    # Target account
    email_address = Column(String(255), nullable=False, index=True)
    account_type = Column(String(50), nullable=False)  # 'user_inbox' or 'bot_email'
    account_id = Column(Integer, nullable=False)  # ID of the EmailInbox or BotEmail
    
    # Request details
    reason = Column(Text, nullable=False)  # Why reauthentication is needed
    security_event_id = Column(Integer, ForeignKey("security_event_logs.id"))  # Link to security event if applicable
    
    # Status
    status = Column(String(50), default='pending', nullable=False)  # pending, completed, expired
    reauth_url = Column(Text)  # OAuth URL for reauthentication
    
    # Notifications
    notification_sent = Column(Boolean, default=False)
    notification_sent_at = Column(DateTime(timezone=True))
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True))
    expires_at = Column(DateTime(timezone=True))  # Reauth request expires after 7 days
    
    # Relationships
    security_event = relationship("SecurityEventLog")


