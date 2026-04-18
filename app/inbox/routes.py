from fastapi import APIRouter, Depends, HTTPException, status, Request, Query, BackgroundTasks
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
import logging

from app.core.database import get_db
from app.auth.dependencies import get_current_user
from app.db.models import User, EmailProvider, InboxStatus, BotEmail, BotEmailStatus
from app.inbox.schemas import InboxResponse, InboxUpdate
from app.inbox.oauth import get_authorization_url, exchange_code_for_tokens, get_user_email_sync
from app.inbox.service import (
    get_user_inboxes,
    get_inbox_by_id,
    get_inbox_by_email,
    create_inbox,
    update_inbox_status,
    delete_inbox
)
from app.inbox.webhooks import GmailWebhookManager
from app.core.config import get_settings

router = APIRouter(prefix="/inbox", tags=["inbox"])
templates = Jinja2Templates(directory="templates")
settings = get_settings()
logger = logging.getLogger(__name__)


# Web Routes (Jinja2 Templates)
@router.get("/connect", response_class=HTMLResponse, name="connect_inbox_page")
async def connect_inbox_page(
    request: Request,
    current_user: User = Depends(get_current_user)
):
    """Render inbox connection page"""
    # Note: get_current_user dependency already raises 401, but for HTML we redirect
    # This is handled by exception handler, but kept for clarity
    return templates.TemplateResponse(
        "inbox/connect.html",
        {
            "request": request,
            "user": current_user,
            "settings": settings
        }
    )


@router.get("/list", response_class=HTMLResponse, name="inbox_list_page")
async def inbox_list_page(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Render inbox list page"""
    from datetime import datetime, timezone
    
    inboxes = await get_user_inboxes(db, current_user.id)
    
    # Convert to dictionaries for JSON serialization
    inboxes_dict = []
    for inbox in inboxes:
        # Check if token is expired or expiring soon
        token_expired = False
        token_expiring_soon = False
        token_expiry_date = None
        
        if inbox.token_expiry:
            now = datetime.now(timezone.utc)
            token_expiry_date = inbox.token_expiry.isoformat()
            token_expired = inbox.token_expiry < now
            # Check if expiring within 48 hours
            token_expiring_soon = not token_expired and (inbox.token_expiry - now).total_seconds() < 172800
        
        inboxes_dict.append({
            "id": inbox.id,
            "email_address": inbox.email_address,
            "provider": inbox.provider.value,
            "domain": inbox.domain,
            "status": inbox.status.value,
            "daily_send_limit": inbox.daily_send_limit,
            "warmup_stage": inbox.warmup_stage,
            "total_sent": inbox.total_sent,
            "total_received": inbox.total_received,
            "last_activity": inbox.last_activity.isoformat() if inbox.last_activity else None,
            "created_at": inbox.created_at.isoformat() if inbox.created_at else None,
            "token_expired": token_expired,
            "token_expiring_soon": token_expiring_soon,
            "token_expiry": token_expiry_date
        })
    
    return templates.TemplateResponse(
        "inbox/list.html",
        {"request": request, "user": current_user, "inboxes": inboxes_dict, "settings": settings}
    )


@router.get("/{inbox_id}", response_class=HTMLResponse, name="inbox_detail_page")
async def inbox_detail_page(
    inbox_id: int,
    request: Request,
    current_user: User = Depends(get_current_user)
):
    """Render inbox detail page"""
    return templates.TemplateResponse(
        "inbox/detail.html",
        {
            "request": request,
            "user": current_user,
            "settings": settings
        }
    )


# API Routes
@router.get("/api/oauth/authorize", name="oauth_authorize")
async def oauth_authorize(
    current_user: User = Depends(get_current_user)
):
    """Initiate OAuth flow for Gmail USER INBOXES
    
    IMPORTANT: This is for user inbox OAuth only.
    Admin bot OAuth is initiated via /admin/bots/{bot_id}/oauth/connect
    """
    try:
        # Generate state without "bot_" prefix (reserved for bot OAuth)
        authorization_url, state = get_authorization_url()
        
        # Ensure state doesn't accidentally start with "bot_"
        if state.startswith("bot_"):
            raise ValueError("Invalid state generated - conflicts with bot OAuth prefix")
        
        # Log the authorization URL for debugging
        logger.info(f"Generated OAuth URL for user inbox")
        logger.info(f"Redirect URI: {settings.google_redirect_uri}")
        logger.info(f"Authorization URL: {authorization_url}")
        
        return JSONResponse({
            "authorization_url": authorization_url,
            "state": state
        })
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to initiate OAuth: {str(e)}"
        )


@router.get("/api/oauth/callback", name="oauth_callback")
async def oauth_callback(
    code: str = Query(...),
    state: str = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Handle OAuth callback from Gmail for USER INBOXES
    
    IMPORTANT: This callback is for user inbox OAuth only.
    Bot email OAuth uses a separate callback at /admin/bots/oauth/callback
    Both flows are distinguished by the state parameter:
    - User inbox OAuth: state does NOT start with "bot_"
    - Bot email OAuth: state starts with "bot_{bot_id}_"
    """
    # CRITICAL: Ensure this is NOT a bot OAuth callback
    if state and state.startswith("bot_"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This endpoint is for user inbox OAuth only. Bot OAuth uses /admin/bots/oauth/callback"
        )
    
    try:
        # Exchange code for tokens
        tokens = await exchange_code_for_tokens(code)
        
        # Get user email
        email = get_user_email_sync(tokens['access_token'])
        
        # Encrypt tokens before storing
        from app.inbox.oauth import encrypt_tokens
        encrypted_access, encrypted_refresh = encrypt_tokens(
            tokens['access_token'],
            tokens['refresh_token']
        )
        
        # Check if inbox already exists
        existing_inbox = await get_inbox_by_email(db, email)
        if existing_inbox:
            if existing_inbox.user_id != current_user.id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="This email is already connected to another account"
                )
            
            # Update existing inbox tokens (encrypted)
            existing_inbox.access_token = encrypted_access
            existing_inbox.refresh_token = encrypted_refresh
            existing_inbox.token_expiry = tokens['token_expiry']
            existing_inbox.status = InboxStatus.ACTIVE
            await db.flush()
            
            return RedirectResponse(
                url="/inbox/list?success=reconnected",
                status_code=status.HTTP_302_FOUND
            )
        
        # Create new inbox (encryption handled by create_inbox)
        await create_inbox(
            db,
            user_id=current_user.id,
            email=email,
            provider=EmailProvider.GMAIL,
            access_token=tokens['access_token'],  # Will be encrypted by create_inbox
            refresh_token=tokens['refresh_token'],
            token_expiry=tokens['token_expiry']
        )
        
        return RedirectResponse(
            url="/inbox/list?success=connected",
            status_code=status.HTTP_302_FOUND
        )
        
    except Exception as e:
        return RedirectResponse(
            url=f"/inbox/connect?error={str(e)}",
            status_code=status.HTTP_302_FOUND
        )


