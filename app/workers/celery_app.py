from celery import Celery
from celery.schedules import crontab
from datetime import timedelta
from app.core.config import get_settings

settings = get_settings()

# Create Celery app
celery_app = Celery(
    "email_warmup",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=[
        "app.workers.tasks",
        "app.workers.bot_tasks"  # Include bot-based warmup tasks
    ]
)

# Celery configuration
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=30 * 60,  # 30 minutes
    task_soft_time_limit=25 * 60,  # 25 minutes
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=1000,
    # Use dynamic scheduler that reads from database
    beat_scheduler='app.workers.dynamic_scheduler:DatabaseScheduler',
    
    # Redis connection resilience settings
    broker_connection_retry_on_startup=True,
    broker_connection_retry=True,
    broker_connection_max_retries=10,
    result_backend_transport_options={
        'master_name': 'mymaster',
        'socket_keepalive': True,
        'socket_keepalive_options': {
            1: 1,  # TCP_KEEPIDLE
            2: 1,  # TCP_KEEPINTVL
            3: 3,  # TCP_KEEPCNT
        },
        'retry_on_timeout': True,
        'health_check_interval': 30,
    },
    redis_socket_keepalive=True,
    redis_socket_timeout=5.0,
    redis_retry_on_timeout=True,
)

# Beat schedule for periodic tasks
# NOTE: This is now primarily for fallback. 
# The DatabaseScheduler will load intervals from the database.
# Admins can change intervals via the admin panel without restarting.
celery_app.conf.beat_schedule = {
    # BOT-BASED WARMUP (user-to-bot emails with automated replies)
    # Default: 30 minutes (configurable via admin panel)
    'execute-bot-campaigns': {
        'task': 'app.workers.tasks.execute_bot_campaigns',
        'schedule': timedelta(minutes=30),  # Can be changed in admin
    },
    
    # Check bot inboxes via polling (fallback when webhooks not setup)
    # Default: 30 minutes (configurable via admin panel)
    'monitor-bot-inboxes-polling': {
        'task': 'app.workers.tasks.monitor_bot_inboxes',
        'schedule': timedelta(minutes=30),  # Can be changed in admin
    },
    
    # Refresh Gmail watch subscriptions (they expire after 7 days)
    # Default: Daily at 3 AM (configurable via admin panel)
    'refresh-gmail-watches': {
        'task': 'app.workers.tasks.refresh_gmail_watches',
        'schedule': crontab(hour=3, minute=0),  # Can be changed in admin
    },
    
    # MONITORING & STATS
    # Monitor user inboxes
    # Default: 15 minutes (configurable via admin panel)
    'monitor-inboxes': {
        'task': 'app.workers.tasks.monitor_inboxes',
        'schedule': timedelta(minutes=15),  # Can be changed in admin
    },
    
    # Aggregate reputation stats daily
    # Default: Daily at 00:05 UTC (configurable via admin panel)
    'aggregate-reputation-daily': {
        'task': 'app.workers.tasks.aggregate_daily_stats',
        'schedule': crontab(hour=0, minute=5),  # Can be changed in admin
    },
    
    # Check safety limits
    # Default: 30 minutes (configurable via admin panel)
    'check-safety-limits': {
        'task': 'app.workers.tasks.check_safety_limits',
        'schedule': timedelta(minutes=30),  # Can be changed in admin
    },
    
    # OAUTH TOKEN MANAGEMENT (Cross-Account Protection)
    # Check for expired/expiring OAuth tokens and attempt refresh
    # Default: Every hour (configurable via admin panel)
    'check-oauth-tokens': {
        'task': 'app.workers.tasks.check_oauth_tokens',
        'schedule': timedelta(hours=1),  # Can be changed in admin
    },
    
    # Clean up old security event logs
    # Default: Weekly on Sunday at 2 AM (configurable via admin panel)
    'cleanup-security-events': {
        'task': 'app.workers.tasks.cleanup_security_events',
        'schedule': crontab(hour=2, minute=0, day_of_week=0),  # Sunday 2 AM
    },
}

if __name__ == "__main__":
    celery_app.start()
