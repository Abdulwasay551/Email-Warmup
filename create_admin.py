"""Create admin user script"""
import asyncio
from app.core.database import SessionLocal
from app.db.models import User, UserRole
from app.core.security import hash_password
from sqlalchemy import select


async def create_admin():
    """Create admin user"""
    db = SessionLocal()
    
    try:
        # Check if admin exists
        result = await db.execute(
            select(User).where(User.role == UserRole.ADMIN)
        )
        admin = result.scalar_one_or_none()
        
        if admin:
            print(f"✓ Admin user already exists: {admin.email}")
            return
        
        # Create admin user
        admin_email = input("Enter admin email: ")
        admin_password = input("Enter admin password: ")
        admin_name = input("Enter admin full name (optional): ") or None
        
        admin = User(
            email=admin_email,
            password_hash=hash_password(admin_password),
            full_name=admin_name,
            role=UserRole.ADMIN,
            is_active=True
        )
        
        db.add(admin)
        await db.commit()
        await db.refresh(admin)
        
        print(f"\n✓ Admin user created successfully!")
        print(f"  Email: {admin.email}")
        print(f"  Role: {admin.role}")
        print(f"  ID: {admin.id}")
        
    except Exception as e:
        print(f"✗ Error creating admin user: {e}")
        await db.rollback()
    finally:
        await db.close()


def main():
    """Main function"""
    print("=" * 50)
    print("Create Admin User")
    print("=" * 50)
    asyncio.run(create_admin())


if __name__ == "__main__":
    main()
