from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime
from app.db.models import EmailProvider, InboxStatus


class InboxBase(BaseModel):
    """Base inbox schema"""
    email_address: EmailStr
    provider: EmailProvider = EmailProvider.GMAIL


class InboxCreate(InboxBase):
    """Schema for creating inbox"""
    pass


class InboxResponse(InboxBase):
    """Schema for inbox response"""
    id: int
    user_id: int
    domain: str
    status: InboxStatus
    daily_send_limit: int
    warmup_stage: int
    total_sent: int
    total_received: int
    last_activity: Optional[datetime]
    created_at: datetime
    
    class Config:
        from_attributes = True


class InboxUpdate(BaseModel):
    """Schema for updating inbox"""
    status: Optional[InboxStatus] = None
    daily_send_limit: Optional[int] = None


class OAuthCallbackData(BaseModel):
    """Schema for OAuth callback"""
    code: str
    state: Optional[str] = None
