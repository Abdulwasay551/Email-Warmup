from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import date, datetime
from app.db.models import CampaignStatus, InboxRole


class CampaignBase(BaseModel):
    """Base campaign schema"""
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    target_daily_volume: int = Field(default=50, ge=5, le=200)
    use_ai_replies: bool = True
    reply_rate: float = Field(default=0.7, ge=0.0, le=1.0)


class CampaignCreate(CampaignBase):
    """Schema for creating campaign"""
    inbox_ids: List[int] = Field(..., min_items=1)
    start_date: Optional[date] = None


class CampaignResponse(CampaignBase):
    """Schema for campaign response"""
    id: int
    user_id: int
    start_date: Optional[date]
    end_date: Optional[date]
    current_daily_volume: int
    status: CampaignStatus
    last_run_at: Optional[datetime]
    created_at: datetime
    
    class Config:
        from_attributes = True


class CampaignUpdate(BaseModel):
    """Schema for updating campaign"""
    name: Optional[str] = None
    status: Optional[CampaignStatus] = None
    target_daily_volume: Optional[int] = Field(None, ge=5, le=200)
    use_ai_replies: Optional[bool] = None
    reply_rate: Optional[float] = Field(None, ge=0.0, le=1.0)


class CampaignStatusUpdate(BaseModel):
    """Schema for updating campaign status"""
    status: CampaignStatus


class CampaignStats(BaseModel):
    """Campaign statistics"""
    campaign_id: int
    total_emails_sent: int
    total_emails_received: int
    total_opened: int
    total_replied: int
    total_spam: int
    open_rate: float
    reply_rate: float
    spam_rate: float
    active_inboxes: int
    days_running: int


class InboxPair(BaseModel):
    """Inbox pair for sending"""
    from_inbox_id: int
    to_inbox_id: int
    from_email: str
    to_email: str
