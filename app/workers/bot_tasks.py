"""
Bot-based email warmup tasks

This implements the complete bot warmup flow:
1. Send emails from user inboxes to bot emails
2. Bots monitor their inbox and spam folders
3. Bots reply to user emails (using AI or templates)
4. Track engagement and reputation
"""

import logging
import random
from datetime import datetime, timedelta, date
from celery import shared_task
from sqlalchemy import select, and_, func
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import base64
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import json

from app.workers.celery_app import celery_app
from app.core.database import SessionLocal
from app.db.models import (
    WarmupCampaign, EmailMessage, EmailInbox, BotEmail, BotActivity,
    UserBotAssignment, EmailTemplate, CampaignInbox,
    CampaignStatus, EmailDirection, BotEmailStatus, InboxStatus
)
from app.campaigns.bot_service import (
    get_available_bots,
    select_user_to_bot_pairs,
    calculate_daily_bot_send_quota,
    get_email_template
)
from app.ai.generator import generate_casual_email, generate_reply
from app.emails.sender import decrypt_token
from app.core.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)


@celery_app.task(name="app.workers.tasks.execute_bot_campaigns")
def execute_bot_campaigns():
    """
    Main task: Execute bot-based warmup campaigns
    Sends emails from user inboxes to bot emails
    """
    logger.info("=== Starting bot-based campaign execution ===")
    
    db = SessionLocal()
    try:
        # Get all running campaigns that use bot system
        campaigns = db.query(WarmupCampaign).filter(
            and_(
                WarmupCampaign.status == CampaignStatus.RUNNING,
                WarmupCampaign.use_bot_system == True
            )
        ).all()
        
        logger.info(f"Found {len(campaigns)} active bot-based campaigns")
        
        for campaign in campaigns:
            try:
                logger.info(f"Processing campaign: {campaign.name} (ID: {campaign.id})")
                
                # Calculate remaining quota
                remaining_quota = calculate_daily_bot_send_quota_sync(db, campaign)
                
                if remaining_quota <= 0:
                    logger.info(f"Campaign {campaign.id} has reached daily quota")
                    continue
                
                # Calculate optimal batch size for distributed sending
                batch_size = calculate_optimal_batch_size(db, campaign, remaining_quota)
                logger.info(f"Campaign {campaign.id}: Batch size={batch_size}, Remaining quota={remaining_quota}")
                
                # Select user→bot pairs for this batch only
                pairs = select_user_to_bot_pairs_sync(db, campaign, batch_size)
                
                if not pairs:
                    logger.warning(f"No available user→bot pairs for campaign {campaign.id} - may have sent recently or hit daily limits")
                    continue
                
                logger.info(f"✅ Selected {len(pairs)} user→bot pairs for campaign {campaign.id}")
                
                # Queue email send tasks
                for pair in pairs:
                    try:
                        send_email_to_bot.delay(
                            campaign.id,
                            pair['from_inbox_id'],
                            pair['to_bot_id'],
                            pair['to_bot_email']
                        )
                    except Exception as e:
                        logger.error(f"Error queuing email for pair {pair}: {e}")
                
                # Increment volume if needed
                increment_campaign_volume_sync(db, campaign)
                
                # Update warmup stages for inboxes
                update_inbox_warmup_stages_sync(db, campaign)
                
                # Update last run time
                campaign.last_run_at = datetime.utcnow()
                db.commit()
                
            except Exception as e:
                logger.error(f"Error processing campaign {campaign.id}: {e}")
                db.rollback()
        
        logger.info("=== Bot campaign execution completed ===")
        
    except Exception as e:
        logger.error(f"Error in execute_bot_campaigns: {e}")
        db.rollback()
    finally:
        db.close()


