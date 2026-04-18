"""
Database seed script for Email Warm-Up Pro
Run this to populate the database with test data
"""
import asyncio
from datetime import date, datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.db.models import (
    User, UserRole, 
    EmailInbox, InboxStatus, EmailProvider,
    WarmupCampaign, CampaignStatus,
    CampaignInbox, InboxRole
)


async def clear_database(db: AsyncSession):
    """Clear all data from database (optional)"""
    print("⚠️  Clearing existing data...")
    
    from sqlalchemy import text
    
    # Delete in order to respect foreign keys
    await db.execute(text("DELETE FROM reputation_stats"))
    await db.execute(text("DELETE FROM email_messages"))
    await db.execute(text("DELETE FROM campaign_inboxes"))
    await db.execute(text("DELETE FROM warmup_campaigns"))
    await db.execute(text("DELETE FROM email_inboxes"))
    await db.execute(text("DELETE FROM users"))
    
    await db.commit()
    print("✅ Database cleared")


async def seed_users(db: AsyncSession):
    """Create test users"""
    print("\n📝 Creating users...")
    
    users = [
        User(
            email="admin@warmup.test",
            password_hash=hash_password("admin123"),
            full_name="Admin User",
            role=UserRole.ADMIN,
            is_active=True
        ),
        User(
            email="user@warmup.test",
            password_hash=hash_password("user123"),
            full_name="Test User",
            role=UserRole.USER,
            is_active=True
        ),
        User(
            email="demo@warmup.test",
            password_hash=hash_password("demo123"),
            full_name="Demo User",
            role=UserRole.USER,
            is_active=True
        )
    ]
    
    for user in users:
        db.add(user)
    
    await db.commit()
    
    for user in users:
        await db.refresh(user)
        print(f"   ✓ Created user: {user.email} (password: {'admin123' if user.role == UserRole.ADMIN else 'user123' if 'user@' in user.email else 'demo123'})")
    
    return users


async def seed_inboxes(db: AsyncSession, user: User):
    """Create sample inboxes (without real OAuth tokens)"""
    print(f"\n📬 Creating sample inboxes for {user.email}...")
    
    # Note: These are placeholder inboxes
    # In production, users need to connect real Gmail accounts via OAuth
    
    inboxes = [
        EmailInbox(
            user_id=user.id,
            email_address=f"inbox1.{user.email}",
            provider=EmailProvider.GMAIL,
            domain=user.email.split('@')[1],
            status=InboxStatus.PAUSED,  # Paused since no real OAuth
            daily_send_limit=30,
            warmup_stage=1,
            access_token="placeholder_token_connect_real_gmail",
            refresh_token="placeholder_token_connect_real_gmail"
        ),
        EmailInbox(
            user_id=user.id,
            email_address=f"inbox2.{user.email}",
            provider=EmailProvider.GMAIL,
            domain=user.email.split('@')[1],
            status=InboxStatus.PAUSED,
            daily_send_limit=30,
            warmup_stage=1,
            access_token="placeholder_token_connect_real_gmail",
            refresh_token="placeholder_token_connect_real_gmail"
        ),
        EmailInbox(
            user_id=user.id,
            email_address=f"inbox3.{user.email}",
            provider=EmailProvider.GMAIL,
            domain=user.email.split('@')[1],
            status=InboxStatus.PAUSED,
            daily_send_limit=30,
            warmup_stage=1,
            access_token="placeholder_token_connect_real_gmail",
            refresh_token="placeholder_token_connect_real_gmail"
        )
    ]
    
    for inbox in inboxes:
        db.add(inbox)
    
    await db.commit()
    
    for inbox in inboxes:
        await db.refresh(inbox)
        print(f"   ✓ Created inbox: {inbox.email_address} (Status: {inbox.status.value})")
    
    return inboxes


async def seed_campaigns(db: AsyncSession, user: User, inboxes: list):
    """Create sample campaigns"""
    print(f"\n🚀 Creating sample campaigns for {user.email}...")
    
    campaigns = [
        WarmupCampaign(
            user_id=user.id,
            name="My First Warm-Up Campaign",
            description="A sample campaign to get started with email warming",
            start_date=date.today(),
            target_daily_volume=50,
            current_daily_volume=10,
            status=CampaignStatus.DRAFT,
            use_ai_replies=True,
            reply_rate=0.7
        ),
        WarmupCampaign(
            user_id=user.id,
            name="Domain Reputation Builder",
            description="Building reputation for our main domain",
            start_date=date.today() - timedelta(days=7),
            target_daily_volume=100,
            current_daily_volume=35,
            status=CampaignStatus.PAUSED,
            use_ai_replies=True,
            reply_rate=0.75,
            last_run_at=datetime.utcnow() - timedelta(hours=2)
        )
    ]
    
    for campaign in campaigns:
        db.add(campaign)
    
    await db.commit()
    
    for campaign in campaigns:
        await db.refresh(campaign)
        print(f"   ✓ Created campaign: {campaign.name} (Status: {campaign.status.value})")
        
        # Link inboxes to campaigns
        if len(inboxes) >= 2:
            for inbox in inboxes[:2]:  # Use first 2 inboxes
                campaign_inbox = CampaignInbox(
                    campaign_id=campaign.id,
                    inbox_id=inbox.id,
                    role=InboxRole.MIXED,
                    is_active=True
                )
                db.add(campaign_inbox)
            
            await db.commit()
            print(f"      → Linked {len(inboxes[:2])} inboxes to campaign")
    
    return campaigns


async def main():
    """Main seed function"""
    print("=" * 60)
    print("🌱 Email Warm-Up Pro - Database Seeding")
    print("=" * 60)
    
    db = AsyncSessionLocal()
    
    try:
        # Optional: Clear existing data
        clear = input("\n⚠️  Clear existing data? (y/N): ").strip().lower()
        if clear == 'y':
            await clear_database(db)
        
        # Seed data
        users = await seed_users(db)
        
        # Seed inboxes and campaigns for the test user
        test_user = next(u for u in users if u.email == "user@warmup.test")
        inboxes = await seed_inboxes(db, test_user)
        campaigns = await seed_campaigns(db, test_user, inboxes)
        
        print("\n" + "=" * 60)
        print("✅ Database seeding completed successfully!")
        print("=" * 60)
        print("\n📋 Test Accounts Created:")
        print("-" * 60)
        print("Admin Account:")
        print("  Email:    admin@warmup.test")
        print("  Password: admin123")
        print("  Role:     Admin")
        print()
        print("User Account:")
        print("  Email:    user@warmup.test")
        print("  Password: user123")
        print("  Role:     User")
        print("  Inboxes:  3 sample inboxes (need real Gmail OAuth)")
        print("  Campaigns: 2 sample campaigns")
        print()
        print("Demo Account:")
        print("  Email:    demo@warmup.test")
        print("  Password: demo123")
        print("  Role:     User")
        print("-" * 60)
        print("\n🚀 You can now:")
        print("   1. Login at http://localhost:8000/auth/login")
        print("   2. Connect real Gmail accounts via OAuth")
        print("   3. Create and run warm-up campaigns")
        print()
        print("⚠️  Note: Sample inboxes are PAUSED and need real Gmail OAuth tokens")
        print("   Go to 'Connect Inbox' to link real Gmail accounts")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n❌ Error seeding database: {e}")
        await db.rollback()
        raise
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
