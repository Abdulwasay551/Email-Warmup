#!/bin/bash

# Complete Email Warmup System Setup Script
# This script will guide you through setting up Google Cloud Pub/Sub and starting all services

echo "=========================================="
echo "Email Warmup System - Complete Setup"
echo "=========================================="
echo ""

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Check if gcloud is installed
if ! command -v gcloud &> /dev/null; then
    echo -e "${RED}❌ gcloud CLI is not installed${NC}"
    echo ""
    echo "Install it with:"
    echo "  curl https://sdk.cloud.google.com | bash"
    echo "  exec -l \$SHELL"
    echo "  gcloud init"
    echo ""
    read -p "Press Enter to continue without Google Cloud setup (will use polling fallback)..."
    SKIP_GCLOUD=true
else
    echo -e "${GREEN}✓ gcloud CLI found${NC}"
    SKIP_GCLOUD=false
fi

echo ""
echo "=========================================="
echo "Step 1: Google Cloud Pub/Sub Setup"
echo "=========================================="
echo ""

if [ "$SKIP_GCLOUD" = false ]; then
    # Read from .env
    PROJECT_ID=$(grep GOOGLE_PROJECT_ID .env | cut -d '=' -f2)
    TOPIC_NAME=$(grep GMAIL_PUBSUB_TOPIC .env | cut -d '=' -f2)
    
    echo "Project ID: $PROJECT_ID"
    echo "Topic Name: $TOPIC_NAME"
    echo ""
    
    read -p "Do you want to set up Google Cloud Pub/Sub now? (y/n): " -n 1 -r
    echo ""
    
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo -e "${BLUE}Setting up Google Cloud...${NC}"
        
        # Set project
        echo "Setting project to: $PROJECT_ID"
        gcloud config set project $PROJECT_ID
        
        # Check if topic exists
        if gcloud pubsub topics describe $TOPIC_NAME &> /dev/null; then
            echo -e "${GREEN}✓ Topic '$TOPIC_NAME' already exists${NC}"
        else
            echo "Creating Pub/Sub topic..."
            gcloud pubsub topics create $TOPIC_NAME
            echo -e "${GREEN}✓ Topic created${NC}"
        fi
        
        # Grant Gmail permissions
        echo "Granting Gmail API permissions..."
        gcloud pubsub topics add-iam-policy-binding $TOPIC_NAME \
            --member=serviceAccount:gmail-api-push@system.gserviceaccount.com \
            --role=roles/pubsub.publisher
        echo -e "${GREEN}✓ Permissions granted${NC}"
        
        echo ""
        echo -e "${YELLOW}⚠️  Important: You need to create a push subscription${NC}"
        echo ""
        echo "For production, run:"
        echo "  gcloud pubsub subscriptions create gmail-webhook \\"
        echo "    --topic=$TOPIC_NAME \\"
        echo "    --push-endpoint=https://yourdomain.com/inbox/api/webhooks/gmail"
        echo ""
        echo "For local development with ngrok:"
        echo "  1. Run: ngrok http 8000"
        echo "  2. Copy the ngrok URL (https://xxxx.ngrok.io)"
        echo "  3. Run:"
        echo "     gcloud pubsub subscriptions create gmail-webhook \\"
        echo "       --topic=$TOPIC_NAME \\"
        echo "       --push-endpoint=https://YOUR-NGROK-URL.ngrok.io/inbox/api/webhooks/gmail"
        echo ""
        read -p "Press Enter to continue..."
    fi
else
    echo -e "${YELLOW}⚠️  Skipping Google Cloud setup - system will use polling fallback${NC}"
    echo ""
fi

echo ""
echo "=========================================="
echo "Step 2: Verify Database Migration"
echo "=========================================="
echo ""

echo "Checking database..."
source venv/bin/activate
python -c "
from app.core.database import SessionLocal
from sqlalchemy import inspect

db = SessionLocal()
inspector = inspect(db.bind)
columns = [col['name'] for col in inspector.get_columns('bot_emails')]

if 'watch_history_id' in columns and 'watch_expiration' in columns:
    print('✓ Webhook fields are present in database')
else:
    print('❌ Webhook fields missing - run: alembic upgrade head')
db.close()
"
echo ""

echo "=========================================="
echo "Step 3: Starting Services"
echo "=========================================="
echo ""

echo -e "${BLUE}Starting services in separate terminals...${NC}"
echo ""
echo "You need to run these commands in separate terminals:"
echo ""
echo -e "${GREEN}Terminal 1 - API Server:${NC}"
echo "  cd $(pwd)"
echo "  source venv/bin/activate"
echo "  uvicorn app.main:app --reload --host 0.0.0.0 --port 8000"
echo ""
echo -e "${GREEN}Terminal 2 - Celery Worker:${NC}"
echo "  cd $(pwd)"
echo "  source venv/bin/activate"
echo "  celery -A app.workers.celery_app worker --loglevel=info"
echo ""
echo -e "${GREEN}Terminal 3 - Celery Beat:${NC}"
echo "  cd $(pwd)"
echo "  source venv/bin/activate"
echo "  celery -A app.workers.celery_app beat --loglevel=info"
echo ""

read -p "Do you want to start the API server now? (y/n): " -n 1 -r
echo ""

if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo -e "${BLUE}Starting API server...${NC}"
    echo ""
    echo "API will be available at: http://localhost:8000"
    echo "API Docs: http://localhost:8000/docs"
    echo ""
    echo "Start Celery worker and beat in other terminals!"
    echo ""
    uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
fi

echo ""
echo "=========================================="
echo "Setup Complete!"
echo "=========================================="
echo ""
echo "Next steps:"
echo "1. Access http://localhost:8000 to view the application"
echo "2. Login/Register an account"
echo "3. Connect user email inboxes via OAuth"
echo "4. Admin: Add bot emails"
echo "5. Admin: Enable webhooks for bots (POST /inbox/api/inboxes/bot/{id}/setup-watch)"
echo "6. Create warmup campaigns"
echo ""
echo "Documentation:"
echo "  - Complete Flow: COMPLETE_EMAIL_FLOW.md"
echo "  - Quick Start: QUICKSTART_WEBHOOKS.md"
echo "  - Architecture: ARCHITECTURE_DIAGRAM.md"
echo ""