@celery_app.task(name="app.workers.tasks.send_email_to_bot")
def send_email_to_bot(campaign_id: int, from_inbox_id: int, to_bot_id: int, to_bot_email: str):
    """
    Send a warmup email from user inbox to a bot email
    """
    db = SessionLocal()
    
    try:
        # Get user inbox
        user_inbox = db.query(EmailInbox).filter(EmailInbox.id == from_inbox_id).first()
        if not user_inbox:
            logger.error(f"User inbox {from_inbox_id} not found")
            return
        
        campaign = db.query(WarmupCampaign).filter(WarmupCampaign.id == campaign_id).first()
        if not campaign:
            logger.error(f"Campaign {campaign_id} not found")
            return
        
        # Generate email content
        if campaign.use_ai_replies and settings.openai_api_key:
            try:
                subject, body = generate_casual_email()
            except Exception as e:
                logger.error(f"AI generation failed, using template: {e}")
                template = get_email_template_sync(db, "engagement")
                if template:
                    subject = template.subject
                    body = template.body
                else:
                    subject = "Quick question"
                    body = "Hi! Hope you're doing well. Just wanted to reach out and connect."
        else:
            # Use template
            template = get_email_template_sync(db, "engagement")
            if template:
                subject = template.subject
                body = template.body
            else:
                subject = "Hello!"
                body = "Hi there! Just wanted to say hello and see how you're doing."
        
        # Send email via Gmail API
        try:
            message_id = send_via_gmail_api(
                user_inbox,
                to_bot_email,
                subject,
                body,
                db=db
            )
            
            # Record the message
            email_message = EmailMessage(
                campaign_id=campaign_id,
                from_inbox_id=from_inbox_id,
                to_inbox_id=None,  # Not going to another user inbox
                bot_email_id=to_bot_id,
                message_id=message_id,
                subject=subject,
                body=body,
                direction=EmailDirection.OUTBOUND,
                ai_generated=campaign.use_ai_replies,
                is_bot_reply=False
            )
            db.add(email_message)
            
            # Update inbox stats
            user_inbox.total_sent += 1
            user_inbox.last_activity = datetime.utcnow()
            
            db.commit()
            
            logger.info(f"✅ Sent email from {user_inbox.email_address} to bot {to_bot_email}")
            
        except Exception as e:
            logger.error(f"Failed to send email: {e}")
            db.rollback()
    
    except Exception as e:
        logger.error(f"Error in send_email_to_bot: {e}")
        db.rollback()
    finally:
        db.close()


@celery_app.task(name="app.workers.tasks.monitor_bot_inboxes")
def monitor_bot_inboxes():
    """
    Monitor all bot email inboxes for new messages from users
    Checks both inbox and spam folders
    """
    logger.info("=== Monitoring bot inboxes ===")
    
    db = SessionLocal()
    try:
        # Get all active bots
        bots = db.query(BotEmail).filter(
            BotEmail.status == BotEmailStatus.ACTIVE
        ).all()
        
        logger.info(f"Monitoring {len(bots)} bot inboxes")
        
        for bot in bots:
            try:
                check_bot_inbox.delay(bot.id)
            except Exception as e:
                logger.error(f"Error queuing inbox check for bot {bot.id}: {e}")
        
        logger.info("=== Bot inbox monitoring tasks queued ===")
        
    except Exception as e:
        logger.error(f"Error in monitor_bot_inboxes: {e}")
    finally:
        db.close()


@celery_app.task(name="app.workers.tasks.check_bot_inbox")
def check_bot_inbox(bot_id: int):
    """
    Check a single bot's inbox and spam folder for user emails
    Move from spam if needed, and trigger replies
    """
    db = SessionLocal()
    
    try:
        bot = db.query(BotEmail).filter(BotEmail.id == bot_id).first()
        if not bot:
            logger.error(f"Bot {bot_id} not found")
            return
        
        if not bot.access_token:
            logger.warning(f"Bot {bot.email_address} has no access token. Skipping inbox check.")
            return
        
        logger.info(f"Checking inbox for bot: {bot.email_address}")
        
        # Build Gmail API service with token refresh support
        credentials = get_bot_credentials(bot, db)
        service = build('gmail', 'v1', credentials=credentials)
        
        # Check inbox for unread messages
        inbox_messages = check_folder(service, 'INBOX', bot, db)
        
        # Check spam folder
        spam_messages = check_folder(service, 'SPAM', bot, db)
        
        if spam_messages:
            logger.info(f"Found {len(spam_messages)} messages in spam for bot {bot.email_address}")
            # Move spam messages to inbox
            for msg_id in spam_messages:
                try:
                    service.users().messages().modify(
                        userId='me',
                        id=msg_id,
                        body={'removeLabelIds': ['SPAM'], 'addLabelIds': ['INBOX']}
                    ).execute()
                    bot.spam_moved_to_inbox += 1
                    logger.info(f"Moved message {msg_id} from spam to inbox")
                except Exception as e:
                    logger.error(f"Failed to move message from spam: {e}")
        
        # Update bot status
        bot.last_check_at = datetime.utcnow()
        bot.is_healthy = True
        bot.consecutive_errors = 0
        bot.last_activity = datetime.utcnow()
        db.commit()
        
        logger.info(f"✅ Bot {bot.email_address} check complete. Inbox: {len(inbox_messages)}, Spam: {len(spam_messages)}")
        
    except HttpError as e:
        logger.error(f"Gmail API error for bot {bot_id}: {e}")
        bot.consecutive_errors += 1
        bot.last_error = str(e)
        if bot.consecutive_errors >= 5:
            bot.is_healthy = False
            bot.status = BotEmailStatus.ERROR
        db.commit()
    except Exception as e:
        logger.error(f"Error checking bot inbox {bot_id}: {e}")
        db.rollback()
    finally:
        db.close()


