"""Configuration for the AI-side (Dev B). Dev A owns the full runtime settings;
this is the subset the brain + quiz pipeline need to run solo.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROMPT_VERSION = "1"
"""Bumped whenever the static system prompt / tool-schema preamble changes (cache-busting)."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="", extra="ignore")

    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")

    # Default model for chat/tool-calling; cheaper model for routing/extraction.
    default_model: str = "gpt-4o"
    fast_model: str = "gpt-4o-mini"

    # Generation defaults.
    quiz_temperature: float = 0.9
    deterministic_temperature: float = 0.0

    # Memory.
    transcript_max_tokens: int = 6000
    transcript_keep_recent: int = 8


def get_settings() -> Settings:
    return Settings()
