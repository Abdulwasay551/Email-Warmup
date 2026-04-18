"""Quick setup script for admin user"""
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
import sys
sys.path.insert(0, '.')

from app.db.models import User, UserRole
from app.core.security import hash_password
from app.core.config import get_settings

settings = get_settings()

# Use sync engine for this script
engine = create_engine(
    settings.database_url.replace('+asyncpg', ''),
    echo=False
)
SessionLocal = sessionmaker(bind=engine)


def create_quick_admin():
    """Create default admin user quickly"""
    db = SessionLocal()
    
    try:
        # Check if admin already exists
        existing = db.execute(
            select(User).where(User.email == "admin@example.com")
        ).scalar_one_or_none()
        
        if existing:
            print("✓ Admin user already exists!")
            print("  Email: admin@example.com")
            print("  Password: admin123")
            return
        
        # Create admin with default credentials
        admin = User(
            email="admin@example.com",
            password_hash=hash_password("admin123"),
            full_name="System Administrator",
            role=UserRole.ADMIN,
            is_active=True
        )
        
        db.add(admin)
        db.commit()
        
        print("✓ Admin user created successfully!")
        print("  Email: admin@example.com")
        print("  Password: admin123")
        print("\n⚠️  Please change these credentials in production!")
        
    except Exception as e:
        print(f"Error: {e}")
        db.rollback()
    finally:
        db.close()


if __name__ == "__main__":
    create_quick_admin()
