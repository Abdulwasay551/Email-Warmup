"""
Cross-Account Protection (CAP) for Google OAuth

This module implements Google's Cross-Account Protection (RISC) to detect
and handle security events like:
- Token revocation
- Account disabled
- Session hijacking
- Password changes

References:
- https://developers.google.com/identity/protocols/risc
- https://openid.net/specs/openid-risc-profile-1_0.html
"""

import jwt
import json
import logging
import base64
from typing import Dict, Optional, Any, List
from datetime import datetime, timedelta
from enum import Enum
import requests

from app.core.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)


class SecurityEventType(str, Enum):
    """Security event types from Google RISC"""
    TOKEN_REVOKED = "https://schemas.openid.net/secevent/oauth/event-type/token-revoked"
    ACCOUNT_DISABLED = "https://schemas.openid.net/secevent/risc/event-type/account-disabled"
    ACCOUNT_ENABLED = "https://schemas.openid.net/secevent/risc/event-type/account-enabled"
    ACCOUNT_PURGED = "https://schemas.openid.net/secevent/risc/event-type/account-purged"
    CREDENTIAL_CHANGE = "https://schemas.openid.net/secevent/risc/event-type/credential-change"
    SESSIONS_REVOKED = "https://schemas.openid.net/secevent/oauth/event-type/sessions-revoked"


class SecurityEventSubject:
    """Subject of a security event"""
    
    def __init__(self, subject_data: dict):
        self.email = subject_data.get('email')
        self.sub = subject_data.get('sub')  # Google user ID
        self.subject_type = subject_data.get('subject_type', 'email')
    
    def __repr__(self):
        return f"SecurityEventSubject(email={self.email}, sub={self.sub})"


class SecurityEvent:
    """Parsed security event from Google"""
    
    def __init__(self, event_token: str, event_data: dict):
        self.raw_token = event_token
        self.raw_data = event_data
        
        # Parse JWT claims
        self.issuer = event_data.get('iss')
        self.issued_at = datetime.fromtimestamp(event_data.get('iat', 0))
        self.jwt_id = event_data.get('jti')
        self.audience = event_data.get('aud')
        
        # Parse subject
        subject_data = event_data.get('sub_id') or event_data.get('subject', {})
        if isinstance(subject_data, str):
            subject_data = {'email': subject_data}
        self.subject = SecurityEventSubject(subject_data)
        
        # Parse events
        self.events = event_data.get('events', {})
        self.event_types = list(self.events.keys())
        
    def is_token_revoked(self) -> bool:
        """Check if this is a token revocation event"""
        return SecurityEventType.TOKEN_REVOKED in self.event_types
    
    def is_account_disabled(self) -> bool:
        """Check if this is an account disabled event"""
        return SecurityEventType.ACCOUNT_DISABLED in self.event_types
    
    def is_sessions_revoked(self) -> bool:
        """Check if all sessions were revoked"""
        return SecurityEventType.SESSIONS_REVOKED in self.event_types
    
    def is_credential_change(self) -> bool:
        """Check if credentials (password) changed"""
        return SecurityEventType.CREDENTIAL_CHANGE in self.event_types
    
    def requires_reauthentication(self) -> bool:
        """Check if this event requires user reauthentication"""
        return (
            self.is_token_revoked() or 
            self.is_account_disabled() or 
            self.is_sessions_revoked() or
            self.is_credential_change()
        )
    
    def get_event_description(self) -> str:
        """Get human-readable description of the event"""
        if self.is_token_revoked():
            return "OAuth token was revoked"
        elif self.is_account_disabled():
            return "Google account was disabled"
        elif self.is_sessions_revoked():
            return "All sessions were revoked"
        elif self.is_credential_change():
            return "Account password was changed"
        else:
            return f"Security event: {', '.join(self.event_types)}"
    
    def __repr__(self):
        return f"SecurityEvent(subject={self.subject.email}, types={self.event_types})"