@router.get("/api/inboxes", response_model=List[InboxResponse])
async def list_inboxes(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get all inboxes for current user"""
    inboxes = await get_user_inboxes(db, current_user.id)
    return [InboxResponse.model_validate(inbox) for inbox in inboxes]


@router.get("/api/inboxes/{inbox_id}", response_model=InboxResponse)
async def get_inbox(
    inbox_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get specific inbox"""
    inbox = await get_inbox_by_id(db, inbox_id, current_user.id)
    
    if not inbox:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Inbox not found"
        )
    
    return InboxResponse.model_validate(inbox)


@router.patch("/api/inboxes/{inbox_id}", response_model=InboxResponse)
async def update_inbox(
    inbox_id: int,
    inbox_update: InboxUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Update inbox settings"""
    inbox = await get_inbox_by_id(db, inbox_id, current_user.id)
    
    if not inbox:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Inbox not found"
        )
    
    # Update fields
    if inbox_update.status is not None:
        inbox.status = inbox_update.status
    
    if inbox_update.daily_send_limit is not None:
        inbox.daily_send_limit = inbox_update.daily_send_limit
    
    await db.flush()
    await db.refresh(inbox)
    
    return InboxResponse.model_validate(inbox)


@router.post("/api/inboxes/{inbox_id}/pause")
async def pause_inbox(
    inbox_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Pause inbox"""
    inbox = await update_inbox_status(db, inbox_id, InboxStatus.PAUSED)
    
    if not inbox or inbox.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Inbox not found"
        )
    
    return {"message": "Inbox paused successfully"}


@router.post("/api/inboxes/{inbox_id}/activate")
async def activate_inbox(
    inbox_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Activate inbox"""
    inbox = await update_inbox_status(db, inbox_id, InboxStatus.ACTIVE)
    
    if not inbox or inbox.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Inbox not found"
        )
    
    return {"message": "Inbox activated successfully"}


@router.delete("/api/inboxes/{inbox_id}")
async def remove_inbox(
    inbox_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Delete inbox"""
    success = await delete_inbox(db, inbox_id, current_user.id)
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Inbox not found"
        )
    
    await db.commit()
    return {"message": "Inbox deleted successfully"}


