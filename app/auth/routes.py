from fastapi import APIRouter, Depends, HTTPException, logger, status, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.core.security import create_access_token, create_refresh_token
from app.auth.schemas import UserCreate, UserLogin, TokenResponse, UserResponse
from app.auth.service import create_user, authenticate_user, get_user_by_email
from app.auth.dependencies import get_current_user
from app.db.models import User
from app.core.config import get_settings

router = APIRouter(prefix="/auth", tags=["auth"])
templates = Jinja2Templates(directory="templates")
settings = get_settings()


# Web Routes (Jinja2 Templates)
@router.get("/login", response_class=HTMLResponse, name="login_page")
async def login_page(request: Request, next: str = None):
    """Render login page"""
    return templates.TemplateResponse(
        "auth/login.html", 
        {
            "request": request, 
            "settings": settings,
            "next": next or "/dashboard"
        }
    )


@router.get("/register", response_class=HTMLResponse, name="register_page")
async def register_page(request: Request):
    """Render registration page"""
    return templates.TemplateResponse("auth/register.html", {"request": request, "settings": settings})


@router.get("/logout", name="logout")
async def logout(request: Request):
    """Logout user"""
    response = RedirectResponse(url="/auth/login", status_code=status.HTTP_302_FOUND)
    response.delete_cookie("access_token")
    return response


# API Routes
@router.post("/api/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(
    user_data: UserCreate,
    db: AsyncSession = Depends(get_db)
):
    """Register new user"""
    # Check if user already exists
    existing_user = await get_user_by_email(db, user_data.email)
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )
    
    # Create new user
    user = await create_user(
        db,
        email=user_data.email,
        password=user_data.password,
        full_name=user_data.full_name
    )
    
    # Generate tokens
    access_token = create_access_token(data={"user_id": user.id, "email": user.email})
    refresh_token = create_refresh_token(data={"user_id": user.id})
    
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user=UserResponse.model_validate(user)
    )


@router.post("/api/login", response_model=TokenResponse)
async def login(
    credentials: UserLogin,
    response: Response,
    db: AsyncSession = Depends(get_db)
):
    """Login user"""
    user = await authenticate_user(db, credentials.email, credentials.password)
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Inactive user account"
        )
    
    # Generate tokens
    access_token = create_access_token(data={"user_id": user.id, "email": user.email})
    refresh_token = create_refresh_token(data={"user_id": user.id})
    
    # Set access token in cookie (httponly for security)
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        max_age=1800,  # 30 minutes
        samesite="lax"
    )
    
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user=UserResponse.model_validate(user)
    )


@router.get("/api/me", response_model=UserResponse)
async def get_current_user_info(
    current_user: User = Depends(get_current_user)
):
    """Get current user information"""
    return UserResponse.model_validate(current_user)


# Cross-Account Protection (CAP) / RISC Webhook
@router.post("/api/security-events", include_in_schema=False)
async def handle_security_events(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Handle Google Cross-Account Protection (CAP) security events
    
    This endpoint receives Security Event Tokens (SET) from Google when:
    - OAuth tokens are revoked
    - User accounts are disabled
    - Sessions are revoked
    - Credentials change (password reset)
    
    Setup in Google Cloud Console:
    1. Go to APIs & Services > Credentials
    2. Edit OAuth 2.0 Client ID
    3. Add this URL as the Security Event Receiver endpoint
    4. Enable RISC (Risk and Identity Signal Coordination)
    
    References:
    - https://developers.google.com/identity/protocols/risc
    - https://openid.net/specs/openid-risc-profile-1_0.html
    """
    from app.auth.cross_account_protection import CrossAccountProtectionManager, security_event_logger
    from app.auth.token_revocation_handler import TokenRevocationHandler
    
    try:
        # Get the raw request body
        body = await request.body()
        
        # Parse as JSON
        try:
            data = await request.json()
        except Exception:
            logger.error("Invalid JSON in security event")
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"error": "Invalid JSON"}
            )
        
        # Extract the Security Event Token
        event_token = data.get('token') or data.get('SET')
        
        if not event_token:
            logger.error("No security event token found in request")
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"error": "No security event token"}
            )
        
        # Verify and parse the event
        security_event = CrossAccountProtectionManager.verify_and_parse_event(event_token)
        
        if not security_event:
            logger.error("Failed to verify security event token")
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"error": "Invalid security event token"}
            )
        
        logger.info(
            f"Received security event: {security_event.get_event_description()} "
            f"for {security_event.subject.email}"
        )
        
        # Handle the event (mark accounts as disconnected, etc.)
        result = TokenRevocationHandler.handle_security_event(
            db=db,
            security_event=security_event
        )
        
        # Log the event
        security_event_logger.log_event(
            event=security_event,
            affected_records=[security_event.subject.email],
            action_taken=f"Marked {result['user_inboxes_affected']} user inboxes and "
                        f"{result['bot_emails_affected']} bot emails as disconnected"
        )
        
        # Return success response
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "processed",
                "event_type": security_event.event_types,
                "subject": security_event.subject.email,
                "result": result
            }
        )
        
    except Exception as e:
        logger.error(f"Error handling security event: {e}", exc_info=True)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"error": "Internal server error"}
        )
