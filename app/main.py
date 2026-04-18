from fastapi import FastAPI, Request, Depends, HTTPException, status
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import logging
from typing import Optional

from app.core.config import get_settings
from app.auth.routes import router as auth_router
from app.inbox.routes import router as inbox_router
from app.campaigns.routes import router as campaign_router
from app.admin.routes import router as admin_router
from app.monitoring.routes import router as monitoring_router
from app.auth.dependencies import get_current_user_optional
from app.db.models import User

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

settings = get_settings()
async def lifespan(app: FastAPI):
    """Application lifespan events"""
    logger.info(f"Starting {settings.app_name}...")
    logger.info(f"Environment: {settings.environment}")
    yield
    logger.info(f"Shutting down {settings.app_name}...")


# Create FastAPI app
app = FastAPI(
    title=settings.app_name,
    description="Email warm-up automation service with AI-powered replies",
    version="1.0.0",
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None,
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Templates
templates = Jinja2Templates(directory="templates")

# Include routers
app.include_router(auth_router)
app.include_router(inbox_router)
app.include_router(campaign_router)
app.include_router(admin_router)
app.include_router(monitoring_router)

# TODO: Add more routers as we build them
# app.include_router(dashboard_router)


@app.get("/", response_class=HTMLResponse, name="home")
async def home(request: Request):
    """Public landing page"""
    return templates.TemplateResponse("home.html", {"request": request, "settings": settings})


@app.get("/privacy", response_class=HTMLResponse, name="privacy")
async def privacy(request: Request):
    """Public privacy policy page"""
    return templates.TemplateResponse("privacy.html", {"request": request, "settings": settings})


@app.get("/terms", response_class=HTMLResponse, name="terms")
async def terms(request: Request):
    """Public terms of service page"""
    return templates.TemplateResponse("terms.html", {"request": request, "settings": settings})


@app.get("/google14f2dc5cb3b9ab3e.html")
async def google_verification():
    """Google Search Console verification"""
    from fastapi.responses import FileResponse
    return FileResponse("static/google14f2dc5cb3b9ab3e.html")


@app.get("/dashboard", response_class=HTMLResponse, name="dashboard")
async def dashboard(
    request: Request,
    current_user: Optional[User] = Depends(get_current_user_optional)
):
    """Dashboard page"""
    # Redirect to login if not authenticated
    if not current_user:
        return RedirectResponse(
            url=f"/auth/login?next={request.url.path}",
            status_code=status.HTTP_302_FOUND
        )
    
    return templates.TemplateResponse(
        "dashboard/home.html",
        {
            "request": request,
            "user": current_user,
            "settings": settings
        }
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Handle HTTP exceptions - redirect to login for 401 on HTML routes"""
    # For 401 Unauthorized on HTML requests, redirect to login
    if exc.status_code == 401:
        # Check if it's an HTML request by looking at Accept header
        accept_header = request.headers.get("accept", "")
        if "text/html" in accept_header or request.url.path.startswith(("/dashboard", "/inbox", "/campaigns", "/admin")):
            # Redirect to login with return URL
            return RedirectResponse(
                url=f"/auth/login?next={request.url.path}",
                status_code=status.HTTP_302_FOUND
            )
    
    # For API requests or other status codes, return JSON
    from fastapi.responses import JSONResponse
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail}
    )


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "app": settings.app_name,
        "environment": settings.environment
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.debug
    )
