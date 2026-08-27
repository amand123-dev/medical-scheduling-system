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

    # Retrieval: "fastembed" runs a local ONNX model; "hashing" is the offline
    # deterministic fallback used by tests and CI.
    embedding_provider: str = "fastembed"
    rag_top_k: int = 5

    # Generation. Protocol docs carry no PHI, so answering over them is on by
    # default. Patient passages are a different matter: even with names
    # redacted the token is reversible, so sending them to a hosted model is a
    # contractual question (BAA + zero retention), not a technical one. That
    # path ships off by default and an admin turns it on deliberately.
    anthropic_api_key: str = ""
    generation_model: str = "claude-sonnet-5"
    generation_max_tokens: int = 1024
    protocol_generation_enabled: bool = True
    patient_generation_enabled: bool = False
    # Per-user cap on generation calls per hour. The deployed demo is public,
    # and every generated answer costs money. 0 disables the check.
    generation_rate_limit_per_hour: int = 60

    matcher_w1: float = 1.0
    matcher_w2: float = 0.5
    matcher_w3: float = 0.3
    hold_window_minutes: int = 30

    risk_low_threshold: float = 0.2
    risk_high_threshold: float = 0.5


settings = Settings()
