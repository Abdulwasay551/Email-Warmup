"""Admin API routes"""
from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import List
from app.core.database import get_db
from app.admin.dependencies import require_admin
from app.admin import schemas, service
from app.auth.dependencies import get_current_user
from app.db.models import User, UserRole
from app.core.config import get_settings
from app.inbox.oauth import get_authorization_url, exchange_code_for_tokens, get_user_email_sync
import secrets

router = APIRouter(prefix="/admin", tags=["admin"])
templates = Jinja2Templates(directory="templates")
settings = get_settings()


# Web Routes (HTML)
@router.get("/dashboard", response_class=HTMLResponse, name="admin_dashboard")
async def admin_dashboard(
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin)
):
    """Admin dashboard page"""
    # Get quick stats
    stats = await service.get_dashboard_stats(db)
    
    return templates.TemplateResponse(
        "admin/dashboard.html",
        {
            "request": request,
            "user": admin,
            "stats": stats,
            "settings": settings
        }
    )


# Bot Email Management
@router.get("/bots", response_model=List[schemas.BotEmailResponse])
async def list_bots(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin)
):
    """List all bot emails (Admin only)"""
    bots = await service.get_all_bots(db)
    return bots


@router.get("/bots/health", response_model=schemas.BotHealthStatus)
async def get_bots_health(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin)
):
    """Get overall bot health status (Admin only)"""
    summary = await service.get_bot_health_summary(db)
    bots = await service.get_all_bots(db)
    
    return {
        **summary,
        "bots": bots
    }


@router.post("/bots", response_model=schemas.BotEmailResponse, status_code=status.HTTP_201_CREATED)
async def create_bot(
    bot_data: schemas.BotEmailCreate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin)
):
    """Create new bot email (Admin only)"""
    # Check if bot email already exists
    existing = await service.get_bot_by_email(db, bot_data.email_address)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Bot email already exists"
        )
    
    bot = await service.create_bot_email(
        db=db,
        email_address=bot_data.email_address,
        provider=bot_data.provider,
        client_id=bot_data.client_id,
        client_secret=bot_data.client_secret
    )
    await db.commit()
    
    return bot


@router.get("/bots/{bot_id}", response_model=schemas.BotEmailResponse)
async def get_bot(
    bot_id: int,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin)
):
    """Get bot email details (Admin only)"""
    bot = await service.get_bot_by_id(db, bot_id)
    if not bot:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Bot email not found"
        )
    return bot


@router.patch("/bots/{bot_id}", response_model=schemas.BotEmailResponse)
async def update_bot(
    bot_id: int,
    bot_data: schemas.BotEmailUpdate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin)
):
    """Update bot email (Admin only)"""
    bot = await service.update_bot_email(
        db=db,
        bot_id=bot_id,
        status=bot_data.status,
        client_id=bot_data.client_id,
        client_secret=bot_data.client_secret
    )
    
    if not bot:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Bot email not found"
        )
    
    await db.commit()
    return bot


@router.delete("/bots/{bot_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_bot(
    bot_id: int,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin)
):
    """Delete bot email (Admin only)"""
    success = await service.delete_bot_email(db, bot_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Bot email not found"
        )
    await db.commit()


@router.get("/bots/{bot_id}/oauth/connect")
async def connect_bot_oauth(
    bot_id: int,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin)
):
    """Initiate OAuth flow for bot email (Admin only)"""
    bot = await service.get_bot_by_id(db, bot_id)
    if not bot:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Bot email not found"
        )
    
    # Generate OAuth URL with state containing bot_id
    # Use "bot_" prefix to distinguish from user inbox OAuth
    state = f"bot_{bot_id}_{secrets.token_urlsafe(16)}"
    
    # Use bot-specific callback URI
    bot_redirect_uri = "http://localhost:8000/admin/bots/oauth/callback"
    authorization_url, _ = get_authorization_url(state, redirect_uri=bot_redirect_uri)
    
    return RedirectResponse(url=authorization_url)


