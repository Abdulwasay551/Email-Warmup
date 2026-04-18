import random
import logging
from datetime import datetime, date, timedelta
from typing import List
from celery import shared_task
from sqlalchemy import select, and_, func

from app.workers.celery_app import celery_app
from app.core.database import SessionLocal
from app.db.models import (
    WarmupCampaign, EmailMessage, EmailInbox, ReputationStats,
    CampaignStatus, EmailDirection, InboxStatus
)
from app.campaigns.service import (
    get_active_campaigns,
    get_campaign_inboxes,
    calculate_daily_send_quota,
    select_inbox_pairs,
    increment_campaign_volume
)
from app.ai.generator import generate_casual_email, generate_reply, calculate_reply_delay
from app.emails.sender import send_email_via_gmail, check_email_status, get_inbox_messages, parse_email_headers
from app.core.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)


@celery_app.task(name="app.workers.tasks.execute_campaigns")
def execute_campaigns():
    """Main task: Execute all active warm-up campaigns"""
    logger.info("=== Starting campaign execution ===")
    
    db = SessionLocal()
    try:
        # Get all running campaigns (sync query)
        campaigns = db.query(WarmupCampaign).filter(
            WarmupCampaign.status == CampaignStatus.RUNNING
        ).all()
        
        logger.info(f"Found {len(campaigns)} active campaigns")
        
        for campaign in campaigns:
            try:
                logger.info(f"Processing campaign: {campaign.name} (ID: {campaign.id})")
                
                # Check if we can send today
                remaining_quota = calculate_daily_send_quota_sync(db, campaign)
                
                if remaining_quota <= 0:
                    logger.info(f"Campaign {campaign.id} has reached daily quota")
                    continue
                
                # Calculate optimal batch size for this run
                batch_size = calculate_optimal_batch_size(db, campaign, remaining_quota)
                
                # Get inbox pairs for this batch only
                pairs = select_inbox_pairs_sync(db, campaign, batch_size)
                
                if not pairs:
                    logger.warning(f"No available inbox pairs for campaign {campaign.id}")
                    continue
                
                logger.info(f"Selected {len(pairs)} inbox pairs for campaign {campaign.id}")
                
                # Send emails
                for pair in pairs:
                    try:
                        send_warmup_email.delay(
                            campaign.id,
                            pair['from_inbox_id'],
                            pair['to_inbox_id']
                        )
                    except Exception as e:
                        logger.error(f"Error queuing email for pair {pair}: {e}")
                
                # Increment volume if needed
                increment_campaign_volume_sync(db, campaign)
                
                # Update last run time
                campaign.last_run_at = datetime.utcnow()
                db.commit()
                
            except Exception as e:
                logger.error(f"Error processing campaign {campaign.id}: {e}")
                db.rollback()
        
        logger.info("=== Campaign execution completed ===")
        
    except Exception as e:
        logger.error(f"Error in execute_campaigns: {e}")
        db.rollback()
    finally:
        db.close()


@celery_app.task(name="app.workers.tasks.send_warmup_email")
def send_warmup_email(campaign_id: int, from_inbox_id: int, to_inbox_id: int):
    """Send a single warm-up email"""
    db = SessionLocal()
    
    try:
        # Get inboxes
        from_inbox = db.query(EmailInbox).get(from_inbox_id)
        to_inbox = db.query(EmailInbox).get(to_inbox_id)
        campaign = db.query(WarmupCampaign).get(campaign_id)
        
        if not from_inbox or not to_inbox or not campaign:
            logger.error(f"Invalid inbox or campaign IDs")
            return
        
        # Generate email content
        subject, body = generate_casual_email()
        
        logger.info(f"Sending email from {from_inbox.email_address} to {to_inbox.email_address}")
        logger.info(f"Subject: {subject}")
        
        # Send email
        result = send_email_via_gmail(
            from_inbox,
            to_inbox.email_address,
            subject,
            body,
            db=db
        )
        
        if result.get('success'):
            # Store message
            message = EmailMessage(
                campaign_id=campaign_id,
                from_inbox_id=from_inbox_id,
                to_inbox_id=to_inbox_id,
                message_id=result['message_id'],
                thread_id=result.get('thread_id'),
                subject=subject,
                body=body,
                direction=EmailDirection.OUTBOUND,
                ai_generated=True,
                sent_at=result['sent_at']
            )
            db.add(message)
            
            # Update inbox counters
            from_inbox.total_sent += 1
            from_inbox.last_activity = datetime.utcnow()
            
            db.commit()
            
            logger.info(f"Email sent successfully. Message ID: {result['message_id']}")
            
            # Schedule reply if needed
            if campaign.use_ai_replies and random.random() < campaign.reply_rate:
                delay_minutes = calculate_reply_delay()
                schedule_reply.apply_async(
                    args=[message.id],
                    countdown=delay_minutes * 60
                )
                logger.info(f"Reply scheduled in {delay_minutes} minutes")
        else:
            logger.error(f"Failed to send email: {result.get('error')}")
        
    except Exception as e:
        logger.error(f"Error in send_warmup_email: {e}")
        db.rollback()
    finally:
        db.close()


