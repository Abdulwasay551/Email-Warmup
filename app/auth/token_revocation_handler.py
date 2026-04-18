"""
Token Revocation Handler

Handles OAuth token revocation events and automatic recovery.
Works with Cross-Account Protection to detect and respond to:
- Expired tokens
- Revoked tokens
- Invalid tokens during scheduled tasks
"""

import logging
from datetime import datetime, timedelta
from typing import Optional, List, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.db.models import EmailInbox, BotEmail, InboxStatus, BotEmailStatus
from app.auth.cross_account_protection import SecurityEvent, CrossAccountProtectionManager
from app.core.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)


class TokenRevocationHandler:
    """Handle OAuth token revocations and recovery"""
    
    @staticmethod
    def mark_inbox_disconnected(
        db: Session,
        email_address: str,
        reason: str,
        security_event: Optional[SecurityEvent] = None
    ) -> Tuple[int, int]:
        """
        Mark user inboxes and bot emails as disconnected
        
        Args:
            db: Database session
            email_address: Email address affected
            reason: Reason for disconnection
            security_event: Optional security event that triggered this
            
        Returns:
            Tuple of (user_inboxes_affected, bot_emails_affected)
        """
        user_inboxes_affected = 0
        bot_emails_affected = 0
        
        try:
            # Update user inboxes
            user_inboxes = db.query(EmailInbox).filter(
                EmailInbox.email_address == email_address
            ).all()
            
            for inbox in user_inboxes:
                inbox.status = InboxStatus.DISCONNECTED
                inbox.last_error = reason
                inbox.updated_at = datetime.utcnow()
                user_inboxes_affected += 1
                
                logger.warning(
                    f"Marked user inbox {inbox.id} ({email_address}) as DISCONNECTED: {reason}"
                )
            
            # Update bot emails
            bot_emails = db.query(BotEmail).filter(
                BotEmail.email_address == email_address
            ).all()
            
            for bot in bot_emails:
                bot.status = BotEmailStatus.DISCONNECTED
                bot.last_error = reason
                bot.last_check_at = datetime.utcnow()
                bot.consecutive_errors += 1
                bot.is_healthy = False
                bot_emails_affected += 1
                
                logger.warning(
                    f"Marked bot email {bot.id} ({email_address}) as DISCONNECTED: {reason}"
                )
            
            db.commit()
            
            return (user_inboxes_affected, bot_emails_affected)
            
        except Exception as e:
            logger.error(f"Error marking {email_address} as disconnected: {e}")
            db.rollback()
            return (0, 0)
    
    @staticmethod
    def handle_security_event(
        db: Session,
        security_event: SecurityEvent
    ) -> dict:
        """
        Handle a security event from Cross-Account Protection
        
        Args:
            db: Database session
            security_event: The security event to handle
            
        Returns:
            Dictionary with handling results
        """
        email = security_event.subject.email
        event_desc = security_event.get_event_description()
        
        logger.warning(
            f"Handling security event for {email}: {event_desc}"
        )
        
        # Mark affected accounts as disconnected
        user_count, bot_count = TokenRevocationHandler.mark_inbox_disconnected(
            db=db,
            email_address=email,
            reason=f"Security event: {event_desc}",
            security_event=security_event
        )
        
        # Generate reauthentication URLs
        reauth_urls = {}
        if user_count > 0:
            reauth_urls['user'] = CrossAccountProtectionManager.create_reauth_url(
                email=email,
                redirect_uri=f"{settings.base_url}/inbox/oauth/callback"
            )
        if bot_count > 0:
            reauth_urls['bot'] = CrossAccountProtectionManager.create_reauth_url(
                email=email,
                redirect_uri=f"{settings.base_url}/admin/bots/oauth/callback"
            )
        
        result = {
            'email': email,
            'event_type': security_event.event_types,
            'description': event_desc,
            'user_inboxes_affected': user_count,
            'bot_emails_affected': bot_count,
            'reauth_urls': reauth_urls,
            'timestamp': datetime.utcnow().isoformat()
        }
        
        logger.info(f"Security event handling complete: {result}")
        
        return result
    
    @staticmethod
    def check_expired_tokens(db: Session) -> List[dict]:
        """
        Check for expired tokens and mark them as disconnected
        
        Args:
            db: Database session
            
        Returns:
            List of affected accounts
        """
        now = datetime.utcnow()
        affected = []
        
        try:
            # Check user inboxes with expired tokens
            expired_inboxes = db.query(EmailInbox).filter(
                EmailInbox.token_expiry < now,
                EmailInbox.status == InboxStatus.ACTIVE
            ).all()
            
            for inbox in expired_inboxes:
                inbox.status = InboxStatus.DISCONNECTED
                inbox.last_error = "OAuth token expired"
                inbox.updated_at = now
                
                affected.append({
                    'type': 'user_inbox',
                    'id': inbox.id,
                    'email': inbox.email_address,
                    'reason': 'token_expired'
                })
                
                logger.warning(
                    f"User inbox {inbox.id} ({inbox.email_address}) "
                    f"token expired on {inbox.token_expiry}"
                )
            
            # Check bot emails with expired tokens
            expired_bots = db.query(BotEmail).filter(
                BotEmail.token_expiry < now,
                BotEmail.status == BotEmailStatus.ACTIVE
            ).all()
            
            for bot in expired_bots:
                bot.status = BotEmailStatus.DISCONNECTED
                bot.last_error = "OAuth token expired"
                bot.last_check_at = now
                bot.is_healthy = False
                bot.consecutive_errors += 1
                
                affected.append({
                    'type': 'bot_email',
                    'id': bot.id,
                    'email': bot.email_address,
                    'reason': 'token_expired'
                })
                
                logger.warning(
                    f"Bot email {bot.id} ({bot.email_address}) "
                    f"token expired on {bot.token_expiry}"
                )
            
            if affected:
                db.commit()
                logger.info(f"Marked {len(affected)} accounts with expired tokens as disconnected")
            
            return affected
            
        except Exception as e:
            logger.error(f"Error checking expired tokens: {e}")
            db.rollback()
            return []
    
    @staticmethod
    def check_expiring_soon(db: Session, hours: int = 48) -> List[dict]:
        """
        Check for tokens expiring soon
        
        Args:
            db: Database session (sync Session, not AsyncSession)
            hours: How many hours ahead to check
            
        Returns:
            List of accounts with tokens expiring soon
        """
        cutoff = datetime.utcnow() + timedelta(hours=hours)
        expiring_soon = []
        
        try:
            # Ensure we're using a sync session
            if hasattr(db, 'execute'):
                # This is likely an AsyncSession, we need sync
                # For now, return empty list and log warning
                logger.warning("check_expiring_soon called with AsyncSession, returning empty list")
                return []
            
            # Check user inboxes
            user_inboxes = db.query(EmailInbox).filter(
                EmailInbox.token_expiry < cutoff,
                EmailInbox.token_expiry > datetime.utcnow(),
                EmailInbox.status == InboxStatus.ACTIVE
            ).all()
            
            for inbox in user_inboxes:
                expiring_soon.append({
                    'type': 'user_inbox',
                    'id': inbox.id,
                    'email': inbox.email_address,
                    'expires_at': inbox.token_expiry.isoformat(),
                    'hours_remaining': (inbox.token_expiry - datetime.utcnow()).total_seconds() / 3600
                })
            
            # Check bot emails
            bot_emails = db.query(BotEmail).filter(
                BotEmail.token_expiry < cutoff,
                BotEmail.token_expiry > datetime.utcnow(),
                BotEmail.status == BotEmailStatus.ACTIVE
            ).all()
            
            for bot in bot_emails:
                expiring_soon.append({
                    'type': 'bot_email',
                    'id': bot.id,
                    'email': bot.email_address,
                    'expires_at': bot.token_expiry.isoformat(),
                    'hours_remaining': (bot.token_expiry - datetime.utcnow()).total_seconds() / 3600
                })
            
            if expiring_soon:
                logger.info(
                    f"Found {len(expiring_soon)} accounts with tokens expiring "
                    f"within {hours} hours"
                )
            
            return expiring_soon
            
        except Exception as e:
            logger.error(f"Error checking expiring tokens: {e}")
            return []
    
    @staticmethod
    def attempt_token_refresh(
        db: Session,
        inbox_id: Optional[int] = None,
        bot_id: Optional[int] = None
    ) -> bool:
        """
        Attempt to refresh an OAuth token
        
        Args:
            db: Database session
            inbox_id: User inbox ID (if refreshing user inbox)
            bot_id: Bot email ID (if refreshing bot email)
            
        Returns:
            True if refresh successful, False otherwise
        """
        from app.inbox.oauth import GoogleOAuthManager
        
        try:
            if inbox_id:
                inbox = db.query(EmailInbox).filter(EmailInbox.id == inbox_id).first()
                if not inbox or not inbox.refresh_token:
                    logger.error(f"Cannot refresh inbox {inbox_id}: not found or no refresh token")
                    return False
                
                # Attempt refresh
                oauth_manager = GoogleOAuthManager()
                try:
                    new_tokens = oauth_manager.refresh_access_token(inbox.refresh_token)
                    
                    # Update inbox
                    inbox.access_token = new_tokens['access_token']
                    inbox.token_expiry = new_tokens['token_expiry']
                    inbox.status = InboxStatus.ACTIVE
                    inbox.last_error = None
                    inbox.updated_at = datetime.utcnow()
                    
                    db.commit()
                    
                    logger.info(f"Successfully refreshed token for inbox {inbox_id} ({inbox.email_address})")
                    return True
                    
                except Exception as refresh_error:
                    logger.error(f"Token refresh failed for inbox {inbox_id}: {refresh_error}")
                    
                    # Mark as disconnected if refresh fails
                    inbox.status = InboxStatus.DISCONNECTED
                    inbox.last_error = f"Token refresh failed: {str(refresh_error)}"
                    db.commit()
                    
                    return False
            
            elif bot_id:
                bot = db.query(BotEmail).filter(BotEmail.id == bot_id).first()
                if not bot or not bot.refresh_token:
                    logger.error(f"Cannot refresh bot {bot_id}: not found or no refresh token")
                    return False
                
                # Attempt refresh (using bot's own OAuth credentials)
                oauth_manager = GoogleOAuthManager(
                    client_id=bot.client_id,
                    client_secret=bot.client_secret
                )
                
                try:
                    new_tokens = oauth_manager.refresh_access_token(bot.refresh_token)
                    
                    # Update bot
                    bot.access_token = new_tokens['access_token']
                    bot.token_expiry = new_tokens['token_expiry']
                    bot.status = BotEmailStatus.ACTIVE
                    bot.last_error = None
                    bot.is_healthy = True
                    bot.consecutive_errors = 0
                    bot.last_check_at = datetime.utcnow()
                    
                    db.commit()
                    
                    logger.info(f"Successfully refreshed token for bot {bot_id} ({bot.email_address})")
                    return True
                    
                except Exception as refresh_error:
                    logger.error(f"Token refresh failed for bot {bot_id}: {refresh_error}")
                    
                    # Mark as disconnected if refresh fails
                    bot.status = BotEmailStatus.DISCONNECTED
                    bot.last_error = f"Token refresh failed: {str(refresh_error)}"
                    bot.is_healthy = False
                    bot.consecutive_errors += 1
                    db.commit()
                    
                    return False
            
            return False
            
        except Exception as e:
            logger.error(f"Error in attempt_token_refresh: {e}")
            db.rollback()
            return False
