from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
from google.auth.exceptions import OAuthError
from typing import Optional, Dict, Any, Union, TYPE_CHECKING
import json
import requests
import logging
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import encrypt_data, decrypt_data

if TYPE_CHECKING:
    from app.db.models import EmailInbox, BotEmail

logger = logging.getLogger(__name__)

settings = get_settings()

# OAuth 2.0 scopes for Gmail
SCOPES = [
    'https://www.googleapis.com/auth/gmail.send',
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.modify',
    'https://www.googleapis.com/auth/userinfo.email'
]


def get_oauth_flow(redirect_uri: Optional[str] = None) -> Flow:
    """Create OAuth flow for Gmail"""
    client_config = {
        "web": {
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [redirect_uri or settings.google_redirect_uri]
        }
    }
    
    # Sort scopes to ensure consistent ordering
    sorted_scopes = sorted(SCOPES)
    
    flow = Flow.from_client_config(
        client_config,
        scopes=sorted_scopes,
        redirect_uri=redirect_uri or settings.google_redirect_uri
    )
    
    return flow


def get_authorization_url(state: Optional[str] = None, redirect_uri: Optional[str] = None) -> tuple[str, str]:
    """Get Gmail OAuth authorization URL"""
    flow = get_oauth_flow(redirect_uri=redirect_uri)
    
    authorization_url, state = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true',
        prompt='consent',  # Force consent to get refresh token
        state=state  # Pass custom state for bot OAuth
    )
    
    return authorization_url, state


async def exchange_code_for_tokens(code: str, redirect_uri: Optional[str] = None) -> Dict[str, Any]:
    """Exchange authorization code for access and refresh tokens
    
    Uses manual token exchange to avoid scope validation issues where Google
    returns scopes in different order or adds additional scopes like 'openid'
    """
    logger.info("Exchanging authorization code for tokens")
    
    try:
        # Manually exchange authorization code for tokens
        # This avoids the strict scope validation in google_auth_oauthlib
        token_url = "https://oauth2.googleapis.com/token"
        data = {
            'code': code,
            'client_id': settings.google_client_id,
            'client_secret': settings.google_client_secret,
            'redirect_uri': redirect_uri or settings.google_redirect_uri,
            'grant_type': 'authorization_code'
        }
        
        response = requests.post(token_url, data=data)
        response.raise_for_status()
        token_data = response.json()
        
        logger.info(f"Token exchange successful. Granted scopes: {token_data.get('scope', '')}")
        
        # Verify that all required scopes are present (order doesn't matter)
        granted_scopes = set(token_data.get('scope', '').split())
        required_scopes = set(SCOPES)
        
        if not required_scopes.issubset(granted_scopes):
            missing_scopes = required_scopes - granted_scopes
            error_msg = f"Missing required scopes: {', '.join(missing_scopes)}"
            logger.error(error_msg)
            raise ValueError(error_msg)
        
        # Parse expiry time (use timezone-aware datetime)
        from datetime import datetime, timedelta, timezone
        expiry = datetime.now(timezone.utc) + timedelta(seconds=token_data.get('expires_in', 3600))
        
        return {
            'access_token': token_data['access_token'],
            'refresh_token': token_data.get('refresh_token'),
            'token_expiry': expiry,
            'scopes': list(granted_scopes)
        }
    except requests.exceptions.HTTPError as e:
        logger.error(f"HTTP error during token exchange: {e.response.text if e.response else str(e)}")
        raise ValueError(f"Failed to exchange authorization code: {str(e)}")
    except Exception as e:
        logger.error(f"Token exchange failed: {str(e)}")
        raise


def get_credentials_from_tokens(access_token: str, refresh_token: str) -> Credentials:
    """Create credentials object from tokens"""
    return Credentials(
        token=access_token,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        scopes=SCOPES
    )


def refresh_access_token(refresh_token: str) -> Dict[str, Any]:
    """Refresh access token using refresh token"""
    credentials = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        scopes=SCOPES
    )
    
    credentials.refresh(Request())
    
    return {
        'access_token': credentials.token,
        'token_expiry': credentials.expiry
    }


def get_user_email_sync(access_token: str) -> str:
    """Get user email from Gmail API (sync)"""
    credentials = Credentials(
        token=access_token,
        refresh_token=None,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        scopes=SCOPES
    )
    
    service = build('gmail', 'v1', credentials=credentials)
    profile = service.users().getProfile(userId='me').execute()
    
    return profile['emailAddress']