@celery_app.task(name="app.workers.tasks.schedule_reply")
def schedule_reply(message_id: int):
    """Send an AI-generated reply to a message"""
    db = SessionLocal()
    
    try:
        # Get original message
        message = db.query(EmailMessage).get(message_id)
        
        if not message:
            logger.error(f"Message {message_id} not found")
            return
        
        # Get inboxes (swap sender/receiver)
        from_inbox = db.query(EmailInbox).get(message.to_inbox_id)
        to_inbox = db.query(EmailInbox).get(message.from_inbox_id)
        
        if not from_inbox or not to_inbox:
            logger.error(f"Invalid inbox IDs for reply")
            return
        
        # Generate reply
        reply_body = generate_reply(message.subject, message.body)
        reply_subject = f"Re: {message.subject}"
        
        logger.info(f"Sending reply from {from_inbox.email_address} to {to_inbox.email_address}")
        
        # Send reply
        result = send_email_via_gmail(
            from_inbox,
            to_inbox.email_address,
            reply_subject,
            reply_body,
            thread_id=message.thread_id,
            in_reply_to=message.message_id,
            db=db
        )
        
        if result.get('success'):
            # Store reply message
            reply_message = EmailMessage(
                campaign_id=message.campaign_id,
                from_inbox_id=from_inbox.id,
                to_inbox_id=to_inbox.id,
                message_id=result['message_id'],
                thread_id=result.get('thread_id', message.thread_id),
                subject=reply_subject,
                body=reply_body,
                direction=EmailDirection.INBOUND,
                ai_generated=True,
                sent_at=result['sent_at']
            )
            db.add(reply_message)
            
            # Mark original as replied
            message.replied = True
            message.replied_at = datetime.utcnow()
            
            # Update inbox counters
            from_inbox.total_sent += 1
            to_inbox.total_received += 1
            
            db.commit()
            
            logger.info(f"Reply sent successfully")
        else:
            logger.error(f"Failed to send reply: {result.get('error')}")
        
    except Exception as e:
        logger.error(f"Error in schedule_reply: {e}")
        db.rollback()
    finally:
        db.close()


@celery_app.task(name="app.workers.tasks.monitor_inboxes")
def monitor_inboxes():
    """Monitor inboxes for opens, replies, spam placement"""
    logger.info("=== Starting inbox monitoring ===")
    
    db = SessionLocal()
    
    try:
        # Get all active inboxes
        inboxes = db.query(EmailInbox).filter(
            EmailInbox.status == InboxStatus.ACTIVE
        ).all()
        
        logger.info(f"Monitoring {len(inboxes)} active inboxes")
        
        for inbox in inboxes:
            try:
                # Check recent sent messages
                recent_messages = db.query(EmailMessage).filter(
                    and_(
                        EmailMessage.from_inbox_id == inbox.id,
                        EmailMessage.sent_at >= datetime.utcnow() - timedelta(days=7),
                        EmailMessage.opened == False
                    )
                ).limit(20).all()
                
                for message in recent_messages:
                    status = check_email_status(inbox, message.message_id)
                    
                    if status.get('opened'):
                        message.opened = True
                        message.opened_at = datetime.utcnow()
                    
                    if status.get('spam'):
                        message.spam_reported = True
                
                db.commit()
                
            except Exception as e:
                logger.error(f"Error monitoring inbox {inbox.id}: {e}")
                db.rollback()
        
        logger.info("=== Inbox monitoring completed ===")
        
    except Exception as e:
        logger.error(f"Error in monitor_inboxes: {e}")
        db.rollback()
    finally:
        db.close()