def check_folder(service, folder_label: str, bot: BotEmail, db):
    """Check a specific Gmail folder and trigger replies for new messages"""
    try:
        # Get unread messages
        results = service.users().messages().list(
            userId='me',
            labelIds=[folder_label],
            q='is:unread'
        ).execute()
        
        messages = results.get('messages', [])
        message_ids = [msg['id'] for msg in messages]
        
        for msg_id in message_ids:
            try:
                # Get message details
                msg = service.users().messages().get(userId='me', id=msg_id, format='full').execute()
                
                # Extract sender and subject
                headers = msg['payload']['headers']
                from_email = next((h['value'] for h in headers if h['name'].lower() == 'from'), '')
                subject = next((h['value'] for h in headers if h['name'].lower() == 'subject'), '')
                
                # Extract sender email address
                import re
                email_match = re.search(r'<(.+?)>', from_email)
                sender_email = email_match.group(1) if email_match else from_email
                
                # Check if sender is a monitored user inbox
                user_inbox = db.query(EmailInbox).filter(
                    EmailInbox.email_address == sender_email
                ).first()
                
                if not user_inbox:
                    logger.debug(f"Email from {sender_email} is not from a monitored user inbox")
                    continue
                
                # Check if this is from a user we're monitoring (or create assignment)
                assignment = db.query(UserBotAssignment).filter(
                    and_(
                        UserBotAssignment.bot_email_id == bot.id,
                        UserBotAssignment.user_email_address == sender_email
                    )
                ).first()
                
                if not assignment:
                    # Auto-create assignment for any user inbox sending to this bot
                    logger.info(f"Creating new assignment: {sender_email} -> bot {bot.email_address}")
                    assignment = UserBotAssignment(
                        bot_email_id=bot.id,
                        user_email_address=sender_email,
                        is_active=True,
                        emails_received=0,
                        emails_in_spam=0
                    )
                    db.add(assignment)
                    db.flush()
                
                if assignment and assignment.is_active:
                    # This is a user email we should reply to
                    logger.info(f"Found user email from {sender_email} in {folder_label}")
                    
                    # Log activity
                    activity = BotActivity(
                        bot_email_id=bot.id,
                        activity_type='email_received',
                        from_email=sender_email,
                        subject=subject,
                        was_in_spam=(folder_label == 'SPAM'),
                        action_taken='queued_reply' if assignment.is_active else 'ignored'
                    )
                    db.add(activity)
                    
                    # Queue reply task
                    reply_to_user_email.delay(bot.id, sender_email, msg_id, subject)
                    
                    # Mark as read
                    service.users().messages().modify(
                        userId='me',
                        id=msg_id,
                        body={'removeLabelIds': ['UNREAD']}
                    ).execute()
                    
                    # Update stats (handle None values)
                    assignment.emails_received = (assignment.emails_received or 0) + 1
                    if folder_label == 'SPAM':
                        assignment.emails_in_spam = (assignment.emails_in_spam or 0) + 1
                    
                    bot.total_emails_processed = (bot.total_emails_processed or 0) + 1
                else:
                    logger.debug(f"Email from {sender_email} not from monitored user")
                
                db.commit()
                
            except Exception as e:
                logger.error(f"Error processing message {msg_id}: {e}")
                db.rollback()
        
        return message_ids
        
    except Exception as e:
        logger.error(f"Error checking folder {folder_label}: {e}")
        return []


