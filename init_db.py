#!/usr/bin/env python3
"""
Database initialization script for Email Warm-Up Pro
Creates initial admin user and runs migrations
"""
import sys
import os
from getpass import getpass

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.core.database import SessionLocal
from app.db.models import User, UserRole
from app.core.security import hash_password

def create_admin_user():
    """Create initial admin user"""
    db = SessionLocal()
    
    try:
        # Check if admin exists
        admin = db.query(User).filter(User.role == UserRole.ADMIN).first()
        
        if admin:
            print("✅ Admin user already exists")
            return
        
        print("🔐 Creating admin user...")
        email = input("Admin email: ")
        password = getpass("Admin password (min 8 chars): ")
        confirm_password = getpass("Confirm password: ")
        
        if password != confirm_password:
            print("❌ Passwords don't match!")
            return
        
        if len(password) < 8:
            print("❌ Password must be at least 8 characters!")
            return
        
        # Create admin
        admin = User(
            email=email,
            password_hash=hash_password(password),
            full_name="Admin User",
            role=UserRole.ADMIN,
            is_active=True
        )
        
        db.add(admin)
        db.commit()
        
        print("✅ Admin user created successfully!")
        print(f"   Email: {email}")
        print(f"   Role: {UserRole.ADMIN}")
        
    except Exception as e:
        print(f"❌ Error creating admin user: {e}")
        db.rollback()
    finally:
        db.close()


if __name__ == "__main__":
    print("📧 Email Warm-Up Pro - Database Initialization")
    print("=" * 50)
    print()
    
    create_admin_user()
    
    print()
    print("=" * 50)
    print("✅ Initialization complete!")
