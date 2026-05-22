from __future__ import annotations

import os
from dataclasses import dataclass


LLM_RETRY_DELAYS_SECONDS = (2.0, 8.0, 32.0)

PARSE_MIN_USEFUL_CHARS = 200

DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-4-6"
DEFAULT_ANTHROPIC_KNOCKOUT_MODEL = "claude-haiku-4-5-20251001"
DEFAULT_OPENAI_MODEL = "gpt-4o"
DEFAULT_OPENAI_KNOCKOUT_MODEL = "gpt-4o-mini"
DEFAULT_QWEN_MODEL = "qwen2.5:14b-instruct"
DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    model: str


@dataclass(frozen=True)
class RuntimeConfig:
    ollama_base_url: str = DEFAULT_OLLAMA_BASE_URL
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None

    @classmethod
    def from_env(cls) -> "RuntimeConfig":
        return cls(
            ollama_base_url=os.environ.get("OLLAMA_HOST", DEFAULT_OLLAMA_BASE_URL),
            anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY"),
            openai_api_key=os.environ.get("OPENAI_API_KEY"),
        )
