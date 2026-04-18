# 📧 Email Warm-Up Pro

> A production-ready email reputation management system with AI-powered conversations, bot-based warmup, and intelligent reputation tracking.

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.104+-green.svg)](https://fastapi.tiangolo.com/)
[![Celery](https://img.shields.io/badge/Celery-5.3+-orange.svg)](https://docs.celeryq.dev/)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

---

## 🌟 What is Email Warm-Up Pro?

Email Warm-Up Pro is a sophisticated email reputation management platform that **gradually warms up your email domains** by sending natural, AI-generated conversations between connected Gmail accounts and bot email addresses. This increases your sender reputation, improves inbox placement, and reduces spam complaints.

### 🎯 Key Features

- **🤖 Bot-Based Warmup System** - Send emails to admin-managed bot accounts for safe, controlled warmup
- **🔐 Gmail OAuth Integration** - Secure inbox connections via Google OAuth 2.0
- **🎨 AI-Powered Content** - Natural, human-like emails and replies using OpenAI GPT
- **📊 Real-Time Analytics** - Comprehensive reputation tracking and engagement metrics
- **🛡️ Safety Limits** - Auto-pause campaigns on spam/bounce thresholds
- **⚡ Dynamic Scheduling** - Configurable task intervals without service restarts
- **🎛️ Admin Dashboard** - Complete control over bots, users, and system settings
- **📈 Gradual Volume Escalation** - Intelligent ramping from 5 to 100+ emails per day
- **🔔 Real-Time Webhooks** - Instant email detection via Gmail Pub/Sub notifications
- **🎨 Beautiful UI** - Modern glassmorphism design with animated dashboards

---

## 📋 Table of Contents

- [How It Works](#-how-it-works)
- [Quick Start](#-quick-start-5-minutes)
- [Installation](#-installation)
- [Configuration](#️-configuration)
- [Database Migrations](#️-database-migrations)
- [Running the Application](#-running-the-application)
- [Admin Setup](#-admin-setup)
- [User Guide](#-user-guide)
- [Architecture](#️-architecture)
- [API Documentation](#-api-documentation)
- [Task Scheduling](#-task-scheduling)
- [Monitoring](#-monitoring)
- [Production Deployment](#-production-deployment)
- [Troubleshooting](#-troubleshooting)
- [Development](#-development)

---

## 🔄 How It Works

### The Warmup Process

```mermaid
flowchart TD
    A[👤 USER SETUP] --> B[User connects Gmail via OAuth]
    A --> C[Admin creates bot emails]
    A --> D[User creates warmup campaign]
    A --> E[System assigns 3 bots per inbox]
    
    E --> F[📧 EMAIL SENDING<br/>Every 30 minutes]
    F --> G[execute_bot_campaigns task]
    G --> H[Select user→bot pairs<br/>interval-based]
    H --> I[Generate AI content or templates]
    I --> J[Send via Gmail API]
    J --> K[Record in database]
    
    K --> L[🤖 BOT MONITORING<br/>Real-time + 30min polling]
    L --> M[Gmail Webhook:<br/>Instant notification]
    L --> N[monitor_bot_inboxes<br/>fallback]
    M --> O[Check inbox & spam folders]
    N --> O
    O --> P[Mark emails as read]
    P --> Q[Move spam→inbox if needed]
    
    Q --> R[💬 BOT REPLIES<br/>Automatic]
    R --> S[Queue reply with 1-5min delay]
    S --> T[Generate AI reply or template]
    T --> U[Send as thread continuation]
    U --> V[Log to bot_activities]
    
    V --> W[📊 REPUTATION TRACKING]
    W --> X[Monitor opens/replies/spam]
    W --> Y[Calculate daily scores]
    W --> Z[Auto-pause on complaints]
    W --> AA[Gradual volume increases<br/>every 7 days]
    
    AA -.-> F
    
    style A fill:#667eea,stroke:#764ba2,stroke-width:2px,color:#fff
    style F fill:#f093fb,stroke:#f5576c,stroke-width:2px,color:#fff
    style L fill:#4facfe,stroke:#00f2fe,stroke-width:2px,color:#fff
    style R fill:#43e97b,stroke:#38f9d7,stroke-width:2px,color:#fff
    style W fill:#fa709a,stroke:#fee140,stroke-width:2px,color:#fff
```

### Why It Works

✅ **Natural Conversations** - AI generates casual, human-like emails  
✅ **No Marketing Content** - Pure conversational exchanges  
✅ **Random Timing** - Mimics real human behavior  
✅ **Gradual Escalation** - Start slow, increase safely  
✅ **Engagement Signals** - Opens, replies, spam removal boost reputation  
✅ **Safety First** - Auto-pause prevents reputation damage

---

## 🚀 Quick Start (5 Minutes)

### Prerequisites

Ensure you have these installed:

- **Python 3.11+** - [Download](https://www.python.org/downloads/)
- **Redis** - For Celery task queue ([Install Guide](#install-redis))
- **PostgreSQL** - Database (optional, SQLite works for development)
- **Google Cloud Project** - For Gmail OAuth ([Setup Guide](#google-oauth-setup))
- **OpenAI API Key** - For AI-generated content ([Get Key](https://platform.openai.com/api-keys))

### One-Command Setup

```bash
# Clone and navigate to project
cd email-warpup

# Run setup script
./setup_complete_system.sh

# Follow the prompts to configure your environment
```

### Manual Setup (Detailed)

See [Installation](#-installation) section below.

---

## 📦 Installation

### 1. Create Virtual Environment

```bash
# Create virtual environment
python3 -m venv venv

# Activate it
source venv/bin/activate  # On Linux/Mac
# or
venv\Scripts\activate     # On Windows
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Install Redis

<details>
<summary><b>macOS</b></summary>

```bash
brew install redis
brew services start redis

# Verify
redis-cli ping  # Should return "PONG"
```
</details>

<details>
<summary><b>Ubuntu/Debian</b></summary>

```bash
sudo apt update
sudo apt install redis-server
sudo systemctl start redis
sudo systemctl enable redis

# Verify
redis-cli ping  # Should return "PONG"
```
</details>

<details>
<summary><b>Windows (WSL)</b></summary>

```bash
sudo apt update
sudo apt install redis-server
sudo service redis-server start

# Verify
redis-cli ping  # Should return "PONG"
```
</details>

<details>
<summary><b>Docker</b></summary>

```bash
docker run -d -p 6379:6379 --name redis redis:alpine
```
</details>

### 4. Install PostgreSQL (Optional)

<details>
<summary>SQLite (Default - No Installation Needed)</summary>

The app uses SQLite by default. Just set in `.env`:
```env
DATABASE_URL=sqlite:///./email_warmup.db
```
</details>

<details>
<summary>PostgreSQL (Recommended for Production)</summary>

```bash
# macOS
brew install postgresql
brew services start postgresql

# Ubuntu/Debian
sudo apt install postgresql postgresql-contrib
sudo systemctl start postgresql

# Create database
createdb email_warmup

# Update .env
DATABASE_URL=postgresql://user:password@localhost:5432/email_warmup
```
</details>

---

## ⚙️ Configuration

### Environment Variables

Copy the example environment file:

```bash
cp .env.example .env
```

Edit `.env` with your configuration:

```bash
# ==================== APPLICATION ====================
DEBUG=True
ENVIRONMENT=development
SECRET_KEY=your-super-secret-key-change-me
JWT_SECRET_KEY=your-jwt-secret-key-change-me

# ==================== DATABASE ====================
# Option 1: SQLite (Development)
DATABASE_URL=sqlite:///./email_warmup.db

# Option 2: PostgreSQL (Production)
# DATABASE_URL=postgresql://user:password@localhost:5432/email_warmup

# ==================== REDIS & CELERY ====================
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/1

# Or use Redis Cloud (provided in .env)
# REDIS_URL=redis://default:password@host:port
# CELERY_BROKER_URL=redis://default:password@host:port/0
# CELERY_RESULT_BACKEND=redis://default:password@host:port/1

# ==================== GOOGLE OAUTH ====================
GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your-client-secret
GOOGLE_REDIRECT_URI=http://localhost:8000/inbox/api/oauth/callback

# For production (Vercel, etc.)
# GOOGLE_REDIRECT_URI=https://yourdomain.com/inbox/api/oauth/callback

# ==================== OPENAI ====================
OPENAI_API_KEY=sk-your-openai-api-key-here

# ==================== WARMUP SETTINGS ====================
MIN_DAILY_EMAILS=5
MAX_DAILY_EMAILS=100
WARMUP_INCREMENT_DAYS=7
WARMUP_INCREMENT_AMOUNT=5

# ==================== SAFETY LIMITS ====================
MAX_SPAM_COMPLAINT_RATE=0.01  # 1%
MAX_BOUNCE_RATE=0.05           # 5%
```

### Generate Secure Keys

```bash
# Generate SECRET_KEY
python -c "import secrets; print('SECRET_KEY=' + secrets.token_urlsafe(32))"

# Generate JWT_SECRET_KEY
python -c "import secrets; print('JWT_SECRET_KEY=' + secrets.token_urlsafe(32))"
```

### Google OAuth Setup

1. **Create Google Cloud Project**
   - Go to [Google Cloud Console](https://console.cloud.google.com/)
   - Create new project or select existing

2. **Enable Gmail API**
   - Navigate to "APIs & Services" → "Library"
   - Search for "Gmail API"
   - Click "Enable"

3. **Create OAuth Credentials**
   - Go to "APIs & Services" → "Credentials"
   - Click "Create Credentials" → "OAuth client ID"
   - Application type: "Web application"
   - Add authorized redirect URIs:
     ```
     http://localhost:8000/inbox/api/oauth/callback
     https://yourdomain.com/inbox/api/oauth/callback
     ```

4. **Configure OAuth Consent Screen**
   - Go to "OAuth consent screen"
   - Add scopes:
     - `https://www.googleapis.com/auth/gmail.readonly`
     - `https://www.googleapis.com/auth/gmail.send`
     - `https://www.googleapis.com/auth/gmail.modify`

5. **Copy Credentials to .env**
   - Copy Client ID and Client Secret to `.env`

---

## 🗄️ Database Migrations

### Initialize Database

```bash
# Run all migrations
alembic upgrade head
```

### Create New Migration

```bash
# Auto-generate migration from model changes
alembic revision --autogenerate -m "Description of changes"

# Apply the new migration
alembic upgrade head
```

### Rollback Migration

```bash
# Rollback one migration
alembic downgrade -1

# Rollback to specific revision
alembic downgrade <revision_id>
```

### View Migration History

```bash
# Show migration history
alembic history

# Show current migration
alembic current
```

### Seed Test Data (Optional)

```bash
python seed.py
```

This creates:
- Admin user: `admin@warmup.test` / `admin123`
- Regular user: `user@warmup.test` / `user123`
- Demo user: `demo@warmup.test` / `demo123`

---

## 🏃 Running the Application

### Development Mode

You need **4 terminals** running simultaneously:

#### Terminal 1: API Server

```bash
source venv/bin/activate
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

**Access at:** http://localhost:8000

#### Terminal 2: Celery Worker

```bash
source venv/bin/activate
celery -A app.workers.celery_app worker --loglevel=info
```

#### Terminal 3: Celery Beat (Scheduler)

```bash
source venv/bin/activate
celery -A app.workers.celery_app beat --loglevel=info
```

#### Terminal 4: Flower (Optional - Monitoring)

```bash
source venv/bin/activate
celery -A app.workers.celery_app flower --port=5555
```

**Access at:** http://localhost:5555

### Quick Start Scripts

Use the provided scripts for easier startup:

```bash
# Start everything (API + Celery Worker + Beat)
./start.sh

# Start with Celery
./start_celery.sh

# Production mode with Gunicorn
./start_production.sh

# Check system status
./status.sh
```

### Production Mode

```bash
# Install Gunicorn
pip install gunicorn

# Run with Gunicorn (4 workers)
gunicorn app.main:app \
    --workers 4 \
    --worker-class uvicorn.workers.UvicornWorker \
    --bind 0.0.0.0:8000 \
    --timeout 120 \
    --access-logfile - \
    --error-logfile -
```

See [Production Deployment](#-production-deployment) for detailed setup.

---

## 👨‍💼 Admin Setup

### Create Admin User

**Quick Method (Development):**

```bash
python quick_admin.py
```

Creates admin with:
- Email: `admin@emailwarmup.local`
- Password: `admin123`

**Custom Method:**

```bash
python create_admin.py
```

Interactive prompt for custom credentials.

### Admin Dashboard

Access at: http://localhost:8000/admin

Features:
- **Bot Email Management** - Add/remove bot accounts
- **User Management** - Create users, assign roles
- **Bot Activities** - Monitor all bot actions
- **Task Scheduling** - Configure task intervals
- **System Health** - View overall system status
- **Statistics** - System-wide metrics and charts

### Add Bot Emails

1. Log in as admin
2. Go to "Bot Emails" tab
3. Click "Add Bot Email"
4. Enter bot Gmail credentials
5. Authenticate with Google OAuth
6. Bot will automatically monitor assigned users

**Recommended:** Create 5-10 bot emails for better distribution.

---

## 👥 User Guide

### Step 1: Create Account

1. Navigate to http://localhost:8000
2. Click "Create Account"
3. Fill in your details
4. Login with your credentials

### Step 2: Connect Gmail Inboxes

1. Go to **Dashboard** → **Inboxes**
2. Click **"Connect Inbox"**
3. Click **"Connect Gmail"**
4. Authorize with Google
5. Repeat for 3-5 Gmail accounts

**Important:** Use test Gmail accounts initially!

### Step 3: Create Warmup Campaign

1. Go to **Campaigns** → **"Create Campaign"**
2. Configure:
   - **Name:** e.g., "Domain Warm-Up Q1 2026"
   - **Target Daily Volume:** 20-30 (will increase automatically)
   - **Select Inboxes:** Choose 3+ connected inboxes
   - **Enable AI Replies:** Yes
   - **Reply Rate:** 70%
   - **Use Bot System:** Yes (recommended)

3. Click **"Create Campaign"**

### Step 4: Start Campaign

1. Open your campaign
2. Click **"Start Campaign"**
3. System will automatically:
   - Assign 3 random bots per inbox
   - Start sending emails every 30 minutes
   - Monitor bot inboxes for replies
   - Track reputation metrics

### Step 5: Monitor Progress

**Dashboard Views:**

- **Campaign Stats** - Opens, replies, spam rates
- **Inbox Health** - Per-inbox reputation scores  
- **Bot Activities** - See what bots are doing
- **Email Flow** - Real-time email tracking

**Automatic Actions:**

- ✅ Volume increases every 7 days
- ✅ Auto-pause on spam complaints
- ✅ Bot spam folder monitoring
- ✅ Reputation score calculations

---

## 🏗️ Architecture

### Technology Stack

```
Frontend:
├── Jinja2 Templates
├── TailwindCSS
├── Alpine.js
└── Chart.js

Backend:
├── FastAPI (Python 3.11+)
├── SQLAlchemy (ORM)
├── Alembic (Migrations)
├── Pydantic (Validation)
└── JWT Authentication

Task Queue:
├── Celery
├── Redis (Broker)
└── Celery Beat (Scheduler)

APIs:
├── Gmail API (OAuth 2.0)
├── OpenAI API (GPT-3.5/4)
└── Google Pub/Sub (Webhooks)

Database:
├── PostgreSQL (Production)
└── SQLite (Development)
```

### System Architecture

```mermaid
graph TB
    subgraph Frontend["🌐 Frontend Layer"]
        Browser["Web Browser<br/>(Jinja2 + TailwindCSS + Alpine.js)"]
    end
    
    subgraph API["⚡ FastAPI Application Server"]
        AuthAPI["🔐 Auth API<br/>(JWT, OAuth)"]
        InboxAPI["📨 Inbox API<br/>(Gmail Connect)"]
        CampaignAPI["📊 Campaign API<br/>(CRUD)"]
        AdminAPI["👨‍💼 Admin API<br/>(Bot Management)"]
        WebhookAPI["🔔 Webhook API<br/>(Gmail Pub/Sub)"]
        Dashboard["📈 Dashboard<br/>(Analytics)"]
    end
    
    subgraph Data["💾 Data Layer"]
        Postgres[("PostgreSQL<br/>Database")]
        Redis[("Redis<br/>Cache & Queue")]
    end
    
    subgraph External["🌍 External APIs"]
        Gmail["📧 Gmail API<br/>(OAuth 2.0)"]  
        OpenAI["🤖 OpenAI API<br/>(GPT-3.5/4)"]
        PubSub["🔔 Google Pub/Sub<br/>(Webhooks)"]
    end
    
    subgraph Workers["⚙️ Celery Background Workers"]
        CeleryWorker["Celery Workers<br/>(Task Execution)"]
        CeleryBeat["Celery Beat<br/>(Scheduler)"]
    end
    
    subgraph Tasks["📋 Background Tasks"]
        Task1["execute_bot_campaigns<br/>(Send Emails)"]  
        Task2["monitor_bot_inboxes<br/>(Check Inboxes)"]
        Task3["reply_to_user_email<br/>(Auto Reply)"]
        Task4["aggregate_daily_stats<br/>(Calculate Scores)"]
    end
    
    Browser --> API
    
    AuthAPI --> Postgres
    InboxAPI --> Postgres
    CampaignAPI --> Postgres
    AdminAPI --> Postgres
    WebhookAPI --> Redis
    Dashboard --> Postgres
    
    API --> Gmail
    API --> OpenAI
    PubSub --> WebhookAPI
    
    Redis --> CeleryWorker
    CeleryBeat --> Redis
    
    CeleryWorker --> Task1
    CeleryWorker --> Task2  
    CeleryWorker --> Task3
    CeleryWorker --> Task4
    
    Task1 --> Gmail
    Task1 --> Postgres
    Task2 --> Gmail
    Task2 --> Postgres
    Task3 --> Gmail
    Task3 --> OpenAI
    Task3 --> Postgres
    Task4 --> Postgres
    
    style Browser fill:#667eea,stroke:#764ba2,stroke-width:3px,color:#fff
    style Postgres fill:#336791,stroke:#22577A,stroke-width:2px,color:#fff
    style Redis fill:#DC382D,stroke:#A41E11,stroke-width:2px,color:#fff
    style Gmail fill:#EA4335,stroke:#C5221F,stroke-width:2px,color:#fff
    style OpenAI fill:#10a37f,stroke:#0d8a6a,stroke-width:2px,color:#fff
    style CeleryWorker fill:#37b24d,stroke:#2f9e44,stroke-width:2px,color:#fff
    style CeleryBeat fill:#f59f00,stroke:#f08c00,stroke-width:2px,color:#fff
```

### Database Models

**Key Tables:**

- `users` - User accounts and roles
- `email_inboxes` - Connected Gmail accounts
- `bot_emails` - Admin-managed bot accounts
- `warmup_campaigns` - User campaigns
- `email_messages` - All sent/received emails
- `bot_activities` - Bot action logs
- `reputation_stats` - Daily reputation scores
- `task_configurations` - Dynamic task scheduling
- `user_bot_assignments` - User→Bot mappings

---

## 📚 API Documentation

### Interactive Documentation

- **Swagger UI:** http://localhost:8000/docs
- **ReDoc:** http://localhost:8000/redoc

### Authentication

Most endpoints require JWT token:

```bash
# Login to get token
curl -X POST http://localhost:8000/auth/api/login \
  -H "Content-Type: application/json" \
  -d '{
    "email": "user@example.com",
    "password": "password"
  }'

# Use token in requests
curl -X GET http://localhost:8000/campaigns/api/campaigns \
  -H "Authorization: Bearer YOUR_JWT_TOKEN"
```

### Key Endpoints

#### Auth Endpoints

```
POST   /auth/api/register           - Create account
POST   /auth/api/login              - Login
POST   /auth/api/logout             - Logout
GET    /auth/api/me                 - Get current user
```

#### Inbox Endpoints

```
GET    /inbox/api/inboxes           - List user inboxes
POST   /inbox/api/oauth/authorize   - Start Gmail OAuth
GET    /inbox/api/oauth/callback    - OAuth callback
DELETE /inbox/api/inboxes/{id}      - Disconnect inbox
```

#### Campaign Endpoints

```
GET    /campaigns/api/campaigns              - List campaigns
POST   /campaigns/api/campaigns              - Create campaign
GET    /campaigns/api/campaigns/{id}         - Get campaign
PATCH  /campaigns/api/campaigns/{id}         - Update campaign
DELETE /campaigns/api/campaigns/{id}         - Delete campaign
POST   /campaigns/api/campaigns/{id}/start   - Start campaign
POST   /campaigns/api/campaigns/{id}/pause   - Pause campaign
GET    /campaigns/api/campaigns/{id}/stats   - Get statistics
```

#### Admin Endpoints (Admin Only)

```
GET    /admin/api/bots                       - List bot emails
POST   /admin/api/bots                       - Create bot email
DELETE /admin/api/bots/{id}                  - Delete bot
GET    /admin/api/bots/{id}/activities       - Bot activity log
GET    /admin/api/users                      - List users
POST   /admin/api/users                      - Create user
PATCH  /admin/api/users/{id}/role            - Update user role
GET    /admin/api/tasks                      - List scheduled tasks
PUT    /admin/api/tasks/{id}                 - Update task interval
```

---

## ⏰ Task Scheduling

### Default Schedule

| Task | Interval | Description |
|------|----------|-------------|
| `execute_bot_campaigns` | 30 min | Send warmup emails (user→bot) |
| `monitor_bot_inboxes` | 30 min | Check bot inboxes (polling fallback) |
| `refresh_gmail_watches` | Daily | Renew Gmail webhook subscriptions |
| `monitor_inboxes` | 15 min | Monitor user inbox engagement |
| `aggregate_daily_stats` | Daily | Calculate reputation scores |
| `check_safety_limits` | 30 min | Auto-pause on spam/bounces |

### Dynamic Scheduling

Change intervals **without restarting services**:

```bash
# Get all tasks
curl http://localhost:8000/admin/api/tasks \
  -H "Authorization: Bearer $TOKEN"

# Update interval (e.g., 15 minutes)
curl -X PUT http://localhost:8000/admin/api/tasks/1 \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"interval_minutes": 15}'

# Disable/enable task
curl -X POST http://localhost:8000/admin/api/tasks/1/toggle \
  -H "Authorization: Bearer $TOKEN"
```

Changes take effect within 5 minutes automatically!

### Email Scheduling Fix

**Issue:** System was only sending one email per user per day.

**Fix Applied:** Changed pair selection from daily tracking to interval-based tracking. Now sends emails at each configured interval (e.g., every 30 minutes) while respecting daily limits.

See code in: `app/workers/bot_tasks.py` → `select_user_to_bot_pairs_sync()`

---

## 📊 Monitoring

### Flower Dashboard

**Celery task monitoring UI**

```bash
celery -A app.workers.celery_app flower --port=5555
```

Access at: http://localhost:5555

Features:
- Active tasks
- Task history
- Worker status
- Task routing
- Real-time graphs

### Application Logs

```bash
# API logs (if configured)
tail -f logs/api.log

# Celery worker logs
celery -A app.workers.celery_app worker --loglevel=debug

# Celery beat logs
celery -A app.workers.celery_app beat --loglevel=info
```

### Health Check Endpoint

```bash
curl http://localhost:8000/health

# Response:
{
  "status": "healthy",
  "timestamp": "2026-01-20T12:00:00Z",
  "database": "connected",
  "redis": "connected",
  "celery_workers": 2
}
```

### Database Monitoring

```bash
# PostgreSQL
psql -U your_user -d email_warmup

# Useful queries:
SELECT COUNT(*) FROM email_messages WHERE DATE(sent_at) = CURRENT_DATE;
SELECT status, COUNT(*) FROM warmup_campaigns GROUP BY status;
SELECT email_address, status FROM bot_emails;
```

---

## 🚀 Production Deployment

### Server Requirements

- **CPU:** 2+ cores
- **RAM:** 2GB minimum, 4GB recommended
- **Storage:** 10GB+
- **OS:** Ubuntu 20.04+ / Debian 11+ / CentOS 8+

### Production Checklist

- [ ] Set `DEBUG=False` in `.env`
- [ ] Set `ENVIRONMENT=production`
- [ ] Generate strong `SECRET_KEY` and `JWT_SECRET_KEY`
- [ ] Use PostgreSQL instead of SQLite
- [ ] Configure Redis for production
- [ ] Set up SSL/TLS (HTTPS)
- [ ] Configure proper logging
- [ ] Set up monitoring (Sentry, DataDog, etc.)
- [ ] Configure backups
- [ ] Set up process manager (systemd, supervisor)
- [ ] Configure firewall
- [ ] Set up domain and DNS

### Gunicorn Setup

```bash
# Install Gunicorn
pip install gunicorn

# Run with 4 workers (adjust based on CPU cores)
gunicorn app.main:app \
    --workers 4 \
    --worker-class uvicorn.workers.UvicornWorker \
    --bind 0.0.0.0:8000 \
    --timeout 120 \
    --access-logfile - \
    --error-logfile -

# Formula: workers = (2 x CPU_CORES) + 1
# 2 cores = 5 workers
# 4 cores = 9 workers
```

### Systemd Service

Create `/etc/systemd/system/emailwarmup.service`:

```ini
[Unit]
Description=Email Warm-Up Pro API
After=network.target

[Service]
Type=notify
User=www-data
WorkingDirectory=/var/www/email-warpup
Environment="PATH=/var/www/email-warpup/venv/bin"
ExecStart=/var/www/email-warpup/venv/bin/gunicorn app.main:app \
    --workers 4 \
    --worker-class uvicorn.workers.UvicornWorker \
    --bind 0.0.0.0:8000
Restart=always

[Install]
WantedBy=multi-user.target
```

Create `/etc/systemd/system/emailwarmup-celery.service`:

```ini
[Unit]
Description=Email Warm-Up Celery Worker
After=network.target redis.service

[Service]
Type=forking
User=www-data
WorkingDirectory=/var/www/email-warpup
Environment="PATH=/var/www/email-warpup/venv/bin"
ExecStart=/var/www/email-warpup/venv/bin/celery -A app.workers.celery_app worker --detach
Restart=always

[Install]
WantedBy=multi-user.target
```

Start services:

```bash
sudo systemctl daemon-reload
sudo systemctl enable emailwarmup
sudo systemctl enable emailwarmup-celery
sudo systemctl start emailwarmup
sudo systemctl start emailwarmup-celery
```

### Nginx Configuration

```nginx
server {
    listen 80;
    server_name yourdomain.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Static files (if needed)
    location /static {
        alias /var/www/email-warpup/static;
    }
}
```

### SSL with Let's Encrypt

```bash
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d yourdomain.com
```

### Environment Variables for Production

```bash
DEBUG=False
ENVIRONMENT=production
SECRET_KEY=<strong-random-key>
JWT_SECRET_KEY=<strong-random-key>
DATABASE_URL=postgresql://user:pass@localhost/email_warmup
GOOGLE_REDIRECT_URI=https://yourdomain.com/inbox/api/oauth/callback
```

---

## 🐛 Troubleshooting

### Gmail OAuth Not Working

**Issue:** Can't connect Gmail accounts

**Solutions:**
1. Check redirect URI matches exactly in Google Cloud Console
2. Ensure Gmail API is enabled
3. Verify OAuth consent screen is configured
4. Check scopes are correct
5. Try incognito/private browser window

```bash
# Check .env
GOOGLE_REDIRECT_URI=http://localhost:8000/inbox/api/oauth/callback
# Must match Google Cloud Console exactly (including http/https)
```

### No Emails Sending

**Issue:** Campaign running but no emails sent

**Solutions:**
1. Check campaign status is "RUNNING"
2. Verify inboxes are "ACTIVE" (not disconnected)
3. Check daily quotas not exceeded
4. View Celery worker logs for errors
5. Verify bot emails are active and healthy

```bash
# Check campaign status
curl http://localhost:8000/campaigns/api/campaigns \
  -H "Authorization: Bearer $TOKEN"

# Check Celery logs
celery -A app.workers.celery_app worker --loglevel=debug
```

### Redis Connection Error

**Issue:** Can't connect to Redis

**Solutions:**

```bash
# Check Redis is running
redis-cli ping  # Should return "PONG"

# Start Redis
# macOS:
brew services start redis

# Linux:
sudo systemctl start redis

# Check .env
REDIS_URL=redis://localhost:6379/0
```

### Database Migration Errors

**Issue:** Alembic migration fails

**Solutions:**

```bash
# Check current migration
alembic current

# Stamp to current (if out of sync)
alembic stamp head

# Drop and recreate (CAUTION: loses data)
alembic downgrade base
alembic upgrade head

# Or fresh start
rm -rf alembic/versions/*.py  # DANGER!
alembic revision --autogenerate -m "Initial migration"
alembic upgrade head
```

### Token Decryption Errors

**Issue:** "Cannot decrypt tokens" errors

**Cause:** Tokens encrypted with different SECRET_KEY

**Solution:**
1. All inboxes/bots need re-authentication
2. Or keep same SECRET_KEY from original encryption

```bash
# Mark all as disconnected (will require re-auth)
python fix_auth_tokens.py
```

### Import Errors

**Issue:** `ModuleNotFoundError`

**Solution:**

```bash
# Ensure virtual environment is activated
source venv/bin/activate

# Reinstall dependencies
pip install -r requirements.txt
```

### Celery Workers Not Processing

**Issue:** Tasks queued but not executing

**Solutions:**

```bash
# Check workers are running
celery -A app.workers.celery_app inspect active

# Check worker status
celery -A app.workers.celery_app inspect stats

# Restart workers
pkill -f "celery worker"
celery -A app.workers.celery_app worker --loglevel=info
```

---

## 👨‍💻 Development

### Project Structure

```
email-warpup/
├── app/
│   ├── main.py                 # FastAPI application
│   ├── admin/                  # Admin panel routes & logic
│   ├── auth/                   # Authentication & JWT
│   ├── campaigns/              # Campaign management
│   ├── core/                   # Config, database, security
│   ├── db/                     # Database models
│   ├── emails/                 # Email sending logic
│   ├── inbox/                  # Inbox management & OAuth
│   ├── monitoring/             # Health checks
│   ├── ai/                     # AI content generation
│   └── workers/                # Celery tasks
│       ├── celery_app.py       # Celery configuration
│       ├── tasks.py            # User-to-user warmup tasks
│       ├── bot_tasks.py        # Bot warmup tasks
│       └── dynamic_scheduler.py # Dynamic task scheduling
├── alembic/                    # Database migrations
├── static/                     # Static files (CSS, JS)
├── templates/                  # Jinja2 templates
├── .env                        # Environment configuration
├── requirements.txt            # Python dependencies
├── alembic.ini                 # Alembic configuration
└── README.md                   # This file
```

### Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=app --cov-report=html

# Run specific test file
pytest tests/test_campaigns.py

# Run with verbose output
pytest -v
```

### Code Style

```bash
# Format code with Black
black app/

# Sort imports
isort app/

# Lint with flake8
flake8 app/

# Type checking with mypy
mypy app/
```

### Adding New Features

1. **Create feature branch**
   ```bash
   git checkout -b feature/my-new-feature
   ```

2. **Make changes and test**
   ```bash
   pytest
   ```

3. **Update migrations if needed**
   ```bash
   alembic revision --autogenerate -m "Add new feature"
   alembic upgrade head
   ```

4. **Commit and push**
   ```bash
   git add .
   git commit -m "Add new feature"
   git push origin feature/my-new-feature
   ```

### Environment Setup for Contributors

```bash
# Clone repository
git clone https://github.com/yourusername/email-warpup.git
cd email-warpup

# Create virtual environment
python -m venv venv
source venv/bin/activate

# Install development dependencies
pip install -r requirements.txt
pip install pytest pytest-cov black isort flake8 mypy

# Set up pre-commit hooks
pre-commit install

# Run migrations
alembic upgrade head

# Start development server
uvicorn app.main:app --reload
```

---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## 🙏 Acknowledgments

- **FastAPI** - Modern, fast web framework
- **Celery** - Distributed task queue
- **Gmail API** - Email sending and monitoring
- **OpenAI** - AI-powered content generation
- **TailwindCSS** - Beautiful UI styling

---

## 📞 Support

For issues, questions, or contributions:

- **Issues:** [GitHub Issues](https://github.com/yourusername/email-warpup/issues)
- **Discussions:** [GitHub Discussions](https://github.com/yourusername/email-warpup/discussions)
- **Email:** support@emailwarmup.local

---

## 🎯 Roadmap

- [ ] Microsoft 365 / Outlook integration
- [ ] Custom SMTP support
- [ ] Multi-language support
- [ ] Advanced analytics dashboard
- [ ] API rate limiting
- [ ] Webhook integrations (Slack, Discord)
- [ ] Mobile app
- [ ] White-label solution

---

<div align="center">

**⭐ Star us on GitHub — it motivates us a lot!**

Made with passion and love

</div>