@celery_app.task(name="app.workers.tasks.reply_to_user_email")
def reply_to_user_email(bot_id: int, user_email: str, original_message_id: str, original_subject: str):
    """
    Generate and send a reply from bot to user email
    """
    db = SessionLocal()
    
    try:
        bot = db.query(BotEmail).filter(BotEmail.id == bot_id).first()
        if not bot:
            logger.error(f"Bot {bot_id} not found")
            return
        
        # Check if we should use AI or template
        # For now, use templates. AI integration can be added later
        template = get_email_template_sync(db, "engagement")
        
        if template:
            reply_body = template.body
        else:
            reply_body = "Thank you for your email! I appreciate you reaching out."
        
        # Determine reply subject
        if original_subject.lower().startswith('re:'):
            reply_subject = original_subject
        else:
            reply_subject = f"Re: {original_subject}"
        
        # Send reply
        try:
            credentials = get_bot_credentials(bot)
            service = build('gmail', 'v1', credentials=credentials)
            
            # Create reply message
            message = MIMEMultipart()
            message['to'] = user_email
            message['from'] = bot.email_address
            message['subject'] = reply_subject
            message['In-Reply-To'] = original_message_id
            message['References'] = original_message_id
            
            msg = MIMEText(reply_body, 'plain')
            message.attach(msg)
            
            raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')
            
            send_result = service.users().messages().send(
                userId='me',
                body={'raw': raw_message, 'threadId': original_message_id}
            ).execute()
            
            logger.info(f"✅ Bot {bot.email_address} replied to {user_email}")
            
            # Log activity
            activity = BotActivity(
                bot_email_id=bot.id,
                activity_type='reply_sent',
                from_email=user_email,
                subject=reply_subject,
                action_taken='sent_reply'
            )
            db.add(activity)
            bot.last_activity = datetime.utcnow()
            db.commit()
            
        except Exception as e:
            logger.error(f"Failed to send reply: {e}")
            db.rollback()
    
    except Exception as e:
        logger.error(f"Error in reply_to_user_email: {e}")
        db.rollback()
    finally:
        db.close()


# Helper functions

