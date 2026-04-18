"""Admin service functions"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
from sqlalchemy.orm import selectinload
from typing import List, Optional
from datetime import datetime, date, timedelta
from app.db.models import (
    BotEmail, UserBotAssignment, BotActivity, User, UserRole,
    BotEmailStatus, EmailTemplate
)
from app.core.security import hash_password
import json


async def get_all_bots(db: AsyncSession) -> List[BotEmail]:
    """Get all bot emails"""
    result = await db.execute(
        select(BotEmail)
        .options(selectinload(BotEmail.user_assignments))
        .order_by(BotEmail.created_at.desc())
    )
    return result.scalars().all()


async def get_bot_by_id(db: AsyncSession, bot_id: int) -> Optional[BotEmail]:
    """Get bot email by ID"""
    result = await db.execute(
        select(BotEmail)
        .options(selectinload(BotEmail.user_assignments))
        .where(BotEmail.id == bot_id)
    )
    return result.scalar_one_or_none()


async def get_bot_by_email(db: AsyncSession, email: str) -> Optional[BotEmail]:
    """Get bot email by email address"""
    result = await db.execute(
        select(BotEmail).where(BotEmail.email_address == email)
    )
    return result.scalar_one_or_none()


async def create_bot_email(
    db: AsyncSession,
    email_address: str,
    provider: str,
    client_id: str,
    client_secret: str
) -> BotEmail:
    """Create new bot email"""
    # In production, encrypt the credentials
    bot = BotEmail(
        email_address=email_address,
        provider=provider,
        client_id=client_id,
        client_secret=client_secret,
        status=BotEmailStatus.ACTIVE
    )
    
    db.add(bot)
    await db.flush()
    await db.refresh(bot)
    
    return bot


async def update_bot_email(
    db: AsyncSession,
    bot_id: int,
    status: Optional[BotEmailStatus] = None,
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None
) -> Optional[BotEmail]:
    """Update bot email"""
    bot = await get_bot_by_id(db, bot_id)
    if not bot:
        return None
    
    if status is not None:
        bot.status = status
    if client_id is not None:
        bot.client_id = client_id
    if client_secret is not None:
        bot.client_secret = client_secret
    
    bot.updated_at = datetime.utcnow()
    await db.flush()
    await db.refresh(bot)
    
    return bot


async def delete_bot_email(db: AsyncSession, bot_id: int) -> bool:
    """Delete bot email"""
    bot = await get_bot_by_id(db, bot_id)
    if not bot:
        return False
    
    await db.delete(bot)
    await db.flush()
    return True


async def update_bot_oauth_tokens(
    db: AsyncSession,
    bot_id: int,
    access_token: str,
    refresh_token: str,
    email_address: str,
    token_expiry: Optional[datetime] = None
) -> Optional[BotEmail]:
    """Update bot OAuth tokens after successful authentication"""
    from app.core.security import encrypt_data
    from datetime import datetime, timezone
    
    bot = await get_bot_by_id(db, bot_id)
    if not bot:
        return None
    
    # Encrypt tokens before storing
    bot.access_token = encrypt_data(access_token)
    bot.refresh_token = encrypt_data(refresh_token) if refresh_token else None
    bot.email_address = email_address
    bot.token_expiry = token_expiry
    
    # Update status to ACTIVE
    bot.status = BotEmailStatus.ACTIVE
    bot.is_healthy = True
    bot.consecutive_errors = 0
    bot.last_error = None
    bot.last_check_at = datetime.now(timezone.utc)
    bot.updated_at = datetime.now(timezone.utc)
    
    await db.flush()
    await db.refresh(bot)
    
    return bot


async def create_user_bot_assignment(
    db: AsyncSession,
    user_id: int,
    bot_email_id: int,
    user_email_address: str,
    check_spam: bool = True,
    auto_report_not_spam: bool = True
) -> UserBotAssignment:
    """Create user bot assignment"""
    assignment = UserBotAssignment(
        user_id=user_id,
        bot_email_id=bot_email_id,
        user_email_address=user_email_address,
        check_spam=check_spam,
        auto_report_not_spam=auto_report_not_spam
    )
    
    db.add(assignment)
    await db.flush()
    await db.refresh(assignment)
    
    return assignment


async def get_user_assignments(
    db: AsyncSession,
    user_id: int
) -> List[UserBotAssignment]:
    """Get all bot assignments for a user"""
    result = await db.execute(
        select(UserBotAssignment)
        .options(selectinload(UserBotAssignment.bot_email))
        .where(UserBotAssignment.user_id == user_id)
        .order_by(UserBotAssignment.created_at.desc())
    )
    return result.scalars().all()


async def get_bot_assignments(
    db: AsyncSession,
    bot_email_id: int
) -> List[UserBotAssignment]:
    """Get all user assignments for a bot"""
    result = await db.execute(
        select(UserBotAssignment)
        .where(UserBotAssignment.bot_email_id == bot_email_id)
        .order_by(UserBotAssignment.created_at.desc())
    )
    return result.scalars().all()


async def log_bot_activity(
    db: AsyncSession,
    bot_email_id: int,
    activity_type: str,
    from_email: Optional[str] = None,
    subject: Optional[str] = None,
    was_in_spam: bool = False,
    action_taken: Optional[str] = None,
    details: Optional[dict] = None
) -> BotActivity:
    """Log bot activity"""
    activity = BotActivity(
        bot_email_id=bot_email_id,
        activity_type=activity_type,
        from_email=from_email,
        subject=subject,
        was_in_spam=was_in_spam,
        action_taken=action_taken,
        details=json.dumps(details) if details else None
    )
    
    db.add(activity)
    await db.flush()
    
    return activity


async def get_bot_activities(
    db: AsyncSession,
    bot_email_id: int,
    limit: int = 100
) -> List[BotActivity]:
    """Get recent bot activities"""
    result = await db.execute(
        select(BotActivity)
        .where(BotActivity.bot_email_id == bot_email_id)
        .order_by(BotActivity.created_at.desc())
        .limit(limit)
    )
    return result.scalars().all()


async def get_bot_health_summary(db: AsyncSession) -> dict:
    """Get overall bot health summary"""
    today = date.today()
    
    # Count bots by status
    result = await db.execute(select(BotEmail))
    all_bots = result.scalars().all()
    
    total_bots = len(all_bots)
    active_bots = sum(1 for b in all_bots if b.status == BotEmailStatus.ACTIVE)
    unhealthy_bots = sum(1 for b in all_bots if not b.is_healthy)
    
    # Today's statistics
    result = await db.execute(
        select(func.sum(BotActivity.id))
        .where(
            and_(
                BotActivity.created_at >= datetime.combine(today, datetime.min.time()),
                BotActivity.activity_type == "email_received"
            )
        )
    )
    emails_today = result.scalar() or 0
    
    result = await db.execute(
        select(func.sum(BotActivity.id))
        .where(
            and_(
                BotActivity.created_at >= datetime.combine(today, datetime.min.time()),
                BotActivity.action_taken == "reported_not_spam"
            )
        )
    )
    spam_reported_today = result.scalar() or 0
    
    return {
        "total_bots": total_bots,
        "active_bots": active_bots,
        "unhealthy_bots": unhealthy_bots,
        "total_emails_processed_today": emails_today,
        "total_spam_reported_today": spam_reported_today
    }


async def create_user_admin(
    db: AsyncSession,
    email: str,
    password: str,
    full_name: Optional[str] = None,
    role: UserRole = UserRole.USER
) -> User:
    """Create user (admin function)"""
    hashed_password = hash_password(password)
    
    user = User(
        email=email,
        password_hash=hashed_password,
        full_name=full_name,
        role=role
    )
    
    db.add(user)
    await db.flush()
    await db.refresh(user)
    
    return user


async def get_all_users(db: AsyncSession) -> List[User]:
    """Get all users"""
    result = await db.execute(
        select(User).order_by(User.created_at.desc())
    )
    return result.scalars().all()


async def update_user_role(
    db: AsyncSession,
    user_id: int,
    role: UserRole
) -> Optional[User]:
    """Update user role"""
    result = await db.execute(
        select(User).where(User.id == user_id)
    )
    user = result.scalar_one_or_none()
    
    if not user:
        return None
    
    user.role = role
    user.updated_at = datetime.utcnow()
    await db.flush()
    await db.refresh(user)
    
    return user


async def get_all_campaigns(db: AsyncSession):
    """Get all campaigns"""
    from app.db.models import WarmupCampaign
    result = await db.execute(
        select(WarmupCampaign)
        .options(selectinload(WarmupCampaign.user))
        .order_by(WarmupCampaign.created_at.desc())
    )
    return result.scalars().all()


async def get_campaign_by_id(db: AsyncSession, campaign_id: int):
    """Get campaign by ID"""
    from app.db.models import WarmupCampaign
    result = await db.execute(
        select(WarmupCampaign)
        .options(selectinload(WarmupCampaign.user))
        .where(WarmupCampaign.id == campaign_id)
    )
    return result.scalar_one_or_none()


async def get_dashboard_stats(db: AsyncSession) -> dict:
    """Get dashboard statistics"""
    from app.db.models import WarmupCampaign, CampaignStatus
    from sqlalchemy import func, and_
    from datetime import datetime, date, timedelta
    
    # Total users
    result = await db.execute(select(func.count(User.id)))
    total_users = result.scalar() or 0
    
    # Active bots
    result = await db.execute(
        select(func.count(BotEmail.id))
        .where(BotEmail.status == BotEmailStatus.ACTIVE)
    )
    active_bots = result.scalar() or 0
    
    # Active campaigns
    result = await db.execute(
        select(func.count(WarmupCampaign.id))
        .where(WarmupCampaign.status == CampaignStatus.RUNNING)
    )
    active_campaigns = result.scalar() or 0
    
    # Emails today
    today = date.today()
    result = await db.execute(
        select(func.count(BotActivity.id))
        .where(
            and_(
                BotActivity.created_at >= datetime.combine(today, datetime.min.time()),
                BotActivity.activity_type == "email_received"
            )
        )
    )
    emails_today = result.scalar() or 0
    
    return {
        "total_users": total_users,
        "active_bots": active_bots,
        "active_campaigns": active_campaigns,
        "emails_today": emails_today
    }


async def get_analytics_summary(db: AsyncSession) -> dict:
    """Get overall analytics summary"""
    from app.db.models import WarmupCampaign, CampaignStatus
    
    # Total and active users
    result = await db.execute(select(func.count(User.id)))
    total_users = result.scalar() or 0
    
    result = await db.execute(
        select(func.count(User.id))
        .where(User.is_active == True)
    )
    active_users = result.scalar() or 0
    
    # Total and active campaigns
    result = await db.execute(select(func.count(WarmupCampaign.id)))
    total_campaigns = result.scalar() or 0
    
    result = await db.execute(
        select(func.count(WarmupCampaign.id))
        .where(WarmupCampaign.status == CampaignStatus.ACTIVE)
    )
    active_campaigns = result.scalar() or 0
    
    # Total emails sent
    result = await db.execute(
        select(func.sum(WarmupCampaign.emails_sent))
    )
    total_emails_sent = result.scalar() or 0
    
    # Emails sent today
    today = date.today()
    result = await db.execute(
        select(func.count(BotActivity.id))
        .where(
            and_(
                BotActivity.created_at >= datetime.combine(today, datetime.min.time()),
                BotActivity.activity_type == "email_sent"
            )
        )
    )
    total_emails_today = result.scalar() or 0
    
    # Calculate rates
    result = await db.execute(
        select(
            func.avg(WarmupCampaign.emails_delivered * 100.0 / func.nullif(WarmupCampaign.emails_sent, 0))
        )
    )
    avg_delivery_rate = result.scalar() or 0.0
    
    result = await db.execute(
        select(
            func.avg(WarmupCampaign.emails_opened * 100.0 / func.nullif(WarmupCampaign.emails_delivered, 0))
        )
    )
    avg_open_rate = result.scalar() or 0.0
    
    result = await db.execute(
        select(
            func.avg(WarmupCampaign.emails_replied * 100.0 / func.nullif(WarmupCampaign.emails_delivered, 0))
        )
    )
    avg_reply_rate = result.scalar() or 0.0
    
    return {
        "total_users": total_users,
        "active_users": active_users,
        "total_campaigns": total_campaigns,
        "active_campaigns": active_campaigns,
        "total_emails_sent": int(total_emails_sent),
        "total_emails_today": total_emails_today,
        "avg_delivery_rate": float(avg_delivery_rate),
        "avg_open_rate": float(avg_open_rate),
        "avg_reply_rate": float(avg_reply_rate)
    }


# ============= Email Template Functions =============

async def get_all_templates(db: AsyncSession, active_only: bool = False) -> List[EmailTemplate]:
    """Get all email templates"""
    query = select(EmailTemplate).order_by(EmailTemplate.created_at.desc())
    if active_only:
        query = query.where(EmailTemplate.is_active == True)
    
    result = await db.execute(query)
    return result.scalars().all()


async def get_template_by_id(db: AsyncSession, template_id: int) -> Optional[EmailTemplate]:
    """Get email template by ID"""
    result = await db.execute(
        select(EmailTemplate).where(EmailTemplate.id == template_id)
    )
    return result.scalar_one_or_none()


async def get_templates_by_category(db: AsyncSession, category: str) -> List[EmailTemplate]:
    """Get templates by category"""
    result = await db.execute(
        select(EmailTemplate)
        .where(and_(EmailTemplate.category == category, EmailTemplate.is_active == True))
        .order_by(EmailTemplate.created_at.desc())
    )
    return result.scalars().all()


async def create_template(
    db: AsyncSession,
    name: str,
    subject: str,
    body: str,
    category: str,
    variables: Optional[List[str]] = None
) -> EmailTemplate:
    """Create new email template"""
    template = EmailTemplate(
        name=name,
        subject=subject,
        body=body,
        category=category,
        variables=json.dumps(variables or []),
        is_active=True
    )
    db.add(template)
    await db.commit()
    await db.refresh(template)
    return template


async def update_template(
    db: AsyncSession,
    template_id: int,
    name: Optional[str] = None,
    subject: Optional[str] = None,
    body: Optional[str] = None,
    category: Optional[str] = None,
    variables: Optional[List[str]] = None,
    is_active: Optional[bool] = None
) -> Optional[EmailTemplate]:
    """Update email template"""
    template = await get_template_by_id(db, template_id)
    if not template:
        return None
    
    if name is not None:
        template.name = name
    if subject is not None:
        template.subject = subject
    if body is not None:
        template.body = body
    if category is not None:
        template.category = category
    if variables is not None:
        template.variables = json.dumps(variables)
    if is_active is not None:
        template.is_active = is_active
    
    template.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(template)
    return template


async def delete_template(db: AsyncSession, template_id: int) -> bool:
    """Delete email template"""
    template = await get_template_by_id(db, template_id)
    if not template:
        return False
    
    await db.delete(template)
    await db.commit()
    return True


async def increment_template_usage(db: AsyncSession, template_id: int):
    """Increment template usage counter"""
    template = await get_template_by_id(db, template_id)
    if template:
        template.times_used += 1
        template.last_used_at = datetime.utcnow()
        await db.commit()


# ============================================================================
# TASK CONFIGURATION FUNCTIONS (Dynamic Scheduling)
# ============================================================================

async def get_all_task_configs(db: AsyncSession) -> List:
    """Get all task configurations"""
    from app.db.models import TaskConfiguration
    result = await db.execute(
        select(TaskConfiguration).order_by(TaskConfiguration.task_name)
    )
    return result.scalars().all()


async def get_task_config(db: AsyncSession, task_id: int):
    """Get task configuration by ID"""
    from app.db.models import TaskConfiguration
    result = await db.execute(
        select(TaskConfiguration).where(TaskConfiguration.id == task_id)
    )
    return result.scalar_one_or_none()


async def get_task_config_by_name(db: AsyncSession, task_name: str):
    """Get task configuration by name"""
    from app.db.models import TaskConfiguration
    result = await db.execute(
        select(TaskConfiguration).where(TaskConfiguration.task_name == task_name)
    )
    return result.scalar_one_or_none()


async def update_task_config(db: AsyncSession, task_id: int, update_data):
    """Update task configuration"""
    from app.db.models import TaskConfiguration
    
    task = await get_task_config(db, task_id)
    if not task:
        return None
    
    if update_data.interval_minutes is not None:
        task.interval_minutes = update_data.interval_minutes
    
    if update_data.is_enabled is not None:
        task.is_enabled = update_data.is_enabled
    
    if update_data.description is not None:
        task.description = update_data.description
    
    task.updated_at = datetime.utcnow()
    await db.flush()
    return task


async def toggle_task(db: AsyncSession, task_id: int):
    """Toggle task enabled/disabled"""
    from app.db.models import TaskConfiguration
    
    task = await get_task_config(db, task_id)
    if not task:
        return None
    
    task.is_enabled = not task.is_enabled
    task.updated_at = datetime.utcnow()
    await db.flush()
    return task


# ============================================================================
# SYSTEM SETTINGS
# ============================================================================

async def get_warmup_settings(db: AsyncSession):
    """Get all warmup configuration settings"""
    from app.db.models import SystemSetting
    
    settings_keys = [
        'warmup_increment_days',
        'warmup_increment_amount',
        'min_daily_emails',
        'max_daily_emails',
        'max_spam_complaint_rate',
        'max_bounce_rate',
        'auto_pause_on_spam'
    ]
    
    # Defaults
    defaults = {
        'warmup_increment_days': 7,
        'warmup_increment_amount': 15,
        'min_daily_emails': 5,
        'max_daily_emails': 100,
        'max_spam_complaint_rate': 0.01,
        'max_bounce_rate': 0.05,
        'auto_pause_on_spam': True
    }
    
    settings_dict = {}
    
    for key in settings_keys:
        result = await db.execute(
            select(SystemSetting).where(SystemSetting.setting_key == key)
        )
        setting = result.scalar_one_or_none()
        
        if setting:
            # Parse value based on type
            if setting.setting_type == 'int':
                settings_dict[key] = int(setting.setting_value)
            elif setting.setting_type == 'float':
                settings_dict[key] = float(setting.setting_value)
            elif setting.setting_type == 'bool':
                settings_dict[key] = setting.setting_value.lower() == 'true'
            else:
                settings_dict[key] = setting.setting_value
        else:
            # Use default
            settings_dict[key] = defaults.get(key)
    
    return settings_dict


async def update_warmup_settings(db: AsyncSession, update_data):
    """Update warmup configuration settings"""
    from app.db.models import SystemSetting
    
    settings_map = {
        'warmup_increment_days': ('int', update_data.warmup_increment_days),
        'warmup_increment_amount': ('int', update_data.warmup_increment_amount),
        'min_daily_emails': ('int', update_data.min_daily_emails),
        'max_daily_emails': ('int', update_data.max_daily_emails),
        'max_spam_complaint_rate': ('float', update_data.max_spam_complaint_rate),
        'max_bounce_rate': ('float', update_data.max_bounce_rate),
        'auto_pause_on_spam': ('bool', update_data.auto_pause_on_spam)
    }
    
    for key, (setting_type, value) in settings_map.items():
        if value is not None:
            # Check if setting exists
            result = await db.execute(
                select(SystemSetting).where(SystemSetting.setting_key == key)
            )
            setting = result.scalar_one_or_none()
            
            if setting:
                # Update existing
                setting.setting_value = str(value).lower() if setting_type == 'bool' else str(value)
                setting.updated_at = datetime.utcnow()
            else:
                # Create new
                new_setting = SystemSetting(
                    setting_key=key,
                    setting_value=str(value).lower() if setting_type == 'bool' else str(value),
                    setting_type=setting_type
                )
                db.add(new_setting)
    
    await db.flush()
    
    # Return updated settings
    return await get_warmup_settings(db)

