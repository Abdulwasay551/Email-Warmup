#!/bin/bash

# System Status Check
echo "=========================================="
echo "📊 Email Warmup System Status"
echo "=========================================="
echo ""

cd /home/bnb/Documents/email-warpup
source venv/bin/activate 2>/dev/null

# Check if services are running
echo "🔍 Checking Services..."
echo ""

# API Server
if curl -s http://localhost:8000/ > /dev/null 2>&1; then
    echo "✅ API Server: RUNNING (http://localhost:8000)"
else
    echo "❌ API Server: NOT RUNNING"
fi

# Celery Worker
if pgrep -f "celery.*worker" > /dev/null; then
    WORKER_COUNT=$(pgrep -f "celery.*worker" | wc -l)
    echo "✅ Celery Worker: RUNNING ($WORKER_COUNT processes)"
else
    echo "❌ Celery Worker: NOT RUNNING"
fi

# Celery Beat
if pgrep -f "celery.*beat" > /dev/null; then
    echo "✅ Celery Beat: RUNNING"
else
    echo "❌ Celery Beat: NOT RUNNING"
fi

echo ""
echo "=========================================="
echo "📋 Database Status"
echo "=========================================="
echo ""

python3 -c "
from app.core.database import SessionLocal
from app.db.models import User, EmailInbox, BotEmail, WarmupCampaign
from sqlalchemy import text

db = SessionLocal()

try:
    # Count records
    users = db.query(User).count()
    inboxes = db.query(EmailInbox).count()
    bots = db.query(BotEmail).count()
    campaigns = db.query(WarmupCampaign).count()
    
    print(f'Users: {users}')
    print(f'Email Inboxes: {inboxes}')
    print(f'Bot Emails: {bots}')
    print(f'Campaigns: {campaigns}')
    print('')
    
    # Check bot status
    active_bots = db.query(BotEmail).filter_by(status='active').count()
    bots_with_watch = db.query(BotEmail).filter(BotEmail.watch_history_id.isnot(None)).count()
    
    print(f'Active Bots: {active_bots}')
    print(f'Bots with Webhooks: {bots_with_watch}')
    
except Exception as e:
    print(f'Error: {e}')
finally:
    db.close()
" 2>/dev/null

echo ""
echo "=========================================="
echo "📝 Recent Logs"
echo "=========================================="
echo ""

echo "API Server (last 5 lines):"
tail -5 api.log 2>/dev/null || echo "No logs yet"
echo ""

echo "Celery Worker (last 5 lines):"
tail -5 celery_worker.log 2>/dev/null || echo "No logs yet"
echo ""

echo "Celery Beat (last 5 lines):"
tail -5 celery_beat.log 2>/dev/null || echo "No logs yet"

echo ""
echo "=========================================="
echo "🔗 Access URLs"
echo "=========================================="
echo ""
echo "🌐 Application: http://localhost:8000"
echo "📚 API Docs: http://localhost:8000/docs"
echo "👨‍💼 Admin Panel: http://localhost:8000/admin"
echo "📧 Inbox Management: http://localhost:8000/inbox/list"
echo "📊 Campaign Dashboard: http://localhost:8000/campaigns/list"
echo ""

echo "=========================================="
echo "💡 Useful Commands"
echo "=========================================="
echo ""
echo "View logs:"
echo "  tail -f api.log"
echo "  tail -f celery_worker.log"
echo "  tail -f celery_beat.log"
echo ""
echo "Check Celery:"
echo "  celery -A app.workers.celery_app inspect active"
echo "  celery -A app.workers.celery_app inspect scheduled"
echo ""
echo "Stop services:"
echo "  pkill -f 'uvicorn app.main:app'"
echo "  pkill -f 'celery.*app.workers.celery_app'"
echo ""
echo "Restart services:"
echo "  ./start.sh  # Choose option 4"
echo ""