@router.get("/bots/oauth/callback")
async def bot_oauth_callback(
    code: str,
    state: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Handle OAuth callback for bot emails (distinct from user inbox OAuth)"""
    # CRITICAL: Validate state starts with "bot_" to distinguish from user OAuth
    if not state or not state.startswith("bot_"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid OAuth state - not a bot OAuth flow"
        )
    
    # Extract bot_id from state
    try:
        state_parts = state.split("_")
        if len(state_parts) < 3:  # Should be: bot_<id>_<random>
            raise ValueError("Invalid state format")
        bot_id = int(state_parts[1])
    except (IndexError, ValueError) as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid OAuth state format: {str(e)}"
        )
    
    # Verify bot exists before exchanging tokens
    bot = await service.get_bot_by_id(db, bot_id)
    if not bot:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Bot email with ID {bot_id} not found"
        )
    
    try:
        # Exchange code for tokens using bot callback URI
        bot_redirect_uri = "http://localhost:8000/admin/bots/oauth/callback"
        tokens = await exchange_code_for_tokens(code, redirect_uri=bot_redirect_uri)
        
        # Get email from access token
        email = get_user_email_sync(tokens['access_token'])
        
        # IMPORTANT: Update bot with OAuth tokens (stored separately from user inbox tokens)
        await service.update_bot_oauth_tokens(
            db=db,
            bot_id=bot_id,
            access_token=tokens["access_token"],
            refresh_token=tokens["refresh_token"],
            email_address=email,
            token_expiry=tokens.get("token_expiry")
        )
        
        await db.commit()
        
        # Redirect to admin dashboard with success message
        return RedirectResponse(
            url="/admin/dashboard?success=bot_connected", 
            status_code=status.HTTP_303_SEE_OTHER
        )
    except Exception as e:
        await db.rollback()
        return RedirectResponse(
            url=f"/admin/dashboard?error=bot_oauth_failed&message={str(e)}",
            status_code=status.HTTP_303_SEE_OTHER
        )


@router.get("/bots/{bot_id}/activities", response_model=List[schemas.BotActivityResponse])
async def get_bot_activities(
    bot_id: int,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin)
):
    """Get bot activity log (Admin only)"""
    bot = await service.get_bot_by_id(db, bot_id)
    if not bot:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Bot email not found"
        )
    
    activities = await service.get_bot_activities(db, bot_id, limit)
    return activities


@router.get("/bots/{bot_id}/assignments", response_model=List[schemas.UserBotAssignmentResponse])
async def get_bot_assignments(
    bot_id: int,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin)
):
    """Get all user assignments for a bot (Admin only)"""
    assignments = await service.get_bot_assignments(db, bot_id)
    return assignments


# User Bot Assignment (Regular Users)
@router.post("/assignments", response_model=schemas.UserBotAssignmentResponse, status_code=status.HTTP_201_CREATED)
async def create_assignment(
    assignment_data: schemas.UserBotAssignmentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create user bot assignment (assign user email to bot for monitoring)"""
    # Verify bot exists
    bot = await service.get_bot_by_id(db, assignment_data.bot_email_id)
    if not bot:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Bot email not found"
        )
    
    try:
        assignment = await service.create_user_bot_assignment(
            db=db,
            user_id=current_user.id,
            bot_email_id=assignment_data.bot_email_id,
            user_email_address=assignment_data.user_email_address,
            check_spam=assignment_data.check_spam,
            auto_report_not_spam=assignment_data.auto_report_not_spam
        )
        await db.commit()
        return assignment
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to create assignment: {str(e)}"
        )


@router.get("/assignments", response_model=List[schemas.UserBotAssignmentResponse])
async def get_my_assignments(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get current user's bot assignments"""
    assignments = await service.get_user_assignments(db, current_user.id)
    return assignments


# User Management (Admin only)
@router.get("/users", response_model=List[schemas.UserResponse])
async def list_users(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin)
):
    """List all users (Admin only)"""
    users = await service.get_all_users(db)
    return users


