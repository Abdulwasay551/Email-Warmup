#!/bin/bash

# Quick Start Script for Complete Email Warmup System
# Run this in multiple terminals

echo "=========================================="
echo "🚀 Email Warmup System - Quick Start"
echo "=========================================="
echo ""

# Get the script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# Activate virtual environment
echo "Activating virtual environment..."
source venv/bin/activate

echo ""
echo "Which service do you want to start?"
echo ""
echo "1) API Server (FastAPI)"
echo "2) Celery Worker (Email processing)"
echo "3) Celery Beat (Scheduler)"
echo "4) All Services (in background)"
echo "5) Google Cloud Setup"
echo ""
read -p "Enter choice [1-5]: " choice

case $choice in
    1)
        echo ""
        echo "=========================================="
        echo "Starting API Server..."
        echo "=========================================="
        echo ""
        echo "✓ API: http://localhost:8000"
        echo "✓ Docs: http://localhost:8000/docs"
        echo "✓ Admin: http://localhost:8000/admin"
        echo ""
        uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
        ;;
    2)
        echo ""
        echo "=========================================="
        echo "Starting Celery Worker..."
        echo "=========================================="
        echo ""
        celery -A app.workers.celery_app worker --loglevel=info
        ;;
    3)
        echo ""
        echo "=========================================="
        echo "Starting Celery Beat..."
        echo "=========================================="
        echo ""
        celery -A app.workers.celery_app beat --loglevel=info
        ;;
    4)
        echo ""
        echo "=========================================="
        echo "Starting All Services..."
        echo "=========================================="
        echo ""
        
        # Kill any existing processes
        pkill -f "uvicorn app.main:app"
        pkill -f "celery.*app.workers.celery_app"
        
        # Start services in background
        echo "Starting API Server..."
        nohup uvicorn app.main:app --host 0.0.0.0 --port 8000 > api.log 2>&1 &
        API_PID=$!
        
        echo "Starting Celery Worker..."
        nohup celery -A app.workers.celery_app worker --loglevel=info > celery_worker.log 2>&1 &
        WORKER_PID=$!
        
        echo "Starting Celery Beat..."
        nohup celery -A app.workers.celery_app beat --loglevel=info > celery_beat.log 2>&1 &
        BEAT_PID=$!
        
        sleep 3
        
        echo ""
        echo "✓ All services started!"
        echo ""
        echo "Process IDs:"
        echo "  API Server: $API_PID"
        echo "  Celery Worker: $WORKER_PID"
        echo "  Celery Beat: $BEAT_PID"
        echo ""
        echo "Logs:"
        echo "  API: tail -f api.log"
        echo "  Worker: tail -f celery_worker.log"
        echo "  Beat: tail -f celery_beat.log"
        echo ""
        echo "To stop all:"
        echo "  pkill -f 'uvicorn app.main:app'"
        echo "  pkill -f 'celery.*app.workers.celery_app'"
        echo ""
        echo "Access the application:"
        echo "  🌐 http://localhost:8000"
        echo "  📚 http://localhost:8000/docs"
        echo ""
        ;;
    5)
        echo ""
        echo "=========================================="
        echo "Google Cloud Pub/Sub Setup"
        echo "=========================================="
        echo ""
        
        # Read from .env
        PROJECT_ID=$(grep GOOGLE_PROJECT_ID .env | cut -d '=' -f2)
        TOPIC_NAME=$(grep GMAIL_PUBSUB_TOPIC .env | cut -d '=' -f2)
        
        echo "Project ID: $PROJECT_ID"
        echo "Topic Name: $TOPIC_NAME"
        echo ""
        
        if ! command -v gcloud &> /dev/null; then
            echo "❌ gcloud CLI not found!"
            echo ""
            echo "Install with:"
            echo "  curl https://sdk.cloud.google.com | bash"
            echo "  exec -l \$SHELL"
            echo "  gcloud init"
            exit 1
        fi
        
        echo "Step 1: Authenticate"
        gcloud auth login
        
        echo ""
        echo "Step 2: Set project"
        gcloud config set project $PROJECT_ID
        
        echo ""
        echo "Step 3: Enable APIs"
        gcloud services enable pubsub.googleapis.com
        gcloud services enable gmail.googleapis.com
        
        echo ""
        echo "Step 4: Create topic"
        gcloud pubsub topics create $TOPIC_NAME 2>/dev/null || echo "Topic already exists"
        
        echo ""
        echo "Step 5: Grant permissions"
        gcloud pubsub topics add-iam-policy-binding $TOPIC_NAME \
            --member=serviceAccount:gmail-api-push@system.gserviceaccount.com \
            --role=roles/pubsub.publisher
        
        echo ""
        echo "✓ Google Cloud setup complete!"
        echo ""
        echo "=========================================="
        echo "Next: Create Push Subscription"
        echo "=========================================="
        echo ""
        echo "For LOCAL development:"
        echo "  1. Install ngrok: https://ngrok.com/download"
        echo "  2. Run: ngrok http 8000"
        echo "  3. Copy the https URL"
        echo "  4. Run:"
        echo "     gcloud pubsub subscriptions create gmail-webhook \\"
        echo "       --topic=$TOPIC_NAME \\"
        echo "       --push-endpoint=https://YOUR-NGROK-URL.ngrok.io/inbox/api/webhooks/gmail"
        echo ""
        echo "For PRODUCTION:"
        echo "  gcloud pubsub subscriptions create gmail-webhook \\"
        echo "    --topic=$TOPIC_NAME \\"
        echo "    --push-endpoint=https://yourdomain.com/inbox/api/webhooks/gmail"
        echo ""
        ;;
    *)
        echo "Invalid choice"
        exit 1
        ;;
esac
