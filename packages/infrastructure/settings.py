from decimal import Decimal
from typing import Literal
from cryptography.fernet import Fernet
from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    app_mode: Literal["demo", "test", "production"] = "demo"
    database_url: str = "sqlite:///./saup.db"
    redis_url: str = "redis://localhost:6379/0"
    rate_limit_backend: Literal["memory", "redis"] = "memory"
    public_origin: str = "http://localhost:3000"
    pii_encryption_key: SecretStr
    admin_username: str = "admin"
    admin_password: SecretStr = SecretStr("")
    real_payments_enabled: bool = False
    min_margin: Decimal = Field(default=Decimal("0.15"), ge=0, lt=1)
    price_spike: Decimal = Field(default=Decimal("0.10"), gt=0, lt=10)
    auto_payment_limit: int = Field(default=30000, ge=0)
    daily_payment_limit: int = Field(default=300000, ge=0)
    auto_refund_limit: int = Field(default=10000, ge=0)
    safety_reserve: int = Field(default=100000, ge=0)
    refund_reserve: int = Field(default=50000, ge=0)
    tax_reserve: int = Field(default=0, ge=0)
    inventory_max_age_seconds: int = Field(default=3600, ge=1)
    order_hold_seconds: int = Field(default=0, ge=0)
    session_ttl_seconds: int = Field(default=3600, ge=60, le=86400)
    max_job_attempts: int = Field(default=5, ge=1, le=10)
    upload_max_bytes: int = Field(default=5_000_000, ge=1, le=10_000_000)

    claim_window_days: int = Field(default=30, ge=1, le=365)
    claim_min_samples: int = Field(default=20, ge=1, le=100000)
    claim_warning_rate: Decimal = Field(default=Decimal("0.10"), ge=0, le=1)
    claim_pause_rate: Decimal = Field(default=Decimal("0.20"), ge=0, le=1)
    seller_loss_pause_rate: Decimal = Field(default=Decimal("0.10"), ge=0, le=1)

    @model_validator(mode="after")
    def safety(self):
        if self.claim_warning_rate > self.claim_pause_rate:
            raise ValueError("Claim warning threshold must not exceed pause threshold")
        Fernet(self.pii_encryption_key.get_secret_value().encode())
        if self.app_mode == "production":
            if not self.database_url.startswith("postgresql+"):
                raise ValueError("Production requires PostgreSQL")
            if self.rate_limit_backend != "redis":
                raise ValueError("Production requires distributed rate limiting")
            if not self.public_origin.startswith("https://"):
                raise ValueError("Production requires HTTPS")
        if self.real_payments_enabled:
            raise ValueError("BLOCKED_BY_PROVIDER_ACCESS: no certified live payment adapter")
        return self
