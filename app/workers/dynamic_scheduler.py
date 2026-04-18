"""
Dynamic Celery Beat Scheduler

Reads task configurations from database and schedules tasks dynamically.
Allows admins to control task intervals without restarting services.
"""

from celery.schedules import schedule
from celery.beat import Scheduler, ScheduleEntry
from datetime import datetime, timedelta
from app.core.database import SessionLocal
from app.db.models import TaskConfiguration
import logging

logger = logging.getLogger(__name__)


class DatabaseScheduler(Scheduler):
    """Custom Celery Beat scheduler that reads from database"""
    
    def __init__(self, *args, **kwargs):
        self._schedule = {}
        self._last_timestamp = None
        super().__init__(*args, **kwargs)
    
    def setup_schedule(self):
        """Load schedule from database"""
        try:
            db = SessionLocal()
            configs = db.query(TaskConfiguration).filter(
                TaskConfiguration.is_enabled == True
            ).all()
            
            schedule_dict = {}
            for config in configs:
                # Create schedule entry
                schedule_dict[config.task_name] = {
                    'task': f'app.workers.tasks.{config.task_name}',
                    'schedule': timedelta(minutes=config.interval_minutes),
                    'options': {
                        'expires': config.interval_minutes * 60 * 2  # 2x interval
                    }
                }
                logger.info(
                    f"Scheduled task: {config.display_name} "
                    f"(every {config.interval_minutes} minutes)"
                )
            
            db.close()
            self.merge_inplace(schedule_dict)
            
        except Exception as e:
            logger.error(f"Error loading schedule from database: {e}")
            # Fallback to default schedule if database fails
            self.use_default_schedule()
    
    def use_default_schedule(self):
        """Fallback to default static schedule"""
        from celery.schedules import crontab
        
        default_schedule = {
            'execute-bot-campaigns': {
                'task': 'app.workers.tasks.execute_bot_campaigns',
                'schedule': timedelta(minutes=30),  # Default: 30 minutes
            },
            'monitor-bot-inboxes': {
                'task': 'app.workers.tasks.monitor_bot_inboxes',
                'schedule': timedelta(minutes=30),
            },
            'refresh-gmail-watches': {
                'task': 'app.workers.tasks.refresh_gmail_watches',
                'schedule': crontab(hour=3, minute=0),
            },
            'monitor-inboxes': {
                'task': 'app.workers.tasks.monitor_inboxes',
                'schedule': timedelta(minutes=15),
            },
            'aggregate-reputation-daily': {
                'task': 'app.workers.tasks.aggregate_daily_stats',
                'schedule': crontab(hour=0, minute=5),
            },
            'check-safety-limits': {
                'task': 'app.workers.tasks.check_safety_limits',
                'schedule': timedelta(minutes=30),
            },
        }
        
        self.merge_inplace(default_schedule)
        logger.info("Using default (static) schedule")
    
    def tick(self, *args, **kwargs):
        """Check if schedule needs to be reloaded"""
        # Reload schedule every 5 minutes to pick up changes
        if self._last_timestamp is None or \
           (datetime.now() - self._last_timestamp).seconds >= 300:
            logger.info("Reloading schedule from database...")
            self.setup_schedule()
            self._last_timestamp = datetime.now()
        
        return super().tick(*args, **kwargs)


def get_task_intervals():
    """Get current task intervals from database"""
    try:
        db = SessionLocal()
        configs = db.query(TaskConfiguration).all()
        
        intervals = {}
        for config in configs:
            intervals[config.task_name] = {
                'interval_minutes': config.interval_minutes,
                'is_enabled': config.is_enabled,
                'display_name': config.display_name
            }
        
        db.close()
        return intervals
    except Exception as e:
        logger.error(f"Error getting task intervals: {e}")
        return {}


def update_task_interval(task_name: str, interval_minutes: int):
    """Update task interval in database"""
    try:
        db = SessionLocal()
        config = db.query(TaskConfiguration).filter(
            TaskConfiguration.task_name == task_name
        ).first()
        
        if config:
            config.interval_minutes = interval_minutes
            config.updated_at = datetime.utcnow()
            db.commit()
            logger.info(f"Updated {task_name} interval to {interval_minutes} minutes")
            return True
        
        db.close()
        return False
    except Exception as e:
        logger.error(f"Error updating task interval: {e}")
        return False