@celery_app.task(name="app.workers.tasks.aggregate_daily_stats")
def aggregate_daily_stats():
    """Aggregate daily reputation statistics"""
    logger.info("=== Aggregating daily stats ===")
    
    db = SessionLocal()
    
    try:
        yesterday = date.today() - timedelta(days=1)
        
        # Get all inboxes
        inboxes = db.query(EmailInbox).all()
        
        for inbox in inboxes:
            try:
                # Count emails sent
                sent_count = db.query(func.count(EmailMessage.id)).filter(
                    and_(
                        EmailMessage.from_inbox_id == inbox.id,
                        func.date(EmailMessage.sent_at) == yesterday
                    )
                ).scalar() or 0
                
                # Count emails received
                received_count = db.query(func.count(EmailMessage.id)).filter(
                    and_(
                        EmailMessage.to_inbox_id == inbox.id,
                        func.date(EmailMessage.sent_at) == yesterday
                    )
                ).scalar() or 0
                
                # Count opens
                opened_count = db.query(func.count(EmailMessage.id)).filter(
                    and_(
                        EmailMessage.from_inbox_id == inbox.id,
                        func.date(EmailMessage.sent_at) == yesterday,
                        EmailMessage.opened == True
                    )
                ).scalar() or 0
                
                # Count replies
                replied_count = db.query(func.count(EmailMessage.id)).filter(
                    and_(
                        EmailMessage.from_inbox_id == inbox.id,
                        func.date(EmailMessage.sent_at) == yesterday,
                        EmailMessage.replied == True
                    )
                ).scalar() or 0
                
                # Count spam
                spam_count = db.query(func.count(EmailMessage.id)).filter(
                    and_(
                        EmailMessage.from_inbox_id == inbox.id,
                        func.date(EmailMessage.sent_at) == yesterday,
                        EmailMessage.spam_reported == True
                    )
                ).scalar() or 0
                
                # Calculate rates
                open_rate = (opened_count / sent_count * 100) if sent_count > 0 else 0
                reply_rate = (replied_count / sent_count * 100) if sent_count > 0 else 0
                spam_rate = (spam_count / sent_count * 100) if sent_count > 0 else 0
                
                # Calculate reputation score (0-100)
                reputation_score = calculate_reputation_score(open_rate, reply_rate, spam_rate)
                
                # Create or update stats
                stats = db.query(ReputationStats).filter(
                    and_(
                        ReputationStats.inbox_id == inbox.id,
                        ReputationStats.date == yesterday
                    )
                ).first()
                
                if stats:
                    stats.emails_sent = sent_count
                    stats.emails_received = received_count
                    stats.emails_opened = opened_count
                    stats.emails_replied = replied_count
                    stats.spam_complaints = spam_count
                    stats.open_rate = open_rate
                    stats.reply_rate = reply_rate
                    stats.spam_rate = spam_rate
                    stats.reputation_score = reputation_score
                else:
                    stats = ReputationStats(
                        inbox_id=inbox.id,
                        date=yesterday,
                        emails_sent=sent_count,
                        emails_received=received_count,
                        emails_opened=opened_count,
                        emails_replied=replied_count,
                        spam_complaints=spam_count,
                        open_rate=open_rate,
                        reply_rate=reply_rate,
                        spam_rate=spam_rate,
                        reputation_score=reputation_score
                    )
                    db.add(stats)
                
                db.commit()
                
                logger.info(f"Stats aggregated for inbox {inbox.id}: {sent_count} sent, score: {reputation_score:.1f}")
                
            except Exception as e:
                logger.error(f"Error aggregating stats for inbox {inbox.id}: {e}")
                db.rollback()
        
        logger.info("=== Daily stats aggregation completed ===")
        
    except Exception as e:
        logger.error(f"Error in aggregate_daily_stats: {e}")
        db.rollback()
    finally:
        db.close()


