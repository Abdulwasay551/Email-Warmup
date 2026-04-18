#!/usr/bin/env python3
"""
Management CLI for Email Warm-Up Pro
Django-style management commands for FastAPI
"""
import sys
import os
import subprocess
from pathlib import Path
from getpass import getpass

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

app = typer.Typer(
    name="Email Warm-Up Pro Manager",
    help="Management commands for Email Warm-Up Pro",
    add_completion=False
)
console = Console()


@app.command()
def init(
    force: bool = typer.Option(False, "--force", help="Force reinitialize even if alembic exists")
):
    """Initialize Alembic migrations (first time setup)"""
    alembic_dir = Path("alembic")
    
    if alembic_dir.exists() and not force:
        console.print("[yellow]⚠️  Alembic already initialized. Use --force to reinitialize[/yellow]")
        return
    
    console.print("[cyan]🔧 Initializing Alembic...[/cyan]")
    
    if force and alembic_dir.exists():
        import shutil
        shutil.rmtree(alembic_dir)
        console.print("[yellow]   Removed existing alembic directory[/yellow]")
    
    result = subprocess.run(["alembic", "init", "alembic"])
    
    if result.returncode == 0:
        console.print("[green]✅ Alembic initialized successfully![/green]")
        console.print("[cyan]📝 Next steps:[/cyan]")
        console.print("   1. Configure alembic.ini with your database URL")
        console.print("   2. Update alembic/env.py to import your models")
        console.print("   3. Run: python manage.py makemigrations")
    else:
        console.print("[red]❌ Failed to initialize Alembic[/red]")
        sys.exit(1)


@app.command()
def makemigrations(
    message: str = typer.Argument("Auto-generated migration", help="Migration message")
):
    """Create new migration from model changes (like Django makemigrations)"""
    console.print(f"[cyan]🔍 Detecting model changes...[/cyan]")
    
    result = subprocess.run(
        ["alembic", "revision", "--autogenerate", "-m", message],
        capture_output=True,
        text=True
    )
    
    if result.returncode == 0:
        console.print("[green]✅ Migration created successfully![/green]")
        console.print(result.stdout)
        console.print("[cyan]📝 To apply migration, run:[/cyan] python manage.py migrate")
    else:
        console.print("[red]❌ Failed to create migration[/red]")
        console.print(result.stderr)
        sys.exit(1)


@app.command()
def migrate(
    revision: str = typer.Argument("head", help="Target revision (default: head)")
):
    """Apply migrations to database (like Django migrate)"""
    console.print(f"[cyan]🚀 Applying migrations to: {revision}[/cyan]")
    
    result = subprocess.run(
        ["alembic", "upgrade", revision],
        capture_output=True,
        text=True
    )
    
    if result.returncode == 0:
        console.print("[green]✅ Migrations applied successfully![/green]")
        console.print(result.stdout)
    else:
        console.print("[red]❌ Failed to apply migrations[/red]")
        console.print(result.stderr)
        sys.exit(1)


@app.command()
def downgrade(
    revision: str = typer.Argument("-1", help="Target revision (default: -1 for one step back)")
):
    """Rollback migrations"""
    console.print(f"[yellow]⚠️  Rolling back to: {revision}[/yellow]")
    
    confirm = typer.confirm("Are you sure you want to rollback?")
    if not confirm:
        console.print("[yellow]Rollback cancelled[/yellow]")
        return
    
    result = subprocess.run(
        ["alembic", "downgrade", revision],
        capture_output=True,
        text=True
    )
    
    if result.returncode == 0:
        console.print("[green]✅ Rollback completed![/green]")
        console.print(result.stdout)
    else:
        console.print("[red]❌ Rollback failed[/red]")
        console.print(result.stderr)
        sys.exit(1)


@app.command()
def history():
    """Show migration history"""
    console.print("[cyan]📜 Migration History:[/cyan]\n")
    
    result = subprocess.run(
        ["alembic", "history", "--verbose"],
        capture_output=True,
        text=True
    )
    
    if result.returncode == 0:
        console.print(result.stdout)
    else:
        console.print("[red]❌ Failed to get history[/red]")
        console.print(result.stderr)


@app.command()
def current():
    """Show current migration revision"""
    console.print("[cyan]📍 Current Migration:[/cyan]\n")
    
    result = subprocess.run(
        ["alembic", "current", "--verbose"],
        capture_output=True,
        text=True
    )
    
    if result.returncode == 0:
        console.print(result.stdout)
    else:
        console.print("[red]❌ Failed to get current revision[/red]")
        console.print(result.stderr)