@router.post("/users", response_model=schemas.UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    user_data: schemas.UserCreate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin)
):
    """Create new user (Admin only)"""
    # Check if user exists
    from app.auth.service import get_user_by_email
    existing = await get_user_by_email(db, user_data.email)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User with this email already exists"
        )
    
    # Parse role
    try:
        role = UserRole(user_data.role)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid role. Must be 'admin' or 'user'"
        )
    
    user = await service.create_user_admin(
        db=db,
        email=user_data.email,
        password=user_data.password,
        full_name=user_data.full_name,
        role=role
    )
    await db.commit()
    
    return user


@router.patch("/users/{user_id}/role", response_model=schemas.UserResponse)
async def update_user_role(
    user_id: int,
    role: str,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin)
):
    """Update user role (Admin only)"""
    try:
        user_role = UserRole(role)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid role. Must be 'admin' or 'user'"
        )
    
    user = await service.update_user_role(db, user_id, user_role)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    await db.commit()
    return user


# Campaign Management (Admin only)
@router.get("/campaigns", response_model=List[schemas.CampaignResponse])
async def list_all_campaigns(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin)
):
    """List all campaigns across all users (Admin only)"""
    campaigns = await service.get_all_campaigns(db)
    return campaigns


@router.get("/campaigns/{campaign_id}", response_model=schemas.CampaignResponse)
async def get_campaign_details(
    campaign_id: int,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin)
):
    """Get campaign details (Admin only)"""
    campaign = await service.get_campaign_by_id(db, campaign_id)
    if not campaign:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Campaign not found"
        )
    return campaign


# Analytics (Admin only)
@router.get("/analytics/summary", response_model=schemas.AnalyticsSummary)
async def get_analytics_summary(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin)
):
    """Get overall platform analytics (Admin only)"""
    summary = await service.get_analytics_summary(db)
    return summary


# Email Template Management
@router.get("/templates", response_model=List[schemas.EmailTemplateResponse])
async def list_templates(
    active_only: bool = False,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin)
):
    """List all email templates (Admin only)"""
    templates_list = await service.get_all_templates(db, active_only)
    return templates_list


@router.get("/templates/category/{category}", response_model=List[schemas.EmailTemplateResponse])
async def get_templates_by_category(
    category: str,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin)
):
    """Get templates by category (Admin only)"""
    templates_list = await service.get_templates_by_category(db, category)
    return templates_list


@router.post("/templates", response_model=schemas.EmailTemplateResponse, status_code=status.HTTP_201_CREATED)
async def create_template(
    template: schemas.EmailTemplateCreate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin)
):
    """Create new email template (Admin only)"""
    new_template = await service.create_template(
        db,
        name=template.name,
        subject=template.subject,
        body=template.body,
        category=template.category,
        variables=template.variables
    )
    return new_template


@router.get("/templates/{template_id}", response_model=schemas.EmailTemplateResponse)
async def get_template(
    template_id: int,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin)
):
    """Get email template by ID (Admin only)"""
    template = await service.get_template_by_id(db, template_id)
    if not template:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Template not found"
        )
    return template


@router.patch("/templates/{template_id}", response_model=schemas.EmailTemplateResponse)
async def update_template(
    template_id: int,
    template_update: schemas.EmailTemplateUpdate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin)
):
    """Update email template (Admin only)"""
    updated_template = await service.update_template(
        db,
        template_id=template_id,
        name=template_update.name,
        subject=template_update.subject,
        body=template_update.body,
        category=template_update.category,
        variables=template_update.variables,
        is_active=template_update.is_active
    )
    
    if not updated_template:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Template not found"
        )
    
    return updated_template


@router.delete("/templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_template(
    template_id: int,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin)
):
    """Delete email template (Admin only)"""
    success = await service.delete_template(db, template_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Template not found"
        )
    
    await db.commit()
    return {"message": "Template deleted successfully"}


# ============================================================================
# TASK CONFIGURATION MANAGEMENT (Dynamic Scheduling)
# ============================================================================

@router.get("/tasks", response_model=List[schemas.TaskConfigResponse])
async def list_task_configs(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin)
):
    """List all task configurations (Admin only)"""
    tasks = await service.get_all_task_configs(db)
    return tasks


