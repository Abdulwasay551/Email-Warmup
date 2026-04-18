from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import base64
from typing import Optional
from datetime import datetime
from sqlalchemy.orm import Session
import logging

from app.core.config import get_settings
from app.inbox.oauth import get_validated_credentials, decrypt_tokens
from app.db.models import EmailInbox

logger = logging.getLogger(__name__)
settings = get_settings()


def decrypt_token(encrypted_token: str) -> str:
    """Decrypt a single token (wrapper for decrypt_tokens)"""
    decrypted, _ = decrypt_tokens(encrypted_token, None)
    return decrypted


def create_mime_message(
    sender: str,
    to: str,
    subject: str,
    body: str,
    in_reply_to: Optional[str] = None,
    references: Optional[str] = None
) -> MIMEMultipart:
    """Create MIME message"""
    message = MIMEMultipart()
    message['From'] = sender
    message['To'] = to
    message['Subject'] = subject
    
    if in_reply_to:
        message['In-Reply-To'] = in_reply_to
    
    if references:
        message['References'] = references
    
    # Add text body
    msg_text = MIMEText(body, 'plain')
    message.attach(msg_text)
    
    return message


def send_email_via_gmail(
    inbox: EmailInbox,
    to_email: str,
    subject: str,
    body: str,
    thread_id: Optional[str] = None,
    in_reply_to: Optional[str] = None,
    db: Optional[Session] = None
) -> dict:
    """Send email via Gmail API with automatic token refresh"""
    if db is None:
        raise ValueError("Database session is required for token refresh")
    
    try:
        # Decrypt and get credentials
        access_token, refresh_token = decrypt_tokens(
            inbox.access_token,
            inbox.refresh_token
        )
        
        # Get validated credentials (auto-refresh if needed)
        credentials = get_validated_credentials(access_token, refresh_token, db, inbox)
        
        # Build Gmail service
        service = build('gmail', 'v1', credentials=credentials)
        
        # Create message
        message = create_mime_message(
            sender=inbox.email_address,
            to=to_email,
            subject=subject,
            body=body,
            in_reply_to=in_reply_to
        )
        
        # Encode message
        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')
        
        # Send message
        send_body = {'raw': raw_message}
        if thread_id:
            send_body['threadId'] = thread_id
        
        result = service.users().messages().send(
            userId='me',
            body=send_body
        ).execute()
        
        return {
            'success': True,
            'message_id': result['id'],
            'thread_id': result.get('threadId'),
            'sent_at': datetime.utcnow()
        }
        
    except HttpError as e:
        # Handle 401 Unauthorized - try to refresh token once
        if e.resp.status == 401:
            logger.warning(f"401 error for {inbox.email_address}, attempting token refresh and retry...")
            try:
                # Force refresh using separate session (safe for Celery)
                from app.core.database import SessionLocal
                from app.core.security import encrypt_data
                
                access_token, refresh_token = decrypt_tokens(inbox.access_token, inbox.refresh_token)
                credentials = get_validated_credentials(access_token, refresh_token, db, inbox)
                credentials.refresh(Request())
                
                # Update in separate session to avoid affecting parent task
                refresh_db = SessionLocal()
                try:
                    inbox_type = type(inbox)
                    fresh_inbox = refresh_db.query(inbox_type).filter(
                        inbox_type.id == inbox.id
                    ).first()
                    if fresh_inbox:
                        fresh_inbox.access_token = encrypt_data(credentials.token)
                        fresh_inbox.token_expiry = credentials.expiry
                        refresh_db.commit()
                        
                        # Update local instance
                        inbox.access_token = fresh_inbox.access_token
                        inbox.token_expiry = fresh_inbox.token_expiry
                finally:
                    refresh_db.close()
                
                # Retry the send
                service = build('gmail', 'v1', credentials=credentials)
                message = create_mime_message(
                    sender=inbox.email_address,
                    to=to_email,
                    subject=subject,
                    body=body,
                    in_reply_to=in_reply_to
                )
                raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')
                send_body = {'raw': raw_message}
                if thread_id:
                    send_body['threadId'] = thread_id
                
                result = service.users().messages().send(userId='me', body=send_body).execute()
                
                return {
                    'success': True,
                    'message_id': result['id'],
                    'thread_id': result.get('threadId'),
                    'sent_at': datetime.utcnow()
                }
            except Exception as retry_error:
                logger.error(f"Retry failed for {inbox.email_address}: {str(retry_error)}")
                return {'success': False, 'error': f"Authentication failed: {str(retry_error)}"}
        
        logger.error(f"Error sending email from {inbox.email_address}: {str(e)}")
        return {'success': False, 'error': str(e)}
        
    except Exception as e:
        logger.error(f"Error sending email from {inbox.email_address}: {str(e)}")
        return {'success': False, 'error': str(e)}


