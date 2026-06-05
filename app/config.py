from pydantic import BaseModel, SecretStr, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseConfig(BaseModel):
    url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/mookit_lms"
    pool_size: int = 20
    max_overflow: int = 10


class RedisConfig(BaseModel):
    url: str = "redis://localhost:6379/0"


class OpenAIConfig(BaseModel):
    api_key: SecretStr = Field(default="sk-placeholder")
    model: str = "gpt-4o"


class MooKitConfig(BaseModel):
    base_url: str = "https://test.mookit.in/api"
    timeout_connect: float = 5.0
    timeout_read: float = 60.0
    timeout_write: float = 10.0
    timeout_pool: float = 5.0
    max_retries: int = 3
    circuit_breaker_fail_max: int = 5
    circuit_breaker_reset_seconds: float = 30.0


class SecurityConfig(BaseModel):
    # Must be at least 32 chars in production; override via env SECURITY__SECRET_KEY
    secret_key: SecretStr = Field(default="dev-secret-key-CHANGE-IN-PRODUCTION-32c")
    confirm_token_ttl_seconds: int = 3600  # 1 hour before a pending confirmation expires


class LimitsConfig(BaseModel):
    max_file_size_bytes: int = 10 * 1024 * 1024   # 10 MB
    max_file_pages: int = 200
    max_messages_per_session: int = 100
    max_context_tokens: int = 8000
    rate_limit_rpm: int = 60          # requests per minute per tenant
    sse_ping_interval_seconds: float = 15.0
    upload_dir: str = "/tmp/mookit_uploads"
    max_zip_expansion_ratio: int = 100           # zip-bomb guard
    max_zip_uncompressed_bytes: int = 50 * 1024 * 1024  # 50 MB uncompressed cap


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        env_nested_delimiter="__",
    )

    app_name: str = "mooKIT AI Assistant"
    debug: bool = False

    db: DatabaseConfig = DatabaseConfig()
    redis: RedisConfig = RedisConfig()
    openai: OpenAIConfig = OpenAIConfig()
    mookit: MooKitConfig = MooKitConfig()
    security: SecurityConfig = SecurityConfig()
    limits: LimitsConfig = LimitsConfig()


settings = Settings()
