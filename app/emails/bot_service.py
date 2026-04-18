"""Gmail API helper for bot email management"""
import base64
from typing import List, Dict, Optional
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.auth.transport.requests import Request
from datetime import datetime
from sqlalchemy.orm import Session
import logging

logger = logging.getLogger(__name__)


class GmailBotService:
    """Service for managing Gmail bot emails"""
    
    def __init__(self, access_token: str, refresh_token: str, bot_instance=None, db: Session = None):
        """Initialize Gmail service
        
        Args:
            access_token: Decrypted access token
            refresh_token: Decrypted refresh token
            bot_instance: BotEmail model instance for token refresh
            db: Database session for token updates
        """
        self.credentials = Credentials(
            token=access_token,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token"
        )
        self.bot_instance = bot_instance
        self.db = db
        
        # Validate and refresh if needed
        if bot_instance and db:
            from app.inbox.oauth import validate_and_refresh_credentials
            self.credentials = validate_and_refresh_credentials(
                self.credentials, db, bot_instance
            )
        
        self.service = build('gmail', 'v1', credentials=self.credentials)
    
    def _handle_api_call_with_retry(self, api_call_func):
        """Execute API call with automatic retry on 401 error
        
        Safe for Celery async operations - uses separate DB session for token updates
        
        Args:
            api_call_func: Lambda/function that executes the API call
            
        Returns:
            Result of the API call
        """
        try:
            return api_call_func()
        except HttpError as e:
            if e.resp.status == 401 and self.bot_instance and self.db:
                logger.warning(f"401 error for bot {self.bot_instance.email_address}, refreshing token and retrying...")
                try:
                    # Force refresh
                    self.credentials.refresh(Request())
                    
                    # Update in separate session (safe for Celery tasks)
                    from app.core.database import SessionLocal
                    from app.core.security import encrypt_data
                    
                    refresh_db = SessionLocal()
                    try:
                        bot_type = type(self.bot_instance)
                        fresh_bot = refresh_db.query(bot_type).filter(
                            bot_type.id == self.bot_instance.id
                        ).first()
                        if fresh_bot:
                            fresh_bot.access_token = encrypt_data(self.credentials.token)
                            fresh_bot.token_expiry = self.credentials.expiry
                            refresh_db.commit()
                            
                            # Update local instance
                            self.bot_instance.access_token = fresh_bot.access_token
                            self.bot_instance.token_expiry = fresh_bot.token_expiry
                    finally:
                        refresh_db.close()
                    
                    # Rebuild service with new credentials
                    self.service = build('gmail', 'v1', credentials=self.credentials)
                    
                    # Retry the API call
                    return api_call_func()
                except Exception as retry_error:
                    logger.error(f"Retry failed for bot {self.bot_instance.email_address}: {str(retry_error)}")
                    raise
            raise
    
    def check_inbox(self, from_email: Optional[str] = None) -> List[Dict]:
        """Check inbox for new emails"""
        try:
            def _execute():
                query = "is:unread"
                if from_email:
                    query += f" from:{from_email}"
                
                results = self.service.users().messages().list(
                    userId='me',
                    q=query,
                    maxResults=50
                ).execute()
                
                messages = results.get('messages', [])
                email_details = []
                
                for msg in messages:
                    message = self.service.users().messages().get(
                        userId='me',
                        id=msg['id'],
                        format='full'
                    ).execute()
                    
                    email_details.append({
                        'id': msg['id'],
                        'threadId': message.get('threadId'),
                        'snippet': message.get('snippet'),
                        'headers': self._parse_headers(message),
                        'labelIds': message.get('labelIds', [])
                    })
                
                return email_details
            
            return self._handle_api_call_with_retry(_execute)
        except Exception as e:
            logger.error(f"Error checking inbox: {e}")
            return []
    
    def check_spam(self, from_email: Optional[str] = None) -> List[Dict]:
        """Check spam folder for emails"""
        try:
            def _execute():
                query = "in:spam"
                if from_email:
                    query += f" from:{from_email}"
                
                results = self.service.users().messages().list(
                    userId='me',
                    q=query,
                    maxResults=50
                ).execute()
                
                messages = results.get('messages', [])
                spam_details = []
                
                for msg in messages:
                    message = self.service.users().messages().get(
                        userId='me',
                        id=msg['id'],
                        format='full'
                    ).execute()
                    
                    spam_details.append({
                        'id': msg['id'],
                        'threadId': message.get('threadId'),
                        'snippet': message.get('snippet'),
                        'headers': self._parse_headers(message),
                        'labelIds': message.get('labelIds', [])
                    })
                
                return spam_details
            
            return self._handle_api_call_with_retry(_execute)
        except Exception as e:
            logger.error(f"Error checking spam: {e}")
            return []
    
    def mark_as_not_spam(self, message_id: str) -> bool:
        """Mark email as not spam and move to inbox"""
        try:
            def _execute():
                # Remove SPAM label and add INBOX label
                self.service.users().messages().modify(
                    userId='me',
                    id=message_id,
                    body={
                        'removeLabelIds': ['SPAM'],
                        'addLabelIds': ['INBOX']
                    }
                ).execute()
                
                # Also mark as read to indicate it's been processed
                self.service.users().messages().modify(
                    userId='me',
                    id=message_id,
                    body={
                        'removeLabelIds': ['UNREAD']
                    }
                ).execute()
                
                return True
            
            return self._handle_api_call_with_retry(_execute)
        except Exception as e:
            logger.error(f"Error marking as not spam: {e}")
            return False
    
    def mark_as_read(self, message_id: str) -> bool:
        """Mark email as read"""
        try:
            def _execute():
                self.service.users().messages().modify(
                    userId='me',
                    id=message_id,
                    body={
                        'removeLabelIds': ['UNREAD']
                    }
                ).execute()
                return True
            
            return self._handle_api_call_with_retry(_execute)
        except Exception as e:
            logger.error(f"Error marking as read: {e}")
            return False
    
    def send_reply(self, to: str, subject: str, body: str, thread_id: Optional[str] = None) -> bool:
        """Send a reply email"""
        try:
            def _execute():
                message = self._create_message(to, subject, body)
                
                if thread_id:
                    send_message = self.service.users().messages().send(
                        userId='me',
                        body={
                            'raw': message,
                            'threadId': thread_id
                        }
                    ).execute()
                else:
                    send_message = self.service.users().messages().send(
                        userId='me',
                        body={'raw': message}
                    ).execute()
                
                return True
            
            return self._handle_api_call_with_retry(_execute)
        except Exception as e:
            logger.error(f"Error sending reply: {e}")
            return False
    
    def _parse_headers(self, message: Dict) -> Dict:
        """Parse email headers"""
        headers = {}
        for header in message.get('payload', {}).get('headers', []):
            name = header.get('name', '').lower()
            value = header.get('value', '')
            
            if name in ['from', 'to', 'subject', 'date']:
                headers[name] = value
        
        return headers
    
    def _create_message(self, to: str, subject: str, body: str) -> str:
        """Create email message in RFC 2822 format"""
        message = f"To: {to}\nSubject: {subject}\n\n{body}"
        return base64.urlsafe_b64encode(message.encode()).decode()