@celery_app.task(name="app.workers.tasks.check_safety_limits")
def check_safety_limits():
    """Check safety limits and auto-pause if needed"""
    logger.info("=== Checking safety limits ===")
    
    db = SessionLocal()
    
    try:
        # Get all active inboxes
        inboxes = db.query(EmailInbox).filter(
            EmailInbox.status == InboxStatus.ACTIVE
        ).all()
        
        for inbox in inboxes:
            try:
                # Check last 7 days
                week_ago = date.today() - timedelta(days=7)
                
                # Get recent stats
                stats = db.query(ReputationStats).filter(
                    and_(
                        ReputationStats.inbox_id == inbox.id,
                        ReputationStats.date >= week_ago
                    )
                ).all()
                
                if not stats:
                    continue
                
                # Calculate average spam rate
                total_sent = sum(s.emails_sent for s in stats)
                total_spam = sum(s.spam_complaints for s in stats)
                
                if total_sent > 0:
                    spam_rate = total_spam / total_sent
                    
                    if spam_rate > settings.max_spam_complaint_rate:
                        # Auto-pause inbox
                        inbox.status = InboxStatus.PAUSED
                        db.commit()
                        
                        logger.warning(
                            f"AUTO-PAUSED inbox {inbox.id} ({inbox.email_address}): "
                            f"Spam rate {spam_rate:.2%} exceeds threshold {settings.max_spam_complaint_rate:.2%}"
                        )
                
            except Exception as e:
                logger.error(f"Error checking safety for inbox {inbox.id}: {e}")
                db.rollback()
        
        logger.info("=== Safety check completed ===")
        
    except Exception as e:
        logger.error(f"Error in check_safety_limits: {e}")
        db.rollback()
    finally:
        db.close()


# Helper functions (sync versions for Celery)
def calculate_daily_send_quota_sync(db, campaign):
    """Sync version of calculate_daily_send_quota"""
    today = date.today()
    
    sent_today = db.query(func.count(EmailMessage.id)).filter(
        and_(
            EmailMessage.campaign_id == campaign.id,
            func.date(EmailMessage.sent_at) == today,
            EmailMessage.direction == EmailDirection.OUTBOUND
        )
    ).scalar() or 0
    
    remaining = campaign.current_daily_volume - sent_today
    return max(0, remaining)


