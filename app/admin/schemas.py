"""Admin schemas"""
from pydantic import BaseModel, EmailStr, ConfigDict
from datetime import datetime
from typing import Optional, List
from app.db.models import BotEmailStatus, EmailProvider


class BotEmailCreate(BaseModel):
    """Schema for creating bot email"""
    email_address: EmailStr
    provider: EmailProvider
    client_id: str
    client_secret: str
    
    
class BotEmailUpdate(BaseModel):
    """Schema for updating bot email"""
    status: Optional[BotEmailStatus] = None
    client_id: Optional[str] = None
    client_secret: Optional[str] = None


class BotEmailResponse(BaseModel):
    """Schema for bot email response"""
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    email_address: str
    provider: EmailProvider
    status: BotEmailStatus
    last_check_at: Optional[datetime] = None
    last_error: Optional[str] = None
    total_emails_processed: int
    spam_moved_to_inbox: int
    is_healthy: bool
    consecutive_errors: int
    created_at: datetime
    updated_at: Optional[datetime] = None


class UserBotAssignmentCreate(BaseModel):
    """Schema for creating user bot assignment"""
    user_email_address: EmailStr
    bot_email_id: int
    check_spam: bool = True
    auto_report_not_spam: bool = True


class UserBotAssignmentResponse(BaseModel):
    """Schema for user bot assignment response"""
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    user_id: int
    bot_email_id: int
    user_email_address: str
    is_active: bool
    check_spam: bool
    auto_report_not_spam: bool
    emails_received: int
    emails_in_spam: int
    spam_reports_made: int
    created_at: datetime


class BotActivityResponse(BaseModel):
    """Schema for bot activity response"""
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    bot_email_id: int
    activity_type: str
    from_email: Optional[str] = None
    subject: Optional[str] = None
    was_in_spam: bool
    action_taken: Optional[str] = None
    details: Optional[str] = None
    created_at: datetime


class BotHealthStatus(BaseModel):
    """Schema for overall bot health status"""
    total_bots: int
    active_bots: int
    unhealthy_bots: int
    total_emails_processed_today: int
    total_spam_reported_today: int
    bots: List[BotEmailResponse]


class UserCreate(BaseModel):
    """Schema for creating user (admin only)"""
    email: EmailStr
    password: str
    full_name: Optional[str] = None
    role: str = "user"


class UserResponse(BaseModel):
    """Schema for user response"""
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    email: str
    full_name: Optional[str] = None
    role: str
    is_active: bool
    created_at: datetime
    last_login_at: Optional[datetime] = None


class CampaignResponse(BaseModel):
    """Schema for campaign response"""
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    user_id: int
    name: str
    status: str
    emails_sent: int
    emails_delivered: int
    emails_opened: int
    emails_replied: int
    emails_bounced: int
    emails_spam_reported: int
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class AnalyticsSummary(BaseModel):
    """Schema for analytics summary"""
    total_users: int
    active_users: int
    total_campaigns: int
    active_campaigns: int
    total_emails_sent: int
    total_emails_today: int
    avg_delivery_rate: float
    avg_open_rate: float
    avg_reply_rate: float


class EmailTemplateCreate(BaseModel):
    """Schema for creating email template"""
    name: str
    subject: str
    body: str
    category: str  # welcome, follow-up, engagement, re-engagement, newsletter, custom
    variables: Optional[List[str]] = []


class EmailTemplateUpdate(BaseModel):
    """Schema for updating email template"""
    name: Optional[str] = None
    subject: Optional[str] = None
    body: Optional[str] = None
    category: Optional[str] = None
    variables: Optional[List[str]] = None
    is_active: Optional[bool] = None


class EmailTemplateResponse(BaseModel):
    """Schema for email template response"""
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    name: str
    subject: str
    body: str
    category: str
    variables: Optional[str] = None  # JSON string
    is_active: bool
    times_used: int
    last_used_at: Optional[datetime] = None
    created_at: datetime
    updated_at: Optional[datetime] = None


# ============================================================================
# TASK CONFIGURATION SCHEMAS (Dynamic Scheduling)
# ============================================================================

class TaskConfigResponse(BaseModel):
    """Schema for task configuration response"""
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    task_name: str
    display_name: str
    description: Optional[str] = None
    interval_minutes: int
    is_enabled: bool
    last_run: Optional[datetime] = None
    next_run: Optional[datetime] = None
    created_at: datetime
    updated_at: Optional[datetime] = None


class TaskConfigUpdate(BaseModel):
    """Schema for updating task configuration"""
    interval_minutes: Optional[int] = None
    is_enabled: Optional[bool] = None
    description: Optional[str] = None


# ============================================================================
# SYSTEM SETTINGS SCHEMAS
# ============================================================================

class WarmupSettingsResponse(BaseModel):
    """Schema for warmup settings response"""
    warmup_increment_days: int
    warmup_increment_amount: int
    min_daily_emails: int
    max_daily_emails: int
    max_spam_complaint_rate: float
    max_bounce_rate: float
    auto_pause_on_spam: bool


class WarmupSettingsUpdate(BaseModel):
    """Schema for updating warmup settings"""
    warmup_increment_days: Optional[int] = None
    warmup_increment_amount: Optional[int] = None
    min_daily_emails: Optional[int] = None
    max_daily_emails: Optional[int] = None
    max_spam_complaint_rate: Optional[float] = None
    max_bounce_rate: Optional[float] = None
    auto_pause_on_spam: Optional[bool] = None

