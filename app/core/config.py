from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List
from functools import lru_cache


class Settings(BaseSettings):
    """Application configuration settings"""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )
    
    # Application
    app_name: str = "Email Warm-Up Pro"
    debug: bool = False
    environment: str = "development"
    secret_key: str
    
    # Database
    database_url: str
    database_url_async: str
    
    # Redis & Celery
    redis_url: str
    celery_broker_url: str
    celery_result_backend: str
    
    # JWT Authentication
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 30
    jwt_refresh_token_expire_days: int = 7
    
    # Google OAuth
    google_client_id: str
    google_client_secret: str
    google_redirect_uri: str
    google_project_id: str = ""  # For Gmail Pub/Sub
    gmail_pubsub_topic: str = "gmail-notifications"  # Pub/Sub topic name
    
    # SendGrid
    sendgrid_api_key: str
    
    # OpenAI
    openai_api_key: str
    openai_model: str = "gpt-3.5-turbo"
    openai_max_tokens: int = 150
    
    # Email Warm-Up Settings
    default_daily_send_limit: int = 50
    min_daily_emails: int = 5
    max_daily_emails: int = 100
    warmup_increment_days: int = 7
    warmup_increment_amount: int = 5
    
    # Safety Limits
    max_spam_complaint_rate: float = 0.01
    max_bounce_rate: float = 0.05
    auto_pause_on_spam: bool = True
    
    # CORS
    allowed_origins: str = "http://localhost:8000"
    
    @property
    def allowed_origins_list(self) -> List[str]:
        """Parse comma-separated origins into list"""
        return [origin.strip() for origin in self.allowed_origins.split(",")]
    
    # Encryption key for sensitive data (derived from secret_key)
    @property
    def encryption_key(self) -> bytes:
        """Generate encryption key from secret key"""
        from hashlib import sha256
        return sha256(self.secret_key.encode()).digest()


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance"""
    return Settings()
