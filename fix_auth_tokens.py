#!/usr/bin/env python3
"""
Fix Authentication Token Issues

This script helps diagnose and fix token-related issues:
1. Checks which accounts have invalid/corrupted tokens
2. Marks them as DISCONNECTED so they show up for re-authentication
3. Reports which accounts need attention

Run this script when you see InvalidToken errors in Celery logs.
"""

from app.core.database import SessionLocal
from app.db.models import EmailInbox, BotEmail, InboxStatus, BotEmailStatus
from app.core.security import decrypt_data
from cryptography.fernet import InvalidToken
from datetime import datetime, timezone


def check_and_fix_tokens():
    """Check all accounts for token issues"""
    db = SessionLocal()
    
    print("=" * 60)
    print("CHECKING AUTHENTICATION TOKENS")
    print("=" * 60)
    
    user_issues = []
    bot_issues = []
    
    now = datetime.now(timezone.utc)
    
    # Check user inboxes
    print("\n📧 Checking User Inboxes...")
    inboxes = db.query(EmailInbox).all()
    
    for inbox in inboxes:
        issues = []
        
        # Check if tokens exist
        if not inbox.access_token:
            issues.append("No access token")
        else:
            # Try to decrypt
            try:
                decrypt_data(inbox.access_token)
            except InvalidToken:
                issues.append("Cannot decrypt access token")
            except Exception as e:
                issues.append(f"Token error: {type(e).__name__}")
        
        if not inbox.refresh_token:
            issues.append("No refresh token")
        else:
            try:
                decrypt_data(inbox.refresh_token)
            except InvalidToken:
                issues.append("Cannot decrypt refresh token")
            except Exception as e:
                issues.append(f"Refresh token error: {type(e).__name__}")
        
        # Check expiry
        if inbox.token_expiry and inbox.token_expiry < now:
            issues.append("Token expired")
        
        if issues:
            user_issues.append({
                'inbox': inbox,
                'issues': issues,
                'email': inbox.email_address,  # Store email before detach
                'id': inbox.id  # Store ID before detach
            })
            
            # Mark as disconnected if currently active
            if inbox.status == InboxStatus.ACTIVE:
                print(f"  ❌ {inbox.email_address} (ID: {inbox.id})")
                print(f"     Issues: {', '.join(issues)}")
                print(f"     Action: Marking as DISCONNECTED")
                
                inbox.status = InboxStatus.DISCONNECTED
                inbox.last_error = f"Authentication issues detected: {', '.join(issues)}"
                inbox.updated_at = now
        else:
            print(f"  ✅ {inbox.email_address} (ID: {inbox.id}) - OK")
    
    # Check bot emails
    print("\n🤖 Checking Bot Emails...")
    bots = db.query(BotEmail).all()
    
    for bot in bots:
        issues = []
        
        # Check if tokens exist
        if not bot.access_token:
            issues.append("No access token")
        else:
            # Try to decrypt
            try:
                decrypt_data(bot.access_token)
            except InvalidToken:
                issues.append("Cannot decrypt access token")
            except Exception as e:
                issues.append(f"Token error: {type(e).__name__}")
        
        if not bot.refresh_token:
            issues.append("No refresh token")
        else:
            try:
                decrypt_data(bot.refresh_token)
            except InvalidToken:
                issues.append("Cannot decrypt refresh token")
            except Exception as e:
                issues.append(f"Refresh token error: {type(e).__name__}")
        
        # Check expiry
        if bot.token_expiry and bot.token_expiry < now:
            issues.append("Token expired")
        
        if issues:
            bot_issues.append({
                'bot': bot,
                'issues': issues,
                'email': bot.email_address,  # Store email before detach
                'id': bot.id  # Store ID before detach
            })
            
            # Mark as disconnected if currently active
            if bot.status == BotEmailStatus.ACTIVE:
                print(f"  ❌ {bot.email_address} (ID: {bot.id})")
                print(f"     Issues: {', '.join(issues)}")
                print(f"     Action: Marking as DISCONNECTED")
                
                bot.status = BotEmailStatus.DISCONNECTED
                bot.last_error = f"Authentication issues detected: {', '.join(issues)}"
                bot.is_healthy = False
                bot.consecutive_errors += 1
                bot.last_check_at = now
        else:
            print(f"  ✅ {bot.email_address} (ID: {bot.id}) - OK")
    
    # Commit changes
    try:
        db.commit()
        print("\n✅ Database updated successfully")
    except Exception as e:
        print(f"\n❌ Error updating database: {e}")
        db.rollback()
    finally:
        db.close()
    
    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    
    if user_issues:
        print(f"\n⚠️  {len(user_issues)} User Inbox(es) Need Re-authentication:")
        for item in user_issues:
            email = item['email']
            inbox_id = item['id']
            print(f"   • {email} (ID: {inbox_id})")
            print(f"     → Visit: /inbox to reconnect")
    else:
        print("\n✅ All user inboxes have valid tokens")
    
    if bot_issues:
        print(f"\n⚠️  {len(bot_issues)} Bot Email(s) Need Re-authentication:")
        for item in bot_issues:
            email = item['email']
            bot_id = item['id']
            print(f"   • {email} (ID: {bot_id})")
            print(f"     → Visit: /admin/bot-emails to reconnect")
    else:
        print("\n✅ All bot emails have valid tokens")
    
    print("\n" + "=" * 60)
    
    if user_issues or bot_issues:
        print("\n📝 NEXT STEPS:")
        print("   1. Log into the application")
        print("   2. Go to the pages listed above")
        print("   3. Click 'Reconnect' for each affected account")
        print("   4. Complete the Google OAuth flow")
        print("   5. Re-run this script to verify all tokens are valid")
    else:
        print("\n🎉 All accounts are properly authenticated!")
    
    print()


if __name__ == "__main__":
    check_and_fix_tokens()
