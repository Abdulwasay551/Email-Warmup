from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from typing import List, Optional
from datetime import datetime

from app.db.models import EmailInbox, User, InboxStatus, EmailProvider
from app.inbox.oauth import encrypt_tokens, decrypt_tokens, refresh_access_token


async def get_inbox_by_id(db: AsyncSession, inbox_id: int, user_id: int) -> Optional[EmailInbox]:
    """Get inbox by ID for specific user"""
    result = await db.execute(
        select(EmailInbox).where(
            EmailInbox.id == inbox_id,
            EmailInbox.user_id == user_id
        )
    )
    return result.scalar_one_or_none()


async def get_inbox_by_email(db: AsyncSession, email: str) -> Optional[EmailInbox]:
    """Get inbox by email address"""
    result = await db.execute(
        select(EmailInbox).where(EmailInbox.email_address == email)
    )
    return result.scalar_one_or_none()


async def get_user_inboxes(db: AsyncSession, user_id: int) -> List[EmailInbox]:
    """Get all inboxes for a user"""
    result = await db.execute(
        select(EmailInbox).where(EmailInbox.user_id == user_id)
    )
    return result.scalars().all()


async def create_inbox(
    db: AsyncSession,
    user_id: int,
    email: str,
    provider: EmailProvider,
    access_token: str,
    refresh_token: Optional[str],
    token_expiry: datetime
) -> EmailInbox:
    """Create new inbox"""
    # Extract domain
    domain = email.split('@')[1] if '@' in email else None
    
    # Encrypt tokens
    encrypted_access, encrypted_refresh = encrypt_tokens(access_token, refresh_token)
    
    inbox = EmailInbox(
        user_id=user_id,
        email_address=email,
        provider=provider,
        domain=domain,
        access_token=encrypted_access,
        refresh_token=encrypted_refresh,
        token_expiry=token_expiry,
        status=InboxStatus.ACTIVE
    )
    
    db.add(inbox)
    await db.flush()
    await db.refresh(inbox)
    
    return inbox


async def update_inbox_status(
    db: AsyncSession,
    inbox_id: int,
    status: InboxStatus
) -> Optional[EmailInbox]:
    """Update inbox status"""
    result = await db.execute(
        update(EmailInbox)
        .where(EmailInbox.id == inbox_id)
        .values(status=status)
        .returning(EmailInbox)
    )
    inbox = result.scalar_one_or_none()
    await db.flush()
    return inbox


async def update_inbox_tokens(
    db: AsyncSession,
    inbox_id: int,
    access_token: str,
    token_expiry: datetime
) -> Optional[EmailInbox]:
    """Update inbox OAuth tokens"""
    encrypted_access, _ = encrypt_tokens(access_token, None)
    
    result = await db.execute(
        update(EmailInbox)
        .where(EmailInbox.id == inbox_id)
        .values(
            access_token=encrypted_access,
            token_expiry=token_expiry
        )
        .returning(EmailInbox)
    )
    inbox = result.scalar_one_or_none()
    await db.flush()
    return inbox


async def refresh_inbox_token(db: AsyncSession, inbox: EmailInbox) -> str:
    """Refresh inbox access token"""
    # Decrypt refresh token
    _, refresh_token = decrypt_tokens(inbox.access_token, inbox.refresh_token)
    
    if not refresh_token:
        raise ValueError("No refresh token available")
    
    # Get new access token
    token_data = refresh_access_token(refresh_token)
    
    # Update inbox
    await update_inbox_tokens(
        db,
        inbox.id,
        token_data['access_token'],
        token_data['token_expiry']
    )
    
    return token_data['access_token']


async def get_active_inboxes(db: AsyncSession, user_id: Optional[int] = None) -> List[EmailInbox]:
    """Get all active inboxes, optionally filtered by user"""
    query = select(EmailInbox).where(EmailInbox.status == InboxStatus.ACTIVE)
    
    if user_id:
        query = query.where(EmailInbox.user_id == user_id)
    
    result = await db.execute(query)
    return result.scalars().all()


async def delete_inbox(db: AsyncSession, inbox_id: int, user_id: int) -> bool:
    """Delete inbox"""
    inbox = await get_inbox_by_id(db, inbox_id, user_id)
    if not inbox:
        return False
    
    await db.delete(inbox)
    await db.commit()
    return True
