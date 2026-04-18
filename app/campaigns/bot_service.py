"""
Email warmup service with bot-based reply system

This service implements the new warmup flow:
1. User emails → Bot emails (from user's connected inbox)
2. Bot checks inbox and spam folder for user emails
3. Bot replies back to user (using AI or templates)
4. Multiple users can email multiple bots for distributed warmup
"""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_
from sqlalchemy.orm import selectinload
from typing import List, Optional, Tuple, Dict
from datetime import date, datetime, timedelta
import random
import logging

from app.db.models import (
    WarmupCampaign, CampaignInbox, EmailInbox, EmailMessage, BotEmail,
    CampaignStatus, InboxRole, EmailDirection, InboxStatus, BotEmailStatus,
    UserBotAssignment, EmailTemplate
)
from app.core.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)


async def get_available_bots(db: AsyncSession) -> List[BotEmail]:
    """Get all active bot emails that can receive messages"""
    result = await db.execute(
        select(BotEmail)
        .where(
            and_(
                BotEmail.status == BotEmailStatus.ACTIVE,
                BotEmail.is_healthy == True
            )
        )
    )
    return result.scalars().all()


async def assign_user_inbox_to_bots(
    db: AsyncSession,
    user_id: int,
    inbox_id: int,
    inbox_email: str,
    num_bots: int = 3
) -> List[UserBotAssignment]:
    """
    Assign a user's inbox to multiple bot emails for distributed warmup
    
    Args:
        user_id: The user ID
        inbox_id: The user's inbox ID
        inbox_email: The user's email address
        num_bots: Number of different bots to assign (default 3 for distribution)
    
    Returns:
        List of UserBotAssignment records
    """
    # Get available bots
    bots = await get_available_bots(db)
    
    if len(bots) < num_bots:
        logger.warning(f"Only {len(bots)} bots available, requested {num_bots}")
        num_bots = len(bots)
    
    if num_bots == 0:
        raise ValueError("No active bots available. Admin must configure bot emails first.")
    
    # Select random bots
    selected_bots = random.sample(bots, num_bots)
    
    assignments = []
    for bot in selected_bots:
        # Check if assignment already exists
        result = await db.execute(
            select(UserBotAssignment).where(
                and_(
                    UserBotAssignment.user_id == user_id,
                    UserBotAssignment.bot_email_id == bot.id,
                    UserBotAssignment.user_email_address == inbox_email
                )
            )
        )
        existing = result.scalar_one_or_none()
        
        if not existing:
            assignment = UserBotAssignment(
                user_id=user_id,
                bot_email_id=bot.id,
                user_email_address=inbox_email,
                is_active=True,
                check_spam=True,
                auto_report_not_spam=True
            )
            db.add(assignment)
            assignments.append(assignment)
            logger.info(f"Assigned user inbox {inbox_email} to bot {bot.email_address}")
        else:
            assignments.append(existing)
    
    await db.commit()
    return assignments


async def get_bot_assignments_for_user(
    db: AsyncSession,
    user_id: int,
    inbox_email: str
) -> List[BotEmail]:
    """Get all bot emails assigned to a specific user inbox"""
    result = await db.execute(
        select(BotEmail)
        .join(UserBotAssignment)
        .where(
            and_(
                UserBotAssignment.user_id == user_id,
                UserBotAssignment.user_email_address == inbox_email,
                UserBotAssignment.is_active == True,
                BotEmail.status == BotEmailStatus.ACTIVE
            )
        )
    )
    return result.scalars().all()


async def calculate_daily_bot_send_quota(
    db: AsyncSession,
    campaign: WarmupCampaign
) -> int:
    """Calculate how many emails can be sent to bots today"""
    today = date.today()
    
    # Count emails sent today from this campaign
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
    
    remaining = campaign.current_daily_volume - sent_today
    return max(0, remaining)


async def select_user_to_bot_pairs(
    db: AsyncSession,
    campaign: WarmupCampaign,
    count: int
) -> List[Dict]:
    """
    Select user inbox → bot email pairs for sending
    
    Returns:
        List of dicts with keys: from_inbox_id, to_bot_id, to_bot_email
    """
    # Get campaign inboxes (user inboxes)
    result = await db.execute(
        select(EmailInbox)
        .join(CampaignInbox)
        .where(
            and_(
                CampaignInbox.campaign_id == campaign.id,
                CampaignInbox.is_active == True,
                EmailInbox.status == InboxStatus.ACTIVE
            )
        )
    )
    user_inboxes = result.scalars().all()
    
    if not user_inboxes:
        logger.warning(f"No user inboxes available for campaign {campaign.id}")
        return []
    
    # Get all available bots
    bots = await get_available_bots(db)
    
    if not bots:
        logger.error("No active bot emails available!")
        return []
    
    pairs = []
    today = date.today()
    
    # Get pairs already used today
    result = await db.execute(
        select(EmailMessage.from_inbox_id, EmailMessage.bot_email_id)
        .where(
            and_(
                EmailMessage.campaign_id == campaign.id,
                func.date(EmailMessage.sent_at) == today,
                EmailMessage.bot_email_id.isnot(None)
            )
        )
    )
    used_today = set(result.all())
    
    attempts = 0
    while len(pairs) < count and attempts < count * 10:
        user_inbox = random.choice(user_inboxes)
        bot = random.choice(bots)
        
        pair_key = (user_inbox.id, bot.id)
        
        if pair_key not in used_today:
            # Check user inbox daily limit
            result = await db.execute(
                select(func.count(EmailMessage.id))
                .where(
                    and_(
                        EmailMessage.from_inbox_id == user_inbox.id,
                        func.date(EmailMessage.sent_at) == today
                    )
                )
            )
            inbox_sent_today = result.scalar() or 0
            
            if inbox_sent_today < user_inbox.daily_send_limit:
                pairs.append({
                    'from_inbox_id': user_inbox.id,
                    'to_bot_id': bot.id,
                    'to_bot_email': bot.email_address
                })
                used_today.add(pair_key)
        
        attempts += 1
    
    return pairs


async def get_email_template(
    db: AsyncSession,
    category: str = "engagement"
) -> Optional[EmailTemplate]:
    """Get a random active template from a category"""
    result = await db.execute(
        select(EmailTemplate)
        .where(
            and_(
                EmailTemplate.is_active == True,
                EmailTemplate.category == category
            )
        )
    )
    templates = result.scalars().all()
    
    if templates:
        return random.choice(templates)
    return None


# Keep existing campaign management functions from original service.py
# Just import and re-export them for compatibility