def send_via_gmail_api(inbox: EmailInbox, to_email: str, subject: str, body: str, db=None) -> str:
    """Send email using Gmail API with automatic token refresh"""
    from cryptography.fernet import InvalidToken
    from app.core.database import SessionLocal
    from app.auth.token_revocation_handler import TokenRevocationHandler
    
    # Create a db session if not provided
    should_close_db = False
    if not db:
        db = SessionLocal()
        should_close_db = True
    
    try:
        # Decrypt tokens
        try:
            access_token = decrypt_token(inbox.access_token)
            refresh_token = decrypt_token(inbox.refresh_token)
        except InvalidToken:
            logger.error(f"Cannot decrypt tokens for inbox {inbox.id} ({inbox.email_address}). Marking as disconnected.")
            
            # Mark inbox as disconnected
            try:
                handler = TokenRevocationHandler()
                handler.mark_inbox_disconnected(
                    db=db,
                    email_address=inbox.email_address,
                    reason="Token decryption failed - please re-authenticate"
                )
                db.commit()
            except Exception as mark_error:
                logger.error(f"Error marking inbox as disconnected: {mark_error}")
                db.rollback()
            
            raise ValueError(f"Invalid token for inbox {inbox.email_address} - re-authentication required")
        
        # Get validated credentials (auto-refresh if needed)
        from app.inbox.oauth import get_validated_credentials
        credentials = get_validated_credentials(access_token, refresh_token, db, inbox)
        
        service = build('gmail', 'v1', credentials=credentials)
        
        # Create message
        message = MIMEText(body)
        message['to'] = to_email
        message['from'] = inbox.email_address
        message['subject'] = subject
        
        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')
        
        send_result = service.users().messages().send(
            userId='me',
            body={'raw': raw_message}
        ).execute()
        
        return send_result['id']
        
    except HttpError as e:
        logger.error(f"Gmail API HTTP error: {e.status_code} - {e.error_details}")
        raise
    except Exception as e:
        logger.error(f"Gmail API send error: {type(e).__name__} - {str(e)}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise
    finally:
        if should_close_db:
            db.close()


def get_bot_credentials(bot: BotEmail, db=None) -> Credentials:
    """Get Google credentials for a bot email with automatic token refresh"""
    from cryptography.fernet import InvalidToken
    from app.core.database import SessionLocal
    from app.auth.token_revocation_handler import TokenRevocationHandler
    
    if not bot.access_token:
        raise ValueError(f"Bot {bot.email_address} has no access token. Please authenticate the bot via admin panel.")
    
    # Create a db session if not provided
    should_close_db = False
    if not db:
        db = SessionLocal()
        should_close_db = True
    
    try:
        try:
            access_token = decrypt_token(bot.access_token)
            refresh_token = decrypt_token(bot.refresh_token) if bot.refresh_token else None
        except InvalidToken:
            logger.error(f"Cannot decrypt tokens for bot {bot.id} ({bot.email_address}). Marking as disconnected.")
            
            # Mark bot as disconnected
            try:
                handler = TokenRevocationHandler()
                handler.mark_inbox_disconnected(
                    db=db,
                    email_address=bot.email_address,
                    reason="Token decryption failed - please re-authenticate"
                )
                db.commit()
            except Exception as mark_error:
                logger.error(f"Error marking bot as disconnected: {mark_error}")
                db.rollback()
            
            raise ValueError(f"Invalid token for bot {bot.email_address} - re-authentication required")
        
        # Get validated credentials (auto-refresh if needed)
        from app.inbox.oauth import get_validated_credentials
        credentials = get_validated_credentials(access_token, refresh_token, db, bot)
        
        return credentials
    finally:
        if should_close_db:
            db.close()


# Sync helper functions for Celery tasks

def calculate_daily_bot_send_quota_sync(db, campaign):
    """Sync version of calculate_daily_bot_send_quota"""
    from datetime import date
    today = date.today()
    
    sent_today = db.query(EmailMessage).filter(
        and_(
            EmailMessage.campaign_id == campaign.id,
            func.date(EmailMessage.sent_at) == today,
            EmailMessage.direction == EmailDirection.OUTBOUND
        )
    ).count()
    
    return max(0, campaign.current_daily_volume - sent_today)


def select_user_to_bot_pairs_sync(db, campaign, count):
    """Sync version of select_user_to_bot_pairs"""
    from datetime import date
    
    # Get campaign inboxes
    user_inboxes = db.query(EmailInbox).join(
        CampaignInbox
    ).filter(
        and_(
            CampaignInbox.campaign_id == campaign.id,
            CampaignInbox.is_active == True,
            EmailInbox.status == 'ACTIVE'
        )
    ).all()
    
    if not user_inboxes:
        logger.debug(f"No active user inboxes for campaign {campaign.id}")
        return []
    
    # Get active bots
    bots = db.query(BotEmail).filter(
        and_(
            BotEmail.status == BotEmailStatus.ACTIVE,
            BotEmail.is_healthy == True
        )
    ).all()
    
    if not bots:
        logger.debug(f"No active/healthy bots available")
        return []
    
    pairs = []
    today = date.today()
    
    # Get task interval to determine lookback period
    from app.db.models import TaskConfiguration
    task_config = db.query(TaskConfiguration).filter(
        TaskConfiguration.task_name == 'execute_bot_campaigns'
    ).first()
    
    # Default to 30 minutes if not configured
    interval_minutes = task_config.interval_minutes if task_config else 30
    
    # Calculate lookback time - we check if pair was used in last interval
    # This allows the same pair to send multiple times per day at each interval
    lookback_time = datetime.utcnow() - timedelta(minutes=interval_minutes)
    
    logger.info(f"🔍 Pair selection for campaign {campaign.id}: {len(user_inboxes)} users × {len(bots)} bots, checking last {interval_minutes} min")
    
    # Get recently used pairs (within the interval period, not entire day)
    recent_pairs = db.query(
        EmailMessage.from_inbox_id,
        EmailMessage.bot_email_id
    ).filter(
        and_(
            EmailMessage.campaign_id == campaign.id,
            EmailMessage.sent_at >= lookback_time,  # Only check recent interval
            EmailMessage.bot_email_id.isnot(None)
        )
    ).all()
    recently_used = set(recent_pairs)
    
    logger.debug(f"Found {len(recently_used)} pairs used in last {interval_minutes} minutes")
    
    attempts = 0
    while len(pairs) < count and attempts < count * 10:
        user_inbox = random.choice(user_inboxes)
        bot = random.choice(bots)
        
        pair_key = (user_inbox.id, bot.id)
        
        # Only skip if this exact pair was used in the recent interval
        if pair_key not in recently_used:
            # Check daily limit
            inbox_sent = db.query(EmailMessage).filter(
                and_(
                    EmailMessage.from_inbox_id == user_inbox.id,
                    func.date(EmailMessage.sent_at) == today
                )
            ).count()
            
            if inbox_sent < user_inbox.daily_send_limit:
                pairs.append({
                    'from_inbox_id': user_inbox.id,
                    'to_bot_id': bot.id,
                    'to_bot_email': bot.email_address
                })
                recently_used.add(pair_key)
        
        attempts += 1
    
    if len(pairs) < count:
        logger.info(f"⚠️ Only found {len(pairs)}/{count} pairs - some inboxes may have hit daily limits or recently sent")
    
    return pairs


def get_email_template_sync(db, category):
    """Sync version to get email template"""
    templates = db.query(EmailTemplate).filter(
        and_(
            EmailTemplate.is_active == True,
            EmailTemplate.category == category
        )
    ).all()
    
    if templates:
        return random.choice(templates)
    return None


@celery_app.task(name="app.workers.tasks.process_bot_notification")
def process_bot_notification(bot_id: int, history_id: str):
    """
    Process Gmail push notification for instant email handling
    
    This is triggered by the webhook when Gmail notifies us of new emails.
    It's much faster than polling every 10 minutes.
    
    Args:
        bot_id: Bot email ID
        history_id: Gmail history ID from notification
    """
    logger.info(f"🔔 Processing notification for bot {bot_id}, history_id: {history_id}")
    
    db = SessionLocal()
    
    try:
        bot = db.query(BotEmail).filter(BotEmail.id == bot_id).first()
        if not bot:
            logger.error(f"Bot {bot_id} not found")
            return
        
        # Get bot credentials
        credentials = get_bot_credentials(bot)
        service = build('gmail', 'v1', credentials=credentials)
        
        # Get changes since last history ID
        from app.inbox.webhooks import GmailWebhookManager
        access_token = decrypt_token(bot.access_token)
        refresh_token = decrypt_token(bot.refresh_token)
        
        # Get new message IDs from history
        message_ids = GmailWebhookManager.get_history_changes(
            access_token,
            refresh_token,
            bot.watch_history_id or history_id,
            'INBOX'
        )
        
        # Also check spam folder
        spam_message_ids = GmailWebhookManager.get_history_changes(
            access_token,
            refresh_token,
            bot.watch_history_id or history_id,
            'SPAM'
        )
        
        logger.info(f"Found {len(message_ids)} inbox messages, {len(spam_message_ids)} spam messages")
        
        # Process inbox messages
        for msg_id in message_ids:
            process_bot_email_message(db, bot, service, msg_id, is_spam=False)
        
        # Process spam messages (and move them)
        for msg_id in spam_message_ids:
            process_bot_email_message(db, bot, service, msg_id, is_spam=True)
            # Move from spam to inbox
            try:
                service.users().messages().modify(
                    userId='me',
                    id=msg_id,
                    body={'removeLabelIds': ['SPAM'], 'addLabelIds': ['INBOX']}
                ).execute()
                bot.spam_moved_to_inbox += 1
                logger.info(f"✅ Moved message {msg_id} from spam to inbox")
            except Exception as e:
                logger.error(f"Failed to move message from spam: {e}")
        
        # Update bot's history ID
        bot.watch_history_id = history_id
        bot.last_check_at = datetime.utcnow()
        bot.last_activity = datetime.utcnow()
        db.commit()
        
        logger.info(f"✅ Notification processing complete for bot {bot.email_address}")
        
    except Exception as e:
        logger.error(f"Error processing notification for bot {bot_id}: {e}")
        db.rollback()
    finally:
        db.close()


def process_bot_email_message(db, bot: BotEmail, service, msg_id: str, is_spam: bool = False):
    """
    Process a single email message received by a bot
    
    This function:
    1. Extracts sender information
    2. Verifies sender is a monitored user inbox
    3. Logs activity
    4. Queues reply if appropriate
    5. Updates statistics
    """
    try:
        # Get message details
        msg = service.users().messages().get(userId='me', id=msg_id, format='full').execute()
        
        # Extract headers
        headers = msg['payload']['headers']
        from_email = next((h['value'] for h in headers if h['name'].lower() == 'from'), '')
        subject = next((h['value'] for h in headers if h['name'].lower() == 'subject'), '')
        thread_id = msg.get('threadId', '')
        
        # Extract clean sender email
        import re
        email_match = re.search(r'<(.+?)>', from_email)
        sender_email = email_match.group(1) if email_match else from_email.strip()
        
        logger.info(f"Processing email from {sender_email}, subject: {subject}")
        
        # Verify sender is from a user inbox
        user_inbox = db.query(EmailInbox).filter(
            EmailInbox.email_address == sender_email
        ).first()
        
        if not user_inbox:
            logger.info(f"Email from {sender_email} is not from a monitored user inbox - ignoring")
            return
        
        # Check if there's an active assignment
        assignment = db.query(UserBotAssignment).filter(
            and_(
                UserBotAssignment.bot_email_id == bot.id,
                UserBotAssignment.user_email_address == sender_email,
                UserBotAssignment.is_active == True
            )
        ).first()
        
        if not assignment:
            logger.info(f"No active assignment for {sender_email} -> bot {bot.email_address}")
            # Create assignment automatically if user inbox exists
            assignment = UserBotAssignment(
                bot_email_id=bot.id,
                user_email_address=sender_email,
                is_active=True,
                emails_received=0,
                emails_in_spam=0
            )
            db.add(assignment)
            db.flush()
            logger.info(f"Created new assignment for {sender_email} -> bot {bot.email_address}")
        
        # Log activity
        activity = BotActivity(
            bot_email_id=bot.id,
            activity_type='email_received',
            from_email=sender_email,
            subject=subject,
            was_in_spam=is_spam,
            action_taken='queued_reply'
        )
        db.add(activity)
        
        # Update stats
        assignment.emails_received += 1
        if is_spam:
            assignment.emails_in_spam += 1
        
        bot.total_emails_processed += 1
        user_inbox.total_received += 1
        
        # Mark as read
        service.users().messages().modify(
            userId='me',
            id=msg_id,
            body={'removeLabelIds': ['UNREAD']}
        ).execute()
        
        db.commit()
        
        # Queue reply task (with small delay for natural behavior)
        import random
        delay_seconds = random.randint(60, 300)  # 1-5 minutes delay
        reply_to_user_email.apply_async(
            args=[bot.id, sender_email, thread_id, subject],
            countdown=delay_seconds
        )
        
        logger.info(f"✅ Queued reply to {sender_email} with {delay_seconds}s delay")
        
    except Exception as e:
        logger.error(f"Error processing message {msg_id}: {e}")
        db.rollback()


@celery_app.task(name="app.workers.tasks.refresh_gmail_watches")
def refresh_gmail_watches():
    """
    Refresh Gmail watch subscriptions for all active bots
    
    Gmail watches expire after 7 days, so we need to renew them periodically.
    This task runs daily to ensure watches stay active.
    """
    logger.info("=== Refreshing Gmail watch subscriptions ===")
    
    db = SessionLocal()
    
    try:
        # Get all active bots with watches
        bots = db.query(BotEmail).filter(
            and_(
                BotEmail.status == BotEmailStatus.ACTIVE,
                BotEmail.watch_history_id.isnot(None)  # Has watch setup
            )
        ).all()
        
        logger.info(f"Found {len(bots)} bots with active watches")
        
        from app.inbox.webhooks import GmailWebhookManager
        
        for bot in bots:
            try:
                # Check if watch is expiring soon (within 24 hours)
                from datetime import datetime
                current_time = int(datetime.utcnow().timestamp() * 1000)  # Convert to milliseconds
                
                if bot.watch_expiration and bot.watch_expiration - current_time < 86400000:  # 24 hours
                    logger.info(f"Refreshing watch for bot {bot.email_address}")
                    
                    # Decrypt tokens
                    access_token = decrypt_token(bot.access_token)
                    refresh_token = decrypt_token(bot.refresh_token)
                    
                    # Setup new watch
                    watch_response = GmailWebhookManager.setup_watch(
                        access_token,
                        refresh_token,
                        topic_name=settings.gmail_pubsub_topic
                    )
                    
                    # Update bot record
                    bot.watch_history_id = watch_response.get('historyId')
                    bot.watch_expiration = watch_response.get('expiration')
                    
                    logger.info(f"✅ Refreshed watch for bot {bot.email_address}")
                else:
                    logger.debug(f"Watch for bot {bot.email_address} is still valid")
                
            except Exception as e:
                logger.error(f"Error refreshing watch for bot {bot.id}: {e}")
                bot.last_error = f"Watch refresh failed: {str(e)}"
        
        db.commit()
        logger.info("=== Gmail watch refresh complete ===")
        
    except Exception as e:
        logger.error(f"Error in refresh_gmail_watches: {e}")
        db.rollback()
    finally:
        db.close()


def calculate_optimal_batch_size(db, campaign, remaining_quota):
    """
    Calculate optimal batch size for this run to distribute emails throughout the day
    
    Args:
        db: Database session
        campaign: Campaign object
        remaining_quota: How many emails can still be sent today
        
    Returns:
        Number of emails to send in this batch
    """
    from app.db.models import SystemSetting
    
    # Get task interval from database settings
    result = db.query(SystemSetting).filter(
        SystemSetting.setting_key == 'task_interval_minutes'
    ).first()
    
    task_interval_minutes = int(result.setting_value) if result else 30
    
    # Calculate how many runs are left today
    now = datetime.utcnow()
    minutes_until_midnight = (24 - now.hour) * 60 - now.minute
    runs_remaining = max(1, minutes_until_midnight // task_interval_minutes)
    
    # Distribute remaining quota across remaining runs
    batch_size = max(1, remaining_quota // runs_remaining)
    
    logger.info(
        f"Campaign {campaign.id}: {remaining_quota} emails remaining, "
        f"{runs_remaining} runs left today, batch size: {batch_size}"
    )
    
    return batch_size


def increment_campaign_volume_sync(db, campaign):
    """
    Increment campaign daily volume based on date tracking
    """
    from app.db.models import SystemSetting
    
    # Get warmup settings
    increment_days_result = db.query(SystemSetting).filter(
        SystemSetting.setting_key == 'warmup_increment_days'
    ).first()
    
    increment_amount_result = db.query(SystemSetting).filter(
        SystemSetting.setting_key == 'warmup_increment_amount'
    ).first()
    
    increment_days = int(increment_days_result.setting_value) if increment_days_result else 3
    increment_amount = int(increment_amount_result.setting_value) if increment_amount_result else 5
    
    today = date.today()
    
    # Check if we should increment
    if campaign.last_volume_increase_date is None:
        # First time - set to today, don't increment yet
        campaign.last_volume_increase_date = today
        db.commit()
        logger.info(f"Campaign {campaign.id}: Initialized volume tracking")
        return
    
    days_since_last_increase = (today - campaign.last_volume_increase_date).days
    
    if days_since_last_increase >= increment_days:
        # Time to increase volume
        old_volume = campaign.current_daily_volume
        campaign.current_daily_volume = min(
            campaign.current_daily_volume + increment_amount,
            campaign.target_daily_volume
        )
        campaign.last_volume_increase_date = today
        db.commit()
        
        logger.info(
            f"Campaign {campaign.id}: Volume increased from {old_volume} to {campaign.current_daily_volume} "
            f"(after {days_since_last_increase} days)"
        )
    else:
        logger.info(
            f"Campaign {campaign.id}: Volume stays at {campaign.current_daily_volume} "
            f"({days_since_last_increase}/{increment_days} days since last increase)"
        )


def update_inbox_warmup_stages_sync(db, campaign):
    """Update warmup stages for all inboxes in campaign based on volume"""
    
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