@app.command()
def reset_db(
    skip_confirm: bool = typer.Option(False, "--yes", help="Skip confirmation")
):
    """Drop all tables and recreate database"""
    if not skip_confirm:
        console.print("[red]⚠️  WARNING: This will DROP ALL DATA![/red]")
        confirm = typer.confirm("Are you sure you want to reset the database?")
        if not confirm:
            console.print("[yellow]Reset cancelled[/yellow]")
            return
    
    console.print("[yellow]🗑️  Dropping all tables...[/yellow]")
    
    # Downgrade to base (removes all tables)
    result = subprocess.run(["alembic", "downgrade", "base"])
    
    if result.returncode == 0:
        console.print("[green]✅ Database reset complete![/green]")
        console.print("[cyan]📝 Run 'python manage.py migrate' to recreate tables[/cyan]")
    else:
        console.print("[red]❌ Failed to reset database[/red]")
        sys.exit(1)


@app.command()
def seed(
    clear: bool = typer.Option(False, "--clear", help="Clear existing data first")
):
    """Seed database with test data"""
    console.print("[cyan]🌱 Seeding database...[/cyan]")
    
    # Run seed.py
    result = subprocess.run([sys.executable, "seed.py"])
    
    if result.returncode == 0:
        console.print("[green]✅ Database seeded successfully![/green]")
    else:
        console.print("[red]❌ Failed to seed database[/red]")
        sys.exit(1)


@app.command()
def createsuperuser():
    """Create admin user interactively"""
    console.print(Panel.fit("🔐 Create Admin User", style="cyan"))
    
    from app.core.database import SessionLocal
    from app.db.models import User, UserRole
    from app.core.security import hash_password
    
    db = SessionLocal()
    
    try:
        # Check if admin exists
        from sqlalchemy import select
        admin = db.execute(select(User).where(User.role == UserRole.ADMIN)).first()
        
        if admin:
            console.print("[yellow]⚠️  Admin user already exists[/yellow]")
            if not typer.confirm("Create another admin user?"):
                return
        
        # Get user input
        email = typer.prompt("Email")
        full_name = typer.prompt("Full Name", default="Admin User")
        password = typer.prompt("Password (min 8 chars)", hide_input=True)
        confirm_password = typer.prompt("Confirm Password", hide_input=True)
        
        if password != confirm_password:
            console.print("[red]❌ Passwords don't match![/red]")
            sys.exit(1)
        
        if len(password) < 8:
            console.print("[red]❌ Password must be at least 8 characters![/red]")
            sys.exit(1)
        
        # Create admin
        admin = User(
            email=email,
            password_hash=hash_password(password),
            full_name=full_name,
            role=UserRole.ADMIN,
            is_active=True
        )
        
        db.add(admin)
        db.commit()
        
        console.print(f"[green]✅ Admin user created: {email}[/green]")
        
    except Exception as e:
        console.print(f"[red]❌ Error creating admin: {e}[/red]")
        db.rollback()
        sys.exit(1)
    finally:
        db.close()


@app.command()
def runserver(
    host: str = typer.Option("0.0.0.0", help="Host to bind to"),
    port: int = typer.Option(8000, help="Port to bind to"),
    reload: bool = typer.Option(True, help="Enable auto-reload"),
    workers: int = typer.Option(1, help="Number of worker processes")
):
    """Start development server"""
    console.print(Panel.fit(
        f"🚀 Starting Email Warm-Up Pro\n"
        f"Host: {host}:{port}\n"
        f"Reload: {reload}\n"
        f"Workers: {workers}",
        style="cyan"
    ))
    
    cmd = [
        "uvicorn",
        "app.main:app",
        "--host", host,
        "--port", str(port),
    ]
    
    if reload:
        cmd.append("--reload")
    
    if workers > 1:
        cmd.extend(["--workers", str(workers)])
    
    try:
        subprocess.run(cmd)
    except KeyboardInterrupt:
        console.print("\n[yellow]👋 Server stopped[/yellow]")


@app.command()
def celery_worker(
    loglevel: str = typer.Option("info", help="Log level"),
    pool: str = typer.Option("solo", help="Pool implementation")
):
    """Start Celery worker"""
    console.print("[cyan]🔄 Starting Celery worker...[/cyan]")
    
    cmd = [
        "celery",
        "-A", "app.workers.celery_app",
        "worker",
        "--loglevel", loglevel,
        "--pool", pool
    ]
    
    try:
        subprocess.run(cmd)
    except KeyboardInterrupt:
        console.print("\n[yellow]👋 Celery worker stopped[/yellow]")