def check_email_status(
    inbox: EmailInbox,
    message_id: str,
    db: Optional[Session] = None
) -> dict:
    """Check if email was opened (via Gmail API labels) with automatic token refresh"""
    if db is None:
        logger.warning("Database session not provided, token refresh will not be available")
        # Fall back to old behavior
        access_token, refresh_token = decrypt_tokens(inbox.access_token, inbox.refresh_token)
        from app.inbox.oauth import get_credentials_from_tokens
        credentials = get_credentials_from_tokens(access_token, refresh_token)
    else:
        # Use validated credentials
        access_token, refresh_token = decrypt_tokens(inbox.access_token, inbox.refresh_token)
        credentials = get_validated_credentials(access_token, refresh_token, db, inbox)
    
    try:
        # Build Gmail service
        service = build('gmail', 'v1', credentials=credentials)
        
        # Get message
        message = service.users().messages().get(
            userId='me',
            id=message_id,
            format='minimal'
        ).execute()
        
        # Check labels
        labels = message.get('labelIds', [])
        
        return {
            'opened': 'OPENED' in labels or 'INBOX' not in labels,
            'spam': 'SPAM' in labels,
            'trash': 'TRASH' in labels
        }
        
    except HttpError as e:
        if e.resp.status == 401 and db:
            logger.warning(f"401 error checking status for {inbox.email_address}, retrying after refresh...")
            try:
                from google.auth.transport.requests import Request
                from app.core.database import SessionLocal
                from app.core.security import encrypt_data
                
                credentials.refresh(Request())
                
                # Update in separate session (safe for Celery)
                refresh_db = SessionLocal()
                try:
                    inbox_type = type(inbox)
                    fresh_inbox = refresh_db.query(inbox_type).filter(
                        inbox_type.id == inbox.id
                    ).first()
                    if fresh_inbox:
                        fresh_inbox.access_token = encrypt_data(credentials.token)
                        fresh_inbox.token_expiry = credentials.expiry
                        refresh_db.commit()
                        inbox.access_token = fresh_inbox.access_token
                        inbox.token_expiry = fresh_inbox.token_expiry
                finally:
                    refresh_db.close()
                
                service = build('gmail', 'v1', credentials=credentials)
                message = service.users().messages().get(userId='me', id=message_id, format='minimal').execute()
                labels = message.get('labelIds', [])
                return {
                    'opened': 'OPENED' in labels or 'INBOX' not in labels,
                    'spam': 'SPAM' in labels,
                    'trash': 'TRASH' in labels
                }
            except Exception as retry_error:
                logger.error(f"Retry failed: {str(retry_error)}")
                return {}
        logger.error(f"Error checking email status: {str(e)}")
        return {}
    except Exception as e:
        logger.error(f"Error checking email status: {str(e)}")
        return {}


def get_inbox_messages(
    inbox: EmailInbox,
    max_results: int = 10,
    query: Optional[str] = None,
    db: Optional[Session] = None
) -> list:
    """Get recent messages from inbox with automatic token refresh"""
    if db is None:
        logger.warning("Database session not provided, token refresh will not be available")
        access_token, refresh_token = decrypt_tokens(inbox.access_token, inbox.refresh_token)
        from app.inbox.oauth import get_credentials_from_tokens
        credentials = get_credentials_from_tokens(access_token, refresh_token)
    else:
        access_token, refresh_token = decrypt_tokens(inbox.access_token, inbox.refresh_token)
        credentials = get_validated_credentials(access_token, refresh_token, db, inbox)
    
    try:
        # Build Gmail service
        service = build('gmail', 'v1', credentials=credentials)
        
        # List messages
        results = service.users().messages().list(
            userId='me',
            maxResults=max_results,
            q=query
        ).execute()
        
        messages = results.get('messages', [])
        
        detailed_messages = []
        for msg in messages:
            # Get full message
            message = service.users().messages().get(
                userId='me',
                id=msg['id'],
                format='full'
            ).execute()
            
            detailed_messages.append(message)
        
        return detailed_messages
        
    except HttpError as e:
        if e.resp.status == 401 and db:
            logger.warning(f"401 error getting messages for {inbox.email_address}, retrying after refresh...")
            try:
                from google.auth.transport.requests import Request
                from app.core.database import SessionLocal
                from app.core.security import encrypt_data
                
                credentials.refresh(Request())
                
                # Update in separate session (safe for Celery)
                refresh_db = SessionLocal()
                try:
                    inbox_type = type(inbox)
                    fresh_inbox = refresh_db.query(inbox_type).filter(
                        inbox_type.id == inbox.id
                    ).first()
                    if fresh_inbox:
                        fresh_inbox.access_token = encrypt_data(credentials.token)
                        fresh_inbox.token_expiry = credentials.expiry
                        refresh_db.commit()
                        inbox.access_token = fresh_inbox.access_token
                        inbox.token_expiry = fresh_inbox.token_expiry
                finally:
                    refresh_db.close()
                
                service = build('gmail', 'v1', credentials=credentials)
                results = service.users().messages().list(userId='me', maxResults=max_results, q=query).execute()
                messages = results.get('messages', [])
                detailed_messages = []
                for msg in messages:
                    message = service.users().messages().get(userId='me', id=msg['id'], format='full').execute()
                    detailed_messages.append(message)
                return detailed_messages
            except Exception as retry_error:
                logger.error(f"Retry failed: {str(retry_error)}")
                return []
        logger.error(f"Error getting inbox messages: {str(e)}")
        return []
    except Exception as e:
        logger.error(f"Error getting inbox messages: {str(e)}")
        return []


def parse_email_headers(message: dict) -> dict:
    """Parse email headers from Gmail API response"""
    headers = {}
    payload = message.get('payload', {})
    
    for header in payload.get('headers', []):
        name = header.get('name', '').lower()
        value = header.get('value', '')
        headers[name] = value
    
    return headers


def get_email_body(message: dict) -> str:
    """Extract email body from Gmail API response"""
    payload = message.get('payload', {})
    
    # Try to get text/plain part
    if 'parts' in payload:
        for part in payload['parts']:
            if part.get('mimeType') == 'text/plain':
                data = part.get('body', {}).get('data', '')
                if data:
                    return base64.urlsafe_b64decode(data).decode('utf-8')
    
    # Fallback to main body
    data = payload.get('body', {}).get('data', '')
    if data:
        return base64.urlsafe_b64decode(data).decode('utf-8')
    
    return ""