@router.get("/tasks/{task_id}", response_model=schemas.TaskConfigResponse)
async def get_task_config(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin)
):
    """Get specific task configuration (Admin only)"""
    task = await service.get_task_config(db, task_id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task configuration not found"
        )
    return task


@router.put("/tasks/{task_id}", response_model=schemas.TaskConfigResponse)
async def update_task_config(
    task_id: int,
    task_update: schemas.TaskConfigUpdate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin)
):
    """Update task configuration interval (Admin only)"""
    task = await service.update_task_config(db, task_id, task_update)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task configuration not found"
        )
    
    await db.commit()
    return task


@router.post("/tasks/{task_id}/toggle")
async def toggle_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin)
):
    """Enable/disable a task (Admin only)"""
    task = await service.toggle_task(db, task_id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task configuration not found"
        )
    
    await db.commit()
    return {
        "message": f"Task {'enabled' if task.is_enabled else 'disabled'} successfully",
        "is_enabled": task.is_enabled
    }


# System Settings Management
@router.get("/settings/warmup", response_model=schemas.WarmupSettingsResponse)
async def get_warmup_settings(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin)
):
    """Get warmup configuration settings (Admin only)"""
    settings_dict = await service.get_warmup_settings(db)
    return settings_dict


@router.put("/settings/warmup", response_model=schemas.WarmupSettingsResponse)
async def update_warmup_settings(
    settings_update: schemas.WarmupSettingsUpdate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin)
):
    """Update warmup configuration settings (Admin only)"""
    updated_settings = await service.update_warmup_settings(db, settings_update)
    await db.commit()
    return updated_settings


# Security Events & Cross-Account Protection
@router.get("/security-events", response_class=HTMLResponse, name="admin_security_events")
async def security_events_dashboard(
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin)
):
    """Security events dashboard page (Admin only) - Deprecated, use tab instead"""
    return RedirectResponse(url="/admin/dashboard")


@router.get("/security-events/data")
async def get_security_events_data(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin)
):
    """Get security events data for AJAX loading"""
    from app.db.models import SecurityEventLog, ReauthenticationRequest, EmailInbox, BotEmail, InboxStatus, BotEmailStatus
    from app.auth.token_revocation_handler import TokenRevocationHandler
    from datetime import datetime, timedelta
    
    # Get recent security events
    security_events = await db.execute(
        select(SecurityEventLog).order_by(SecurityEventLog.received_at.desc()).limit(50)
    )
    events = security_events.scalars().all()
    
    # Get tokens expiring soon
    from app.core.database import SessionLocal
    sync_db = SessionLocal()
    try:
        expiring_tokens = TokenRevocationHandler.check_expiring_soon(sync_db, hours=48)
    finally:
        sync_db.close()
    
    # Calculate stats
    events_24h = await db.execute(
        select(func.count(SecurityEventLog.id)).where(
            SecurityEventLog.received_at > datetime.utcnow() - timedelta(hours=24)
        )
    )
    events_24h_count = events_24h.scalar() or 0
    
    disconnected_inboxes = await db.execute(
        select(func.count(EmailInbox.id)).where(
            EmailInbox.status == InboxStatus.DISCONNECTED
        )
    )
    disconnected_inboxes_count = disconnected_inboxes.scalar() or 0
    
    disconnected_bots = await db.execute(
        select(func.count(BotEmail.id)).where(
            BotEmail.status == BotEmailStatus.DISCONNECTED
        )
    )
    disconnected_bots_count = disconnected_bots.scalar() or 0
    
    reauth_pending = await db.execute(
        select(func.count(ReauthenticationRequest.id)).where(
            ReauthenticationRequest.status == 'pending'
        )
    )
    reauth_pending_count = reauth_pending.scalar() or 0
    
    return {
        "stats": {
            'events_24h': events_24h_count,
            'expiring_soon': len(expiring_tokens),
            'disconnected': disconnected_inboxes_count + disconnected_bots_count,
            'reauth_pending': reauth_pending_count
        },
        "events": [
            {
                "id": event.id,
                "email": event.subject_email,
                "event_type": ", ".join(event.event_types) if hasattr(event, 'event_types') else "Security Event",
                "description": event.description if hasattr(event, 'description') else None,
                "action_taken": "Account marked as disconnected",
                "created_at": event.received_at.isoformat() if event.received_at else None
            }
            for event in events
        ]
    }