@app.command()
def celery_beat(
    loglevel: str = typer.Option("info", help="Log level")
):
    """Start Celery beat scheduler"""
    console.print("[cyan]⏰ Starting Celery beat...[/cyan]")
    
    cmd = [
        "celery",
        "-A", "app.workers.celery_app",
        "beat",
        "--loglevel", loglevel
    ]
    
    try:
        subprocess.run(cmd)
    except KeyboardInterrupt:
        console.print("\n[yellow]👋 Celery beat stopped[/yellow]")


@app.command()
def flower(
    port: int = typer.Option(5555, help="Port for Flower UI")
):
    """Start Flower (Celery monitoring UI)"""
    console.print(f"[cyan]🌸 Starting Flower on port {port}...[/cyan]")
    
    cmd = [
        "celery",
        "-A", "app.workers.celery_app",
        "flower",
        "--port", str(port)
    ]
    
    try:
        subprocess.run(cmd)
    except KeyboardInterrupt:
        console.print("\n[yellow]👋 Flower stopped[/yellow]")


@app.command()
def check():
    """Check project setup and configuration"""
    from app.core.config import get_settings
    
    console.print(Panel.fit("🔍 System Check", style="cyan"))
    
    settings = get_settings()
    
    # Create status table
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Component", style="cyan")
    table.add_column("Status", style="green")
    table.add_column("Details")
    
    # Check database
    try:
        from app.core.database import SessionLocal
        db = SessionLocal()
        db.execute("SELECT 1")
        db.close()
        table.add_row("Database", "✅ OK", settings.DATABASE_URL.split('@')[-1] if '@' in settings.DATABASE_URL else settings.DATABASE_URL)
    except Exception as e:
        table.add_row("Database", "❌ FAIL", str(e)[:50])
    
    # Check Redis
    try:
        import redis
        r = redis.from_url(settings.REDIS_URL)
        r.ping()
        table.add_row("Redis", "✅ OK", settings.REDIS_URL)
    except Exception as e:
        table.add_row("Redis", "❌ FAIL", str(e)[:50])
    
    # Check Alembic
    alembic_dir = Path("alembic")
    if alembic_dir.exists():
        versions = list(Path("alembic/versions").glob("*.py"))
        table.add_row("Alembic", "✅ OK", f"{len(versions)} migrations")
    else:
        table.add_row("Alembic", "⚠️ NOT INIT", "Run: python manage.py init")
    
    # Check environment
    checks = [
        ("Google OAuth", settings.GOOGLE_CLIENT_ID != "your-google-client-id.apps.googleusercontent.com"),
        ("OpenAI API", settings.OPENAI_API_KEY != "sk-your-openai-api-key"),
        ("Secret Key", settings.SECRET_KEY != "dev-secret-key-change-in-production-use-long-random-string")
    ]
    
    for name, is_configured in checks:
        status = "✅ OK" if is_configured else "⚠️ NOT SET"
        table.add_row(name, status, "Configured" if is_configured else "Using default")
    
    console.print(table)
    console.print()


@app.command()
def shell():
    """Open interactive Python shell with app context"""
    console.print("[cyan]🐍 Starting interactive shell...[/cyan]")
    console.print("[dim]Tip: 'db', 'models', 'settings' are pre-loaded[/dim]\n")
    
    # Import common objects
    from app.core.database import SessionLocal
    from app.db import models
    from app.core.config import get_settings
    
    db = SessionLocal()
    settings = get_settings()
    
    # Start IPython if available, otherwise standard Python
    try:
        from IPython import embed  # type: ignore
        embed(colors='neutral')
    except ImportError:
        import code
        code.interact(local={
            'db': db,
            'models': models,
            'settings': settings
        })
    
    db.close()


@app.command()
def dbshell():
    """Open database shell (psql for PostgreSQL, sqlite3 for SQLite)"""
    from app.core.config import get_settings
    settings = get_settings()
    
    console.print("[cyan]💾 Opening database shell...[/cyan]")
    
    if "postgresql" in settings.DATABASE_URL:
        # Extract connection details
        import re
        match = re.match(r'postgresql://([^:]+):([^@]+)@([^/]+)/(.+)', settings.DATABASE_URL)
        if match:
            user, password, host, dbname = match.groups()
            os.environ['PGPASSWORD'] = password
            subprocess.run(["psql", "-U", user, "-h", host.split(':')[0], "-d", dbname])
    elif "sqlite" in settings.DATABASE_URL:
        db_path = settings.DATABASE_URL.replace("sqlite:///", "")
        subprocess.run(["sqlite3", db_path])
    else:
        console.print("[red]❌ Unsupported database type[/red]")


if __name__ == "__main__":
    app()
