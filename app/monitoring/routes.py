"""
Health check API endpoints.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.monitoring.health import (
    get_system_health,
    check_celery_workers,
    check_celery_beat,
    check_redis,
    get_scheduled_tasks_info
)

router = APIRouter(prefix="/api/monitoring", tags=["monitoring"])


@router.get("/health")
async def health_check(db: AsyncSession = Depends(get_db)):
    """
    Complete system health check.
    Returns status of all components: Celery workers, Beat scheduler, Redis, and Database.
    """
    health_status = await get_system_health(db)
    
    # Return 503 if system is critical
    if health_status["status"] == "critical":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=health_status
        )
    
    return health_status


@router.get("/health/workers")
async def workers_health():
    """Check Celery workers health."""
    return await check_celery_workers()


@router.get("/health/beat")
async def beat_health():
    """Check Celery Beat scheduler health."""
    return await check_celery_beat()


@router.get("/health/redis")
async def redis_health():
    """Check Redis connection health."""
    return await check_redis()


@router.get("/health/tasks")
async def tasks_status():
    """Get current tasks status."""
    return await get_scheduled_tasks_info()


@router.get("/ping")
async def ping():
    """Simple ping endpoint for basic API health check."""
    return {
        "status": "ok",
        "message": "API is running"
    }