class CrossAccountProtectionManager:
    """Manager for Google Cross-Account Protection"""
    
    # Google's RISC configuration endpoint
    RISC_CONFIG_URL = "https://accounts.google.com/.well-known/risc-configuration"
    
    @staticmethod
    def verify_and_parse_event(event_token: str) -> Optional[SecurityEvent]:
        """
        Verify and parse a Security Event Token (SET)
        
        Args:
            event_token: The JWT token from Google
            
        Returns:
            SecurityEvent object if valid, None otherwise
        """
        try:
            # For production, fetch Google's public keys and verify signature
            # For now, decode without verification (UNSAFE in production)
            # TODO: Implement proper JWT signature verification with Google's keys
            
            decoded = jwt.decode(
                event_token,
                options={"verify_signature": False},  # UNSAFE: Enable in production
                algorithms=["RS256"]
            )
            
            # Verify issuer
            if decoded.get('iss') not in ['accounts.google.com', 'https://accounts.google.com']:
                logger.warning(f"Invalid issuer: {decoded.get('iss')}")
                return None
            
            # Verify audience (should be our client ID)
            aud = decoded.get('aud')
            if aud and aud != settings.google_client_id:
                logger.warning(f"Invalid audience: {aud}")
                return None
            
            return SecurityEvent(event_token, decoded)
            
        except jwt.InvalidTokenError as e:
            logger.error(f"Invalid JWT token: {e}")
            return None
        except Exception as e:
            logger.error(f"Error parsing security event: {e}")
            return None
    
    @staticmethod
    def get_jwks_uri() -> Optional[str]:
        """
        Get the JWKS URI for verifying Google's signatures
        
        Returns:
            JWKS URI string
        """
        try:
            response = requests.get(
                CrossAccountProtectionManager.RISC_CONFIG_URL,
                timeout=10
            )
            response.raise_for_status()
            config = response.json()
            return config.get('jwks_uri')
        except Exception as e:
            logger.error(f"Error fetching RISC configuration: {e}")
            return None
    
    @staticmethod
    def enable_cap_for_client() -> bool:
        """
        Enable Cross-Account Protection for our OAuth client
        
        This needs to be done in Google Cloud Console:
        1. Go to APIs & Services > Credentials
        2. Edit OAuth 2.0 Client ID
        3. Add Security Event Token (SET) endpoint URL
        4. Enable RISC
        
        Returns:
            True if successful
        """
        # This is informational - actual setup is done in Google Cloud Console
        logger.info("""
        To enable Cross-Account Protection:
        1. Go to https://console.cloud.google.com/apis/credentials
        2. Edit your OAuth 2.0 Client ID
        3. Add this webhook URL: {base_url}/auth/api/security-events
        4. Enable RISC (Risky Information Sharing and Communication)
        """.format(base_url=settings.base_url))
        return True
    
    @staticmethod
    def create_reauth_url(email: str, redirect_uri: str) -> str:
        """
        Create a reauthentication URL for a user
        
        Args:
            email: User's email address
            redirect_uri: Where to redirect after auth
            
        Returns:
            OAuth authorization URL
        """
        from urllib.parse import urlencode
        
        params = {
            'client_id': settings.google_client_id,
            'redirect_uri': redirect_uri,
            'response_type': 'code',
            'scope': ' '.join([
                'openid',
                'email',
                'profile',
                'https://www.googleapis.com/auth/gmail.readonly',
                'https://www.googleapis.com/auth/gmail.send',
                'https://www.googleapis.com/auth/gmail.modify',
            ]),
            'access_type': 'offline',
            'prompt': 'consent',  # Force consent to get new refresh token
            'login_hint': email,  # Pre-fill email
            'state': f'reauth_{email}_{datetime.utcnow().timestamp()}'
        }
        
        return f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"


class SecurityEventLog:
    """Log and track security events"""
    
    def __init__(self):
        self.events = []
    
    def log_event(
        self,
        event: SecurityEvent,
        affected_records: List[str],
        action_taken: str
    ) -> None:
        """
        Log a security event
        
        Args:
            event: The security event
            affected_records: List of affected email addresses or IDs
            action_taken: What action was taken
        """
        log_entry = {
            'timestamp': datetime.utcnow().isoformat(),
            'event_type': event.event_types,
            'subject_email': event.subject.email,
            'affected_records': affected_records,
            'action_taken': action_taken,
            'description': event.get_event_description()
        }
        
        self.events.append(log_entry)
        
        logger.warning(
            f"Security Event: {event.get_event_description()} "
            f"for {event.subject.email}. Action: {action_taken}"
        )
    
    def get_recent_events(self, hours: int = 24) -> List[dict]:
        """Get security events from the last N hours"""
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        return [
            e for e in self.events
            if datetime.fromisoformat(e['timestamp']) > cutoff
        ]


# Global event logger
security_event_logger = SecurityEventLog()
