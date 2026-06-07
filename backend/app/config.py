from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://postgres:password@localhost:5432/smallpractice"

    @model_validator(mode="after")
    def _fix_db_url(self) -> "Settings":
        url = self.database_url
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        if "sslmode=require" in url:
            url = url.replace("sslmode=require", "ssl=require")
        object.__setattr__(self, "database_url", url)
        return self
    secret_key: str = "dev-secret-key-change-in-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    refresh_token_expire_days: int = 7
    encryption_key: str = "dev-encryption-key-32-chars-long!!"

    noshow_model: str = "ratio"

    matcher_w1: float = 1.0
    matcher_w2: float = 0.5
    matcher_w3: float = 0.3
    hold_window_minutes: int = 30

    risk_low_threshold: float = 0.2
    risk_high_threshold: float = 0.5


settings = Settings()
