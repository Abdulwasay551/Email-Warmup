from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_
from sqlalchemy.orm import selectinload
from typing import List, Optional, Tuple
from datetime import date, datetime, timedelta
import random

from app.db.models import (
    WarmupCampaign, CampaignInbox, EmailInbox, EmailMessage,
    CampaignStatus, InboxRole, EmailDirection, InboxStatus
)
from app.campaigns.schemas import InboxPair
from app.core.config import get_settings

settings = get_settings()


async def get_campaign_by_id(
    db: AsyncSession,
    campaign_id: int,
    user_id: int
) -> Optional[WarmupCampaign]:
    """Get campaign by ID for specific user"""
    result = await db.execute(
        select(WarmupCampaign)
        .options(selectinload(WarmupCampaign.campaign_inboxes))
        .where(
            WarmupCampaign.id == campaign_id,
            WarmupCampaign.user_id == user_id
        )
    )
    return result.scalar_one_or_none()


async def get_user_campaigns(
    db: AsyncSession,
    user_id: int
) -> List[WarmupCampaign]:
    """Get all campaigns for a user"""
    result = await db.execute(
        select(WarmupCampaign)
        .where(WarmupCampaign.user_id == user_id)
        .order_by(WarmupCampaign.created_at.desc())
    )
    return result.scalars().all()


async def create_campaign(
    db: AsyncSession,
    user_id: int,
    name: str,
    description: Optional[str],
    target_daily_volume: int,
    inbox_ids: List[int],
    use_ai_replies: bool,
    reply_rate: float,
    start_date: Optional[date]
) -> WarmupCampaign:
    """Create new campaign"""
    campaign = WarmupCampaign(
        user_id=user_id,
        name=name,
        description=description,
        target_daily_volume=target_daily_volume,
        current_daily_volume=settings.min_daily_emails,
        use_ai_replies=use_ai_replies,
        reply_rate=reply_rate,
        start_date=start_date or date.today(),
        status=CampaignStatus.DRAFT
    )
    
    db.add(campaign)
    await db.flush()
    
    # Add inboxes to campaign
    for inbox_id in inbox_ids:
        campaign_inbox = CampaignInbox(
            campaign_id=campaign.id,
            inbox_id=inbox_id,
            role=InboxRole.MIXED  # All inboxes can send and receive
        )
        db.add(campaign_inbox)
    
    await db.flush()
    await db.refresh(campaign)
    
    return campaign


async def update_campaign_status(
    db: AsyncSession,
    campaign_id: int,
    status: CampaignStatus
) -> Optional[WarmupCampaign]:
    """Update campaign status"""
    campaign = await db.get(WarmupCampaign, campaign_id)
    if campaign:
        campaign.status = status
        if status == CampaignStatus.RUNNING and not campaign.start_date:
            campaign.start_date = date.today()
        await db.flush()
        await db.refresh(campaign)
    return campaign


async def get_active_campaigns(db: AsyncSession) -> List[WarmupCampaign]:
    """Get all running campaigns"""
    result = await db.execute(
        select(WarmupCampaign)
        .options(selectinload(WarmupCampaign.campaign_inboxes))
        .where(WarmupCampaign.status == CampaignStatus.RUNNING)
    )
    return result.scalars().all()


async def get_campaign_inboxes(
    db: AsyncSession,
    campaign_id: int
) -> List[EmailInbox]:
    """Get all active inboxes for a campaign"""
    result = await db.execute(
        select(EmailInbox)
        .join(CampaignInbox)
        .where(
            and_(
                CampaignInbox.campaign_id == campaign_id,
                CampaignInbox.is_active == True,
                EmailInbox.status == InboxStatus.ACTIVE
            )
        )
    )
    return result.scalars().all()


async def calculate_daily_send_quota(
    db: AsyncSession,
    campaign: WarmupCampaign
) -> int:
    """Calculate how many emails can be sent today"""
    # Check if we've already sent emails today
    today = date.today()
    
    result = await db.execute(
        select(func.count(EmailMessage.id))
        .where(
            and_(
                EmailMessage.campaign_id == campaign.id,
                func.date(EmailMessage.sent_at) == today,
                EmailMessage.direction == EmailDirection.OUTBOUND
            )
        )
    )
    sent_today = result.scalar() or 0
    
    # Calculate remaining quota
    remaining = campaign.current_daily_volume - sent_today
    return max(0, remaining)


