"""
Health check and monitoring for Celery workers and beat scheduler.
"""
from datetime import datetime, timedelta
from typing import Dict, Any
from celery import Celery
from celery.app.control import Inspect
import redis
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.workers.celery_app import celery_app
from app.core.config import get_settings
from app.db.models import TaskConfiguration

settings = get_settings()


async def check_celery_workers() -> Dict[str, Any]:
    """Check if Celery workers are running and responsive."""
    try:
        # Check worker stats with timeout
        inspect = celery_app.control.inspect(timeout=2.0)
        
        # Get active workers
        stats = inspect.stats()
        active = inspect.active()
        registered = inspect.registered()
        
        if not stats:
            # Workers might be running but not responding - check alternative method
            # Try to get registered tasks which is faster
            if registered:
                workers_info = []
                for worker_name, tasks in registered.items():
                    worker_info = {
                        "name": worker_name,
                        "status": "online",
                        "pool_size": 0,
                        "active_tasks": len(active.get(worker_name, [])) if active else 0,
                        "registered_tasks": len(tasks)
                    }
                    workers_info.append(worker_info)
                
                return {
                    "status": "healthy",
                    "workers_count": len(registered),
                    "message": "Celery workers are running",
                    "workers": workers_info
                }
            
            return {
                "status": "warning",
                "workers_count": 0,
                "message": "Celery workers may be starting up or not responding to inspect",
                "workers": []
            }
        
        workers_info = []
        for worker_name, worker_stats in stats.items():
            worker_info = {
                "name": worker_name,
                "status": "online",
                "pool_size": worker_stats.get('pool', {}).get('max-concurrency', 0),
                "active_tasks": len(active.get(worker_name, [])) if active else 0,
                "registered_tasks": len(registered.get(worker_name, [])) if registered else 0,
            }
            workers_info.append(worker_info)
        
        return {
            "status": "healthy",
            "workers_count": len(stats),
            "message": "Celery workers are running",
            "workers": workers_info
        }
    
    except Exception as e:
        return {
            "status": "error",
            "workers_count": 0,
            "message": f"Failed to connect to Celery workers: {str(e)}",
            "workers": []
        }


async def check_celery_beat() -> Dict[str, Any]:
    """Check if Celery Beat scheduler is running."""
    try:
        # Check Redis for beat heartbeat
        redis_client = redis.from_url(settings.celery_broker_url)
        
        # Celery beat stores its heartbeat in Redis
        # Check if there's been a recent schedule update
        inspect = celery_app.control.inspect()
        scheduled = inspect.scheduled()
        
        if scheduled is None:
            # Try to check if beat is running by checking Redis keys
            beat_keys = redis_client.keys('celery-beat-*')
            if beat_keys:
                return {
                    "status": "healthy",
                    "message": "Celery Beat scheduler is running",
                    "last_heartbeat": "Active"
                }
            else:
                return {
                    "status": "warning",
                    "message": "Celery Beat status unclear - no scheduled tasks or heartbeat found",
                    "last_heartbeat": "Unknown"
                }
        
        # Count scheduled tasks across all workers
        total_scheduled = sum(len(tasks) for tasks in scheduled.values()) if scheduled else 0
        
        return {
            "status": "healthy",
            "message": "Celery Beat scheduler is running",
            "scheduled_tasks": total_scheduled,
            "last_heartbeat": datetime.utcnow().isoformat()
        }
    
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to check Celery Beat: {str(e)}",
            "last_heartbeat": None
        }


async def check_redis() -> Dict[str, Any]:
    """Check if Redis is accessible."""
    try:
        redis_client = redis.from_url(settings.celery_broker_url)
        redis_client.ping()
        
        # Get Redis info
        info = redis_client.info()
        
        return {
            "status": "healthy",
            "message": "Redis is accessible",
            "version": info.get('redis_version', 'unknown'),
            "connected_clients": info.get('connected_clients', 0),
            "used_memory_human": info.get('used_memory_human', 'unknown')
        }
    
    except Exception as e:
        return {
            "status": "error",
            "message": f"Redis connection failed: {str(e)}"
        }


async def check_database(db: AsyncSession) -> Dict[str, Any]:
    """Check if database is accessible and get basic stats."""
    try:
        # Simple query to check connection
        result = await db.execute(select(func.count()).select_from(TaskConfiguration))
        task_count = result.scalar()
        
        return {
            "status": "healthy",
            "message": "Database is accessible",
            "task_configurations": task_count
        }
    
    except Exception as e:
        return {
            "status": "error",
            "message": f"Database connection failed: {str(e)}"
        }


async def get_scheduled_tasks_info() -> Dict[str, Any]:
    """Get information about scheduled periodic tasks."""
    try:
        inspect = celery_app.control.inspect()
        
        # Get active tasks
        active_tasks = inspect.active()
        active_count = sum(len(tasks) for tasks in active_tasks.values()) if active_tasks else 0
        
        # Get scheduled tasks
        scheduled_tasks = inspect.scheduled()
        scheduled_count = sum(len(tasks) for tasks in scheduled_tasks.values()) if scheduled_tasks else 0
        
        # Get reserved tasks
        reserved_tasks = inspect.reserved()
        reserved_count = sum(len(tasks) for tasks in reserved_tasks.values()) if reserved_tasks else 0
        
        return {
            "active_tasks": active_count,
            "scheduled_tasks": scheduled_count,
            "reserved_tasks": reserved_count,
            "total_tasks": active_count + scheduled_count + reserved_count
        }
    
    except Exception as e:
        return {
            "active_tasks": 0,
            "scheduled_tasks": 0,
            "reserved_tasks": 0,
            "total_tasks": 0,
            "error": str(e)
        }


async def get_system_health(db: AsyncSession) -> Dict[str, Any]:
    """Get complete system health status."""
    workers = await check_celery_workers()
    beat = await check_celery_beat()
    redis_status = await check_redis()
    db_status = await check_database(db)
    tasks_info = await get_scheduled_tasks_info()
    
    # Determine overall health
    all_healthy = all([
        workers["status"] in ["healthy", "warning"],  # Allow warning for workers
        beat["status"] == "healthy",
        redis_status["status"] == "healthy",
        db_status["status"] == "healthy"
    ])
    
    overall_status = "healthy" if all_healthy else "degraded"
    if workers["status"] == "error" or redis_status["status"] == "error":
        overall_status = "critical"
    
    return {
        "status": overall_status,
        "timestamp": datetime.utcnow().isoformat(),
        "components": {
            "celery_workers": workers,
            "celery_beat": beat,
            "redis": redis_status,
            "database": db_status
        },
        "tasks": tasks_info
    }