@router.get("/security-events-legacy", response_class=HTMLResponse)
async def security_events_dashboard(
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin)
):
    """Security events dashboard page (Admin only)"""
    from app.db.models import SecurityEventLog, ReauthenticationRequest, EmailInbox, BotEmail, InboxStatus, BotEmailStatus
    from app.auth.token_revocation_handler import TokenRevocationHandler
    from datetime import datetime, timedelta
    
    # Get recent security events
    security_events = await db.execute(
        select(SecurityEventLog).order_by(SecurityEventLog.received_at.desc()).limit(50)
    )
    security_events = security_events.scalars().all()
    
    # Get pending reauthentication requests
    reauth_requests = await db.execute(
        select(ReauthenticationRequest).where(
            ReauthenticationRequest.status == 'pending'
        ).order_by(ReauthenticationRequest.created_at.desc())
    )
    reauth_requests = reauth_requests.scalars().all()
    
    # Get tokens expiring soon (using sync db for now)
    from app.core.database import SessionLocal
    sync_db = SessionLocal()
    try:
        expiring_tokens = TokenRevocationHandler.check_expiring_soon(sync_db, hours=48)
    finally:
        sync_db.close()
    
    # Calculate stats
    events_24h = await db.execute(
        select(func.count(SecurityEventLog.id)).where(
            SecurityEventLog.received_at > datetime.utcnow() - timedelta(hours=24)
        )
    )
    events_24h_count = events_24h.scalar() or 0
    
    disconnected_inboxes = await db.execute(
        select(func.count(EmailInbox.id)).where(
            EmailInbox.status == InboxStatus.DISCONNECTED
        )
    )
    disconnected_inboxes_count = disconnected_inboxes.scalar() or 0
    
    disconnected_bots = await db.execute(
        select(func.count(BotEmail.id)).where(
            BotEmail.status == BotEmailStatus.DISCONNECTED
        )
    )
    disconnected_bots_count = disconnected_bots.scalar() or 0
    
    reauth_pending = await db.execute(
        select(func.count(ReauthenticationRequest.id)).where(
            ReauthenticationRequest.status == 'pending'
        )
    )
    reauth_pending_count = reauth_pending.scalar() or 0
    
    stats = {
        'events_24h': events_24h_count,
        'expiring_soon': len(expiring_tokens),
        'disconnected': disconnected_inboxes_count + disconnected_bots_count,
        'reauth_pending': reauth_pending_count
    }
    
    return templates.TemplateResponse(
        "admin/security_events.html",
        {
            "request": request,
            "user": admin,
            "settings": settings,
            "security_events": security_events,
            "expiring_tokens": expiring_tokens,
            "reauth_requests": reauth_requests,
            "stats": stats,
            "base_url": request.base_url.scheme + "://" + request.base_url.netloc
        }
    )


@router.post("/api/security/refresh-token")
async def refresh_token_endpoint(
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin)
):
    """Manually refresh an OAuth token (Admin only)"""
    from app.auth.token_revocation_handler import TokenRevocationHandler
    import json
    
    try:
        body = await request.json()
        token_type = body.get('type')
        token_id = body.get('id')
        
        if not token_type or not token_id:
            return {"success": False, "error": "Missing type or id"}
        
        if token_type == 'user_inbox':
            success = TokenRevocationHandler.attempt_token_refresh(
                db=db,
                inbox_id=token_id
            )
        elif token_type == 'bot_email':
            success = TokenRevocationHandler.attempt_token_refresh(
                db=db,
                bot_id=token_id
            )
        else:
            return {"success": False, "error": "Invalid type"}
        
        if success:
            await db.commit()
            return {"success": True}
        else:
            return {"success": False, "error": "Token refresh failed"}
    
    except Exception as e:
        return {"success": False, "error": str(e)}