async def select_inbox_pairs(
    db: AsyncSession,
    campaign: WarmupCampaign,
    count: int
) -> List[InboxPair]:
    """Select random inbox pairs for sending"""
    inboxes = await get_campaign_inboxes(db, campaign.id)
    
    if len(inboxes) < 2:
        return []
    
    pairs = []
    used_today = set()
    
    # Get pairs already used today
    today = date.today()
    result = await db.execute(
        select(EmailMessage.from_inbox_id, EmailMessage.to_inbox_id)
        .where(
            and_(
                EmailMessage.campaign_id == campaign.id,
                func.date(EmailMessage.sent_at) == today
            )
        )
    )
    used_today = set(result.all())
    
    # Try to create unique pairs
    attempts = 0
    while len(pairs) < count and attempts < count * 10:
        from_inbox = random.choice(inboxes)
        to_inbox = random.choice([i for i in inboxes if i.id != from_inbox.id])
        
        pair_key = (from_inbox.id, to_inbox.id)
        
        # Avoid using same pair twice in one day
        if pair_key not in used_today:
            # Check inbox daily limit
            result = await db.execute(
                select(func.count(EmailMessage.id))
                .where(
                    and_(
                        EmailMessage.from_inbox_id == from_inbox.id,
                        func.date(EmailMessage.sent_at) == today
                    )
                )
            )
            sent_today_from_inbox = result.scalar() or 0
            
            if sent_today_from_inbox < from_inbox.daily_send_limit:
                pairs.append(InboxPair(
                    from_inbox_id=from_inbox.id,
                    to_inbox_id=to_inbox.id,
                    from_email=from_inbox.email_address,
                    to_email=to_inbox.email_address
                ))
                used_today.add(pair_key)
        
        attempts += 1
    
    return pairs


async def increment_campaign_volume(
    db: AsyncSession,
    campaign: WarmupCampaign
) -> None:
    """Gradually increase campaign volume"""
    if not campaign.start_date:
        return
    
    days_running = (date.today() - campaign.start_date).days
    
    # Increment every N days
    if days_running > 0 and days_running % settings.warmup_increment_days == 0:
        new_volume = min(
            campaign.current_daily_volume + settings.warmup_increment_amount,
            campaign.target_daily_volume,
            settings.max_daily_emails
        )
        
        if new_volume != campaign.current_daily_volume:
            campaign.current_daily_volume = new_volume
            await db.flush()


async def get_campaign_stats(
    db: AsyncSession,
    campaign_id: int
) -> dict:
    """Get campaign statistics"""
    # Total emails sent
    result = await db.execute(
        select(func.count(EmailMessage.id))
        .where(
            and_(
                EmailMessage.campaign_id == campaign_id,
                EmailMessage.direction == EmailDirection.OUTBOUND
            )
        )
    )
    total_sent = result.scalar() or 0
    
    # Total opened
    result = await db.execute(
        select(func.count(EmailMessage.id))
        .where(
            and_(
                EmailMessage.campaign_id == campaign_id,
                EmailMessage.opened == True
            )
        )
    )
    total_opened = result.scalar() or 0
    
    # Total replied
    result = await db.execute(
        select(func.count(EmailMessage.id))
        .where(
            and_(
                EmailMessage.campaign_id == campaign_id,
                EmailMessage.replied == True
            )
        )
    )
    total_replied = result.scalar() or 0
    
    # Total spam
    result = await db.execute(
        select(func.count(EmailMessage.id))
        .where(
            and_(
                EmailMessage.campaign_id == campaign_id,
                EmailMessage.spam_reported == True
            )
        )
    )
    total_spam = result.scalar() or 0
    
    # Active inboxes
    result = await db.execute(
        select(func.count(CampaignInbox.id))
        .where(
            and_(
                CampaignInbox.campaign_id == campaign_id,
                CampaignInbox.is_active == True
            )
        )
    )
    active_inboxes = result.scalar() or 0
    
    return {
        "total_sent": total_sent,
        "total_opened": total_opened,
        "total_replied": total_replied,
        "total_spam": total_spam,
        "open_rate": (total_opened / total_sent * 100) if total_sent > 0 else 0,
        "reply_rate": (total_replied / total_sent * 100) if total_sent > 0 else 0,
        "spam_rate": (total_spam / total_sent * 100) if total_sent > 0 else 0,
        "active_inboxes": active_inboxes
    }
