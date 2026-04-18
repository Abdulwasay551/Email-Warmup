#!/bin/bash
# Production startup script

# Number of worker processes (recommended: 2-4 x CPU cores)
WORKERS=4

# Bind address
HOST=0.0.0.0
PORT=8000

echo "Starting Email Warm-Up Pro in production mode..."
echo "Workers: $WORKERS"
echo "Binding to: $HOST:$PORT"

# Start with Gunicorn + Uvicorn workers
gunicorn app.main:app \
    --workers $WORKERS \
    --worker-class uvicorn.workers.UvicornWorker \
    --bind $HOST:$PORT \
    --timeout 120 \
    --keep-alive 5 \
    --access-logfile - \
    --error-logfile - \
    --log-level info
