#!/bin/bash
# Start Celery workers for email warmup system

# Activate virtual environment
source venv/bin/activate

# Start Celery worker (processes tasks)
echo "Starting Celery worker..."
celery -A app.workers.celery_app worker --loglevel=info --pool=solo &

# Wait a moment
sleep 2

# Start Celery beat (schedules periodic tasks)
echo "Starting Celery beat scheduler..."
celery -A app.workers.celery_app beat --loglevel=info &

echo ""
echo "✅ Celery workers started!"
echo ""
echo "To check status:"
echo "  ps aux | grep celery"
echo ""
echo "To stop workers:"
echo "  pkill -f 'celery worker'"
echo "  pkill -f 'celery beat'"
echo ""
echo "To manually trigger bot campaigns (for testing):"
echo "  celery -A app.workers.celery_app call app.workers.tasks.execute_bot_campaigns"
