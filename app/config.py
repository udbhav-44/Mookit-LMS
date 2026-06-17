import os
from typing import Annotated, Any

from pydantic import BaseModel, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# Bumped whenever the static system prompt / tool-schema preamble changes (cache-busting).
PROMPT_VERSION = "3"


class DatabaseConfig(BaseModel):
    url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/mookit_lms"
    pool_size: int = 20
    max_overflow: int = 10


class RedisConfig(BaseModel):
    url: str = "redis://localhost:6379/0"


class OpenAIConfig(BaseModel):
    api_key: SecretStr = Field(default=SecretStr("sk-placeholder"))
    model: str = "gpt-4o"
    fast_model: str = "gpt-4o-mini"          # cheaper model for routing/extraction
    quiz_temperature: float = 0.9            # diversity for generation
    comprehend_temperature: float = 0.2      # blueprint comprehension: low, near-deterministic
    deterministic_temperature: float = 0.0   # evals / snapshots
    blueprint_model: str = "gpt-4o"          # long-context model for comprehension
    context_token_budget: int = 100_000      # source-router threshold; raise for long-context models
    embed_model: str = "text-embedding-3-small"
    embed_dim: int = 1536


class MooKitConfig(BaseModel):
    # The course short-name is appended per-request: {base_url}/{course}/{endpoint}
    base_url: str = "https://test.mookit.in/v2/api"
    timeout_connect: float = 5.0
    timeout_read: float = 60.0
    timeout_write: float = 10.0
    timeout_pool: float = 5.0
    max_retries: int = 3
    circuit_breaker_fail_max: int = 5
    circuit_breaker_reset_seconds: float = 30.0


class SecurityConfig(BaseModel):
    # Must be at least 32 chars in production; override via env SECURITY__SECRET_KEY
    secret_key: SecretStr = Field(default=SecretStr("dev-secret-key-CHANGE-IN-PRODUCTION-32c"))
    confirm_token_ttl_seconds: int = 3600  # 1 hour before a pending confirmation expires
    # If set, every request must carry header `x-service-key` matching this value — the trust boundary
    # between the mooKIT frontend and this service. Empty = disabled (dev only).
    service_api_key: SecretStr = Field(default=SecretStr(""))
    # CORS allowlist for the service-exposed API. Lock to the mooKIT frontend origins in production.
    # Accepts a JSON array (["https://a"]) or a comma-separated string (https://a,https://b).
    allowed_origins: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["*"])

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def _parse_origins(cls, v: Any) -> Any:
        if isinstance(v, str):
            s = v.strip()
            if not s:
                return ["*"]
            if s.startswith("["):
                import json as _json
                try:
                    return _json.loads(s)
                except Exception:
                    pass
            return [part.strip() for part in s.split(",") if part.strip()]
        return v


class LimitsConfig(BaseModel):
    max_file_size_bytes: int = 500 * 1024 * 1024   # 500 MB default; override via LIMITS__MAX_FILE_SIZE_BYTES
    max_file_pages: int = 200
    max_messages_per_session: int = 100
    max_context_tokens: int = 8000
    rate_limit_rpm: int = 60          # requests per minute per tenant
    sse_ping_interval_seconds: float = 15.0
    upload_dir: str = "/tmp/mookit_uploads"
    max_zip_expansion_ratio: int = 100           # zip-bomb guard
    max_zip_uncompressed_bytes: int = 50 * 1024 * 1024  # 50 MB uncompressed cap
    vision_max_pages: int = 15                   # page-image cap per doc for vision comprehension


class MemoryConfig(BaseModel):
    """Dev B two-channel memory knobs (transcript compaction)."""
    transcript_max_tokens: int = 6000
    transcript_keep_recent: int = 8


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        env_nested_delimiter="__",
    )

    app_name: str = "mooKIT AI Assistant"
    debug: bool = False
    rag_backend: str = "pgvector"  # "pgvector" (embeddings) | "keyword" (Redis term-overlap fallback)
    # Blueprint-first quiz pipeline (comprehend → plan → multi-span generate). When False,
    # the legacy one-span-per-question path is used. See app/gen/quiz/pipeline.py.
    quiz_blueprint_enabled: bool = False
    # Vision comprehension: read PDF page images so equations/figures survive (needs blueprint enabled).
    quiz_vision_enabled: bool = False
    # Adaptive source routing: per request, decide between full-document comprehension (better coverage
    # for a single doc that fits the model context) and top-k retrieval (cheaper, scales to large/many
    # docs) using app/gen/quiz/source_router.py. Implies wiring the blueprint comprehender.
    quiz_source_routing_enabled: bool = False
    # Create tables on startup (convenient for dev/out-of-box). Set False in prod and run
    # `alembic upgrade head` instead.
    auto_create_tables: bool = True

    db: DatabaseConfig = Field(default_factory=DatabaseConfig)
    redis: RedisConfig = Field(default_factory=RedisConfig)
    openai: OpenAIConfig = Field(default_factory=OpenAIConfig)
    mookit: MooKitConfig = Field(default_factory=MooKitConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    limits: LimitsConfig = Field(default_factory=LimitsConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)

    @model_validator(mode="after")
    def _openai_key_fallback(self) -> "Settings":
        # Accept the flat OPENAI_API_KEY (common .env convention) in addition to nested OPENAI__API_KEY.
        if self.openai.api_key.get_secret_value() in ("", "sk-placeholder"):
            flat = os.getenv("OPENAI_API_KEY")
            if flat:
                self.openai.api_key = SecretStr(flat)
        return self


settings = Settings()


def get_settings() -> Settings:
    return settings
