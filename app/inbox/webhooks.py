"""
Gmail Pub/Sub webhook handler for instant email notifications

This module handles Gmail Push Notifications via Google Cloud Pub/Sub.
When an email arrives in a bot's inbox, Gmail sends a notification to our webhook,
allowing us to process emails instantly instead of polling every 10 minutes.
"""

import json
import base64
import logging
from typing import Optional
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from sqlalchemy.orm import Session

from app.core.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)


class GmailWebhookManager:
    """Manages Gmail Push Notifications via Pub/Sub"""
    
    @staticmethod
    def setup_watch(
        access_token: str, 
        refresh_token: str, 
        topic_name: str = "gmail-notifications",
        db: Optional[Session] = None,
        model_instance = None
    ) -> dict:
        """
        Set up Gmail watch for push notifications with automatic token refresh
        
        Args:
            access_token: OAuth access token
            refresh_token: OAuth refresh token
            topic_name: Pub/Sub topic name (must be created in GCP first)
            db: Database session for token refresh
            model_instance: EmailInbox or BotEmail instance for token updates
        
        Returns:
            Watch response with historyId and expiration
        """
        try:
            # Get validated credentials if db and model provided
            if db and model_instance:
                from app.inbox.oauth import get_validated_credentials
                credentials = get_validated_credentials(
                    access_token, refresh_token, db, model_instance
                )
            else:
                credentials = Credentials(
                    token=access_token,
                    refresh_token=refresh_token,
                    token_uri="https://oauth2.googleapis.com/token",
                    client_id=settings.google_client_id,
                    client_secret=settings.google_client_secret
                )
            
            service = build('gmail', 'v1', credentials=credentials)
            
            # Setup watch request
            # Topic format: projects/{project_id}/topics/{topic_name}
            request_body = {
                'labelIds': ['INBOX', 'SPAM'],  # Watch both inbox and spam
                'topicName': f'projects/{settings.google_project_id}/topics/{topic_name}'
            }
            
            watch_response = service.users().watch(
                userId='me',
                body=request_body
            ).execute()
            
            logger.info(f"Gmail watch setup successful. History ID: {watch_response.get('historyId')}")
            return watch_response
            
        except HttpError as e:
            logger.error(f"Gmail API error setting up watch: {e}")
            raise
        except Exception as e:
            logger.error(f"Error setting up Gmail watch: {e}")
            raise
    
    @staticmethod
    def stop_watch(access_token: str, refresh_token: str) -> bool:
        """Stop Gmail push notifications"""
        try:
            credentials = Credentials(
                token=access_token,
                refresh_token=refresh_token,
                token_uri="https://oauth2.googleapis.com/token",
                client_id=settings.google_client_id,
                client_secret=settings.google_client_secret
            )
            
            service = build('gmail', 'v1', credentials=credentials)
            service.users().stop(userId='me').execute()
            
            logger.info("Gmail watch stopped successfully")
            return True
            
        except Exception as e:
            logger.error(f"Error stopping Gmail watch: {e}")
            return False
    
    @staticmethod
    def parse_notification(notification_data: dict) -> Optional[dict]:
        """
        Parse Gmail Pub/Sub notification
        
        Args:
            notification_data: Raw notification from Pub/Sub
        
        Returns:
            Parsed notification with email address and history ID
        """
        try:
            # Pub/Sub sends data in base64 encoded format
            message = notification_data.get('message', {})
            data = message.get('data', '')
            
            # Decode base64 data
            decoded_data = base64.b64decode(data).decode('utf-8')
            parsed = json.loads(decoded_data)
            
            return {
                'email_address': parsed.get('emailAddress'),
                'history_id': parsed.get('historyId')
            }
            
        except Exception as e:
            logger.error(f"Error parsing notification: {e}")
            return None
    
    @staticmethod
    def get_history_changes(
        access_token: str,
        refresh_token: str,
        start_history_id: str,
        label_id: str = 'INBOX',
        db: Optional[Session] = None,
        model_instance = None
    ) -> list:
        """
        Get changes since last history ID with automatic token refresh
        
        Args:
            access_token: OAuth access token
            refresh_token: OAuth refresh token
            start_history_id: History ID to start from
            label_id: Label to filter by (INBOX, SPAM, etc.)
            db: Database session for token refresh
            model_instance: EmailInbox or BotEmail instance for token updates
        
        Returns:
            List of message IDs that changed
        """
        try:
            # Get validated credentials if db and model provided
            if db and model_instance:
                from app.inbox.oauth import get_validated_credentials
                credentials = get_validated_credentials(
                    access_token, refresh_token, db, model_instance
                )
            else:
                credentials = Credentials(
                    token=access_token,
                    refresh_token=refresh_token,
                    token_uri="https://oauth2.googleapis.com/token",
                    client_id=settings.google_client_id,
                    client_secret=settings.google_client_secret
                )
            
            service = build('gmail', 'v1', credentials=credentials)
            
            # Get history list
            history_response = service.users().history().list(
                userId='me',
                startHistoryId=start_history_id,
                labelId=label_id,
                historyTypes=['messageAdded']  # Only new messages
            ).execute()
            
            changes = history_response.get('history', [])
            message_ids = []
            
            for change in changes:
                messages_added = change.get('messagesAdded', [])
                for msg_data in messages_added:
                    message = msg_data.get('message', {})
                    msg_id = message.get('id')
                    if msg_id:
                        message_ids.append(msg_id)
            
            logger.info(f"Found {len(message_ids)} new messages in history")
            return message_ids
            
        except HttpError as e:
            if e.resp.status == 404:
                logger.warning("History ID not found, full sync may be needed")
                return []
            logger.error(f"Gmail API error getting history: {e}")
            return []
        except Exception as e:
            logger.error(f"Error getting history changes: {e}")
            return []


def verify_gmail_webhook(token: str) -> bool:
    """
    Verify webhook token from Gmail
    
    For initial setup, Gmail may send a verification challenge.
    This function validates the webhook endpoint.
    """
    try:
        # In production, verify the token matches your expected value
        # For now, we'll accept any token (should be improved)
        return True
    except Exception as e:
        logger.error(f"Webhook verification failed: {e}")
        return False
