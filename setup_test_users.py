#!/usr/bin/env python3
"""
Quick setup script - Ensures admin user exists for testing
"""
import asyncio
from sqlalchemy import select
from app.core.database import AsyncSession, async_engine, get_async_session_maker
from app.db.models import User, UserRole
from app.core.security import hash_password

async def ensure_admin_exists():
    """Ensure admin user exists"""
    admin_email = "admin@example.com"
    admin_password = "admin123"
    
    SessionLocal = get_async_session_maker()
    async with SessionLocal() as db:
        # Check if admin exists
        result = await db.execute(
            select(User).where(User.email == admin_email)
        )
        admin = result.scalar_one_or_none()
        
        if admin:
            print(f"✓ Admin user exists: {admin_email}")
            # Update password in case it changed
            admin.password_hash = hash_password(admin_password)
            admin.role = UserRole.ADMIN
            admin.is_active = True
            await db.commit()
            print(f"✓ Admin password updated")
        else:
            # Create admin
            admin = User(
                email=admin_email,
                password_hash=hash_password(admin_password),
                full_name="Admin User",
                role=UserRole.ADMIN,
                is_active=True
            )
            db.add(admin)
            await db.commit()
            print(f"✓ Admin user created: {admin_email}")
        
        print(f"  Email: {admin_email}")
        print(f"  Password: {admin_password}")
        print(f"  Role: {admin.role.value}")
        
        return True

async def ensure_test_user_exists():
    """Ensure test user exists"""
    user_email = "testuser@example.com"
    user_password = "test123"
    
    SessionLocal = get_async_session_maker()
    async with SessionLocal() as db:
        # Check if user exists
        result = await db.execute(
            select(User).where(User.email == user_email)
        )
        user = result.scalar_one_or_none()
        
        if user:
            print(f"✓ Test user exists: {user_email}")
            # Update password in case it changed
            user.password_hash = hash_password(user_password)
            await db.commit()
            print(f"✓ Test user password updated")
        else:
            # Create user
            user = User(
                email=user_email,
                password_hash=hash_password(user_password),
                full_name="Test User",
                role=UserRole.USER,
                is_active=True
            )
            db.add(user)
            await db.commit()
            print(f"✓ Test user created: {user_email}")
        
        print(f"  Email: {user_email}")
        print(f"  Password: {user_password}")
        print(f"  Role: {user.role.value}")
        
        return True

async def main():
    print("=" * 60)
    print("Email Warmup Tool - Quick Setup")
    print("=" * 60)
    print()
    
    try:
        await ensure_admin_exists()
        print()
        await ensure_test_user_exists()
        print()
        print("=" * 60)
        print("✓ Setup complete! You can now run tests.")
        print("=" * 60)
    except Exception as e:
        print(f"✗ Setup failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