def encrypt_tokens(access_token: str, refresh_token: str) -> tuple[str, str]:
    """Encrypt OAuth tokens"""
    encrypted_access = encrypt_data(access_token)
    encrypted_refresh = encrypt_data(refresh_token) if refresh_token else None
    return encrypted_access, encrypted_refresh


def decrypt_tokens(encrypted_access: str, encrypted_refresh: Optional[str]) -> tuple[str, Optional[str]]:
    """Decrypt OAuth tokens"""
    access_token = decrypt_data(encrypted_access)
    refresh_token = decrypt_data(encrypted_refresh) if encrypted_refresh else None
    return access_token, refresh_token


async def test_inbox_connection(access_token: str) -> bool:
    """Test if inbox connection is working"""
    try:
        credentials = Credentials(
            token=access_token,
            refresh_token=None,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=settings.google_client_id,
            client_secret=settings.google_client_secret,
            scopes=SCOPES
        )
        
        service = build('gmail', 'v1', credentials=credentials)
        service.users().getProfile(userId='me').execute()
        return True
    except Exception:
        return False


def validate_and_refresh_credentials(
    credentials: Credentials,
    db: Session,
    model_instance: Union['EmailInbox', 'BotEmail']
) -> Credentials:
    """
    Validate credentials and refresh if expired or expiring soon.
    Updates the database with new tokens after refresh.
    
    IMPORTANT: Uses a separate database session for token updates to avoid
    interfering with the parent Celery task's transaction. This is safe for
    async queue operations where tasks can be stopped at any time.
    
    Args:
        credentials: Google OAuth2 Credentials object
        db: Database session (only used to get model_instance ID and type)
        model_instance: EmailInbox or BotEmail model instance
        
    Returns:
        Updated Credentials object with refreshed token if needed
    """
    from app.core.security import encrypt_data
    from app.core.database import SessionLocal
    
    # Check if token is expired or expiring within 5 minutes
    needs_refresh = False
    
    if credentials.expired:
        logger.info(f"Token expired for {model_instance.email_address}, refreshing...")
        needs_refresh = True
    elif credentials.expiry:
        # Refresh if expiring within 5 minutes
        time_until_expiry = credentials.expiry - datetime.now(timezone.utc)
        if time_until_expiry.total_seconds() < 300:  # 5 minutes
            logger.info(f"Token expiring soon for {model_instance.email_address}, refreshing...")
            needs_refresh = True
    
    if needs_refresh:
        # Use a separate DB session for token update to avoid interfering
        # with parent Celery task's transaction
        token_db = SessionLocal()
        try:
            # Refresh the token
            credentials.refresh(Request())
            logger.info(f"Token refreshed successfully for {model_instance.email_address}")
            
            # Get fresh instance in the new session
            model_type = type(model_instance)
            fresh_instance = token_db.query(model_type).filter(
                model_type.id == model_instance.id
            ).first()
            
            if not fresh_instance:
                logger.error(f"Could not find {model_type.__name__} {model_instance.id} for token update")
                return credentials
            
            # Update database with new token
            fresh_instance.access_token = encrypt_data(credentials.token)
            fresh_instance.token_expiry = credentials.expiry
            
            # Commit in separate session (won't affect parent task)
            token_db.commit()
            
            # Update the original instance's attributes (not persisted until parent commits)
            model_instance.access_token = fresh_instance.access_token
            model_instance.token_expiry = fresh_instance.token_expiry
            
            logger.info(f"Database updated with new token for {model_instance.email_address}")
            
        except Exception as e:
            logger.error(f"Failed to refresh token for {model_instance.email_address}: {str(e)}")
            token_db.rollback()
            raise
        finally:
            token_db.close()
    
    return credentials


def get_validated_credentials(
    access_token: str,
    refresh_token: str,
    db: Session,
    model_instance: Union['EmailInbox', 'BotEmail']
) -> Credentials:
    """
    Get credentials and validate/refresh them automatically.
    
    Args:
        access_token: Decrypted access token
        refresh_token: Decrypted refresh token
        db: Database session
        model_instance: EmailInbox or BotEmail model instance
        
    Returns:
        Validated and potentially refreshed Credentials object
    """
    # Create credentials object
    credentials = get_credentials_from_tokens(access_token, refresh_token)
    
    # Validate and refresh if needed
    credentials = validate_and_refresh_credentials(credentials, db, model_instance)
    
    return credentials