def calculate_optimal_batch_size(db, campaign, remaining_quota):
    """Calculate optimal batch size to distribute emails throughout the day"""
    # Get task interval from database or default to 30 minutes
    from app.db.models import TaskConfiguration
    
    task_config = db.query(TaskConfiguration).filter(
        TaskConfiguration.task_name == 'execute_campaigns'
    ).first()
    
    interval_minutes = task_config.interval_minutes if task_config else 30
    
    # Calculate how many more runs we'll have today
    now = datetime.now()
    minutes_until_midnight = (24 - now.hour) * 60 - now.minute
    remaining_runs_today = max(1, minutes_until_midnight // interval_minutes)
    
    # Distribute remaining quota across remaining runs
    # Add a bit extra to first batches to ensure we hit quota
    batch_size = max(1, int(remaining_quota / remaining_runs_today) + 1)
    
    # Don't send more than what's remaining
    batch_size = min(batch_size, remaining_quota)
    
    logger.info(f"Campaign {campaign.id}: {remaining_quota} remaining, {remaining_runs_today} runs left, batch size: {batch_size}")
    
    return batch_size


def select_inbox_pairs_sync(db, campaign, count):
    """Sync version of select_inbox_pairs"""
    # Get campaign inboxes
    from app.db.models import CampaignInbox
    
    campaign_inboxes = db.query(EmailInbox).join(CampaignInbox).filter(
        and_(
            CampaignInbox.campaign_id == campaign.id,
            CampaignInbox.is_active == True,
            EmailInbox.status == InboxStatus.ACTIVE
        )
    ).all()
    
    if len(campaign_inboxes) < 2:
        return []
    
    pairs = []
    today = date.today()
    
    attempts = 0
    while len(pairs) < count and attempts < count * 10:
        from_inbox = random.choice(campaign_inboxes)
        to_inbox = random.choice([i for i in campaign_inboxes if i.id != from_inbox.id])
        
        # Check daily limit
        sent_today = db.query(func.count(EmailMessage.id)).filter(
            and_(
                EmailMessage.from_inbox_id == from_inbox.id,
                func.date(EmailMessage.sent_at) == today
            )
        ).scalar() or 0
        
        if sent_today < from_inbox.daily_send_limit:
            pairs.append({
                'from_inbox_id': from_inbox.id,
                'to_inbox_id': to_inbox.id
            })
        
        attempts += 1
    
    return pairs


def increment_campaign_volume_sync(db, campaign):
    """Sync version of increment_campaign_volume with proper date tracking"""
    if not campaign.start_date:
        return
    
    # Get warmup settings from database or use defaults
    increment_days = get_system_setting_sync(db, 'warmup_increment_days', 7)
    increment_amount = get_system_setting_sync(db, 'warmup_increment_amount', 15)
    max_daily = get_system_setting_sync(db, 'max_daily_emails', 100)
    
    today = date.today()
    
    # Check if we've already incremented or if it's time to increment
    if campaign.last_volume_increase_date:
        days_since_increase = (today - campaign.last_volume_increase_date).days
    else:
        # First time - use start date
        days_since_increase = (today - campaign.start_date).days
    
    # Increment if enough days have passed
    if days_since_increase >= increment_days:
        new_volume = min(
            campaign.current_daily_volume + increment_amount,
            campaign.target_daily_volume,
            max_daily
        )
        
        if new_volume != campaign.current_daily_volume:
            old_volume = campaign.current_daily_volume
            campaign.current_daily_volume = new_volume
            campaign.last_volume_increase_date = today
            db.commit()
            logger.info(f"Campaign {campaign.id} volume increased: {old_volume} -> {new_volume}")
            
            # Also update warmup stages for all campaign inboxes
            update_inbox_warmup_stages_sync(db, campaign)


def get_system_setting_sync(db, key, default):
    """Get system setting value from database"""
    from app.db.models import SystemSetting
    
    setting = db.query(SystemSetting).filter(
        SystemSetting.setting_key == key
    ).first()
    
    if not setting:
        return default
    
    # Parse value based on type
    if setting.setting_type == 'int':
        return int(setting.setting_value)
    elif setting.setting_type == 'float':
        return float(setting.setting_value)
    elif setting.setting_type == 'bool':
        return setting.setting_value.lower() == 'true'
    else:
        return setting.setting_value


def update_inbox_warmup_stages_sync(db, campaign):
    """Update warmup stages for all inboxes in campaign based on volume"""
    from app.db.models import CampaignInbox
    
    # Define stage thresholds
    stage_thresholds = [
        (5, 1),    # 0-5 emails/day = Stage 1
        (10, 2),   # 6-10 emails/day = Stage 2
        (20, 3),   # 11-20 emails/day = Stage 3
        (35, 4),   # 21-35 emails/day = Stage 4
        (50, 5),   # 36-50 emails/day = Stage 5
        (70, 6),   # 51-70 emails/day = Stage 6
        (90, 7),   # 71-90 emails/day = Stage 7
        (110, 8),  # 91-110 emails/day = Stage 8
        (130, 9),  # 111-130 emails/day = Stage 9
        (150, 10), # 131+ emails/day = Stage 10
    ]
    
    # Determine stage based on current volume
    new_stage = 1
    for threshold, stage in stage_thresholds:
        if campaign.current_daily_volume <= threshold:
            new_stage = stage
            break
    else:
        new_stage = 10  # Max stage
    
    # Update all campaign inboxes
    campaign_inboxes = db.query(EmailInbox).join(CampaignInbox).filter(
        and_(
            CampaignInbox.campaign_id == campaign.id,
            EmailInbox.status == InboxStatus.ACTIVE
        )
    ).all()
    
    now = datetime.utcnow()
    for inbox in campaign_inboxes:
        if inbox.warmup_stage != new_stage:
            inbox.warmup_stage = new_stage
            inbox.last_stage_update = now
            # Update daily send limit based on stage
            inbox.daily_send_limit = campaign.current_daily_volume
            logger.info(f"Inbox {inbox.email_address} updated to stage {new_stage}, limit {inbox.daily_send_limit}")
    
    db.commit()


def calculate_reputation_score(open_rate, reply_rate, spam_rate):
    """Calculate reputation score (0-100)"""
    score = 50.0  # Base score
    
    # Positive factors
    score += min(open_rate * 0.3, 20)  # Up to +20 for opens
    score += min(reply_rate * 0.4, 25)  # Up to +25 for replies
    
    # Negative factors
    score -= spam_rate * 10  # -10 per 1% spam rate
    
    return max(0, min(100, score))


@celery_app.task(name="app.workers.tasks.monitor_bot_emails")
def monitor_bot_emails():
    """Monitor bot emails for user emails and handle spam"""
    logger.info("=== Starting bot email monitoring ===")
    
    db = SessionLocal()
    
    try:
        from app.db.models import BotEmail, UserBotAssignment, BotEmailStatus
        from app.emails.bot_service import GmailBotService
        from app.admin.service import log_bot_activity
        
        # Get all active bot emails
        bots = db.query(BotEmail).filter(
            BotEmail.status == BotEmailStatus.ACTIVE
        ).all()
        
        logger.info(f"Monitoring {len(bots)} active bot emails")
        
        for bot in bots:
            try:
                if not bot.access_token or not bot.refresh_token:
                    logger.warning(f"Bot {bot.email_address} missing tokens")
                    continue
                
                # Decrypt tokens
                from app.inbox.oauth import decrypt_tokens
                access_token, refresh_token = decrypt_tokens(
                    bot.access_token,
                    bot.refresh_token
                )
                
                # Initialize Gmail service with token refresh support
                gmail_service = GmailBotService(
                    access_token=access_token,
                    refresh_token=refresh_token,
                    bot_instance=bot,
                    db=db
                )
                
                # Get active assignments for this bot
                assignments = db.query(UserBotAssignment).filter(
                    and_(
                        UserBotAssignment.bot_email_id == bot.id,
                        UserBotAssignment.is_active == True
                    )
                ).all()
                
                for assignment in assignments:
                    user_email = assignment.user_email_address
                    
                    # Check inbox for emails from this user
                    inbox_emails = gmail_service.check_inbox(from_email=user_email)
                    
                    for email in inbox_emails:
                        # Mark as read and log
                        gmail_service.mark_as_read(email['id'])
                        
                        # Log activity (sync)
                        activity = log_bot_activity(
                            db=db,
                            bot_email_id=bot.id,
                            activity_type="email_received",
                            from_email=user_email,
                            subject=email['headers'].get('subject', 'No subject'),
                            was_in_spam=False,
                            action_taken="marked_read"
                        )
                        
                        assignment.emails_received += 1
                        bot.total_emails_processed += 1
                    
                    # Check spam folder if enabled
                    if assignment.check_spam:
                        spam_emails = gmail_service.check_spam(from_email=user_email)
                        
                        for email in spam_emails:
                            # Report as not spam if enabled
                            if assignment.auto_report_not_spam:
                                success = gmail_service.mark_as_not_spam(email['id'])
                                
                                if success:
                                    # Log activity (sync)
                                    activity = log_bot_activity(
                                        db=db,
                                        bot_email_id=bot.id,
                                        activity_type="spam_handled",
                                        from_email=user_email,
                                        subject=email['headers'].get('subject', 'No subject'),
                                        was_in_spam=True,
                                        action_taken="reported_not_spam"
                                    )
                                    
                                    assignment.emails_in_spam += 1
                                    assignment.spam_reports_made += 1
                                    bot.spam_moved_to_inbox += 1
                                    
                                    logger.info(
                                        f"Reported as not spam: {email['headers'].get('subject')} "
                                        f"from {user_email} on bot {bot.email_address}"
                                    )
                
                # Update bot health
                bot.last_check_at = datetime.utcnow()
                bot.last_activity = datetime.utcnow()
                bot.is_healthy = True
                bot.consecutive_errors = 0
                
                db.commit()
                
            except Exception as e:
                logger.error(f"Error monitoring bot {bot.email_address}: {e}")
                
                # Update error status
                bot.last_error = str(e)
                bot.consecutive_errors += 1
                
                if bot.consecutive_errors >= 5:
                    bot.is_healthy = False
                
                db.commit()
        
        logger.info("=== Bot email monitoring completed ===")
        
    except Exception as e:
        logger.error(f"Error in monitor_bot_emails: {e}")
        db.rollback()
    finally:
        db.close()


# Sync version of log_bot_activity for use in tasks
def log_bot_activity_sync(db, bot_email_id, activity_type, from_email=None, 
                          subject=None, was_in_spam=False, action_taken=None):
    """Sync version of log_bot_activity"""
    from app.db.models import BotActivity
    
    activity = BotActivity(
        bot_email_id=bot_email_id,
        activity_type=activity_type,
        from_email=from_email,
        subject=subject,
        was_in_spam=was_in_spam,
        action_taken=action_taken
    )
    
    db.add(activity)
    return activity


@celery_app.task(name="app.workers.tasks.check_oauth_tokens")
def check_oauth_tokens():
    """
    Check OAuth tokens for expiration and attempt automatic refresh
    
    This task runs periodically to:
    1. Check for expired tokens
    2. Check for tokens expiring soon
    3. Attempt automatic token refresh
    4. Mark accounts as disconnected if refresh fails
    
    Works with Cross-Account Protection to handle revoked tokens.
    """
    from app.auth.token_revocation_handler import TokenRevocationHandler
    
    logger.info("=== Starting OAuth token check ===")
    
    db = SessionLocal()
    
    try:
        # Check for expired tokens
        expired_accounts = TokenRevocationHandler.check_expired_tokens(db)
        
        if expired_accounts:
            logger.warning(f"Found {len(expired_accounts)} accounts with expired tokens")
            
            for account in expired_accounts:
                logger.info(
                    f"Expired: {account['type']} {account['id']} "
                    f"({account['email']})"
                )
        
        # Check for tokens expiring soon (within 48 hours)
        expiring_soon = TokenRevocationHandler.check_expiring_soon(db, hours=48)
        
        if expiring_soon:
            logger.info(
                f"Found {len(expiring_soon)} accounts with tokens expiring "
                f"within 48 hours"
            )
            
            # Attempt to refresh tokens that are expiring soon
            for account in expiring_soon:
                try:
                    if account['type'] == 'user_inbox':
                        success = TokenRevocationHandler.attempt_token_refresh(
                            db=db,
                            inbox_id=account['id']
                        )
                    elif account['type'] == 'bot_email':
                        success = TokenRevocationHandler.attempt_token_refresh(
                            db=db,
                            bot_id=account['id']
                        )
                    else:
                        continue
                    
                    if success:
                        logger.info(
                            f"Successfully refreshed token for {account['email']} "
                            f"({account['hours_remaining']:.1f} hours remaining)"
                        )
                    else:
                        logger.warning(
                            f"Failed to refresh token for {account['email']}"
                        )
                
                except Exception as e:
                    logger.error(
                        f"Error refreshing token for {account['email']}: {e}"
                    )
        
        logger.info("=== OAuth token check completed ===")
        
        return {
            'expired_count': len(expired_accounts),
            'expiring_soon_count': len(expiring_soon),
            'timestamp': datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error in check_oauth_tokens: {e}")
        db.rollback()
        return {'error': str(e)}
    finally:
        db.close()


@celery_app.task(name="app.workers.tasks.cleanup_security_events")
def cleanup_security_events(days_to_keep: int = 90):
    """
    Clean up old security event logs
    
    Args:
        days_to_keep: How many days of logs to retain
    """
    from app.db.models import SecurityEventLog
    
    logger.info(f"=== Cleaning up security events older than {days_to_keep} days ===")
    
    db = SessionLocal()
    
    try:
        cutoff_date = datetime.utcnow() - timedelta(days=days_to_keep)
        
        # Delete old security events
        deleted_count = db.query(SecurityEventLog).filter(
            SecurityEventLog.received_at < cutoff_date
        ).delete()
        
        db.commit()
        
        logger.info(f"Deleted {deleted_count} old security event logs")
        
        return {
            'deleted_count': deleted_count,
            'cutoff_date': cutoff_date.isoformat(),
            'timestamp': datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error in cleanup_security_events: {e}")
        db.rollback()
        return {'error': str(e)}
    finally:
        db.close()