# ============================================================================
# GMAIL WEBHOOK ENDPOINTS FOR BOT EMAIL NOTIFICATIONS
# ============================================================================

@router.post("/api/webhooks/gmail", include_in_schema=False)
async def gmail_webhook_handler(
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db)
):
    """
    Handle Gmail Pub/Sub push notifications
    
    This endpoint receives notifications when emails arrive in bot inboxes.
    Gmail sends a POST request with base64-encoded notification data.
    
    Setup required:
    1. Create a Pub/Sub topic in Google Cloud Console
    2. Grant Gmail API permission to publish to the topic
    3. Create a push subscription pointing to this webhook URL
    4. Call /api/inboxes/{inbox_id}/setup-watch to start receiving notifications
    """
    try:
        # Parse the notification
        body = await request.json()
        
        # Verify this is a valid Gmail notification
        message = body.get('message', {})
        if not message:
            logger.warning("Received webhook with no message")
            return JSONResponse({"status": "ignored"}, status_code=200)
        
        # Parse notification data
        notification = GmailWebhookManager.parse_notification(body)
        
        if not notification:
            logger.error("Failed to parse notification")
            return JSONResponse({"status": "error"}, status_code=400)
        
        email_address = notification.get('email_address')
        history_id = notification.get('history_id')
        
        logger.info(f"Gmail webhook: {email_address}, history_id: {history_id}")
        
        # Find the bot email account
        from sqlalchemy import select
        result = await db.execute(
            select(BotEmail).where(BotEmail.email_address == email_address)
        )
        bot = result.scalar_one_or_none()
        
        if not bot:
            logger.warning(f"Received notification for unknown bot email: {email_address}")
            return JSONResponse({"status": "ignored"}, status_code=200)
        
        # Queue the bot inbox check in the background
        # We import here to avoid circular dependency
        from app.workers.bot_tasks import process_bot_notification
        
        # Trigger immediate inbox check via Celery
        process_bot_notification.delay(bot.id, history_id)
        
        logger.info(f"✅ Queued inbox check for bot {email_address}")
        
        return JSONResponse({"status": "success"}, status_code=200)
        
    except Exception as e:
        logger.error(f"Error processing Gmail webhook: {e}")
        # Return 200 to prevent Gmail from retrying
        return JSONResponse({"status": "error", "message": str(e)}, status_code=200)


@router.get("/api/webhooks/gmail", include_in_schema=False)
async def gmail_webhook_verification(request: Request):
    """
    Handle Gmail webhook verification requests
    
    Some webhook services send a GET request for verification.
    """
    # Return success for verification
    return JSONResponse({"status": "ok"}, status_code=200)


@router.post("/api/inboxes/bot/{bot_id}/setup-watch")
async def setup_bot_watch(
    bot_id: int,
    db: AsyncSession = Depends(get_db)
):
    """
    Setup Gmail push notifications for a bot email
    
    This enables instant email notifications via Gmail Pub/Sub.
    Must be called for each bot that should receive instant notifications.
    
    Prerequisites:
    - Google Cloud Pub/Sub topic created
    - Gmail API permissions configured
    - Push subscription pointing to /api/webhooks/gmail
    """
    try:
        # Get bot email
        from sqlalchemy import select
        result = await db.execute(
            select(BotEmail).where(BotEmail.id == bot_id)
        )
        bot = result.scalar_one_or_none()
        
        if not bot:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Bot email not found"
            )
        
        if bot.status != BotEmailStatus.ACTIVE:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Bot email must be active to setup watch"
            )
        
        # Decrypt tokens
        from app.emails.sender import decrypt_token
        access_token = decrypt_token(bot.access_token)
        refresh_token = decrypt_token(bot.refresh_token)
        
        # Setup Gmail watch
        watch_response = GmailWebhookManager.setup_watch(
            access_token,
            refresh_token,
            topic_name=settings.gmail_pubsub_topic or "gmail-notifications"
        )
        
        # Store watch info in bot record
        bot.watch_history_id = watch_response.get('historyId')
        bot.watch_expiration = watch_response.get('expiration')
        await db.commit()
        
        logger.info(f"✅ Gmail watch setup for bot {bot.email_address}")
        
        return {
            "status": "success",
            "message": "Gmail watch setup successfully",
            "history_id": watch_response.get('historyId'),
            "expiration": watch_response.get('expiration')
        }
        
    except Exception as e:
        logger.error(f"Error setting up Gmail watch: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to setup watch: {str(e)}"
        )
