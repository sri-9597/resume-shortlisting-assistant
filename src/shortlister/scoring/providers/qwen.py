from __future__ import annotations

import asyncio
import json

import httpx

from ...config import DEFAULT_OLLAMA_BASE_URL, DEFAULT_QWEN_MODEL, LLM_RETRY_DELAYS_SECONDS
from ...logging import get_logger
from .base import LLMProvider

log = get_logger(__name__)


class QwenProvider(LLMProvider):
    """Local Qwen model served via an Ollama-compatible HTTP endpoint.

    Default model is qwen3:30b on localhost:11434. The `OLLAMA_HOST`
    env var (read in RuntimeConfig) can point at any compatible server.

    By default requests carry `think: false` to suppress the reasoning preamble
    that thinking models (qwen3) emit and that would corrupt JSON-mode output.
    Set `disable_thinking=False` for non-thinking models that reject the field.
    """

    name = "qwen"

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_OLLAMA_BASE_URL,
        model: str = DEFAULT_QWEN_MODEL,
        disable_thinking: bool = True,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        # Thinking-capable models (e.g. qwen3) emit a reasoning preamble that breaks
        # JSON-mode parsing. Sending `think: false` suppresses it. Non-thinking models
        # (e.g. the default qwen2.5) reject this field, so callers can opt out.
        self.disable_thinking = disable_thinking

    async def score(
        self,
        *,
        system: str,
        cacheable_prefix: str,
        candidate_block: str,
        output_schema: dict,
        tool_name: str,
        tool_description: str,
    ) -> dict:
        # Qwen via Ollama doesn't support tool-use; we ask for JSON-mode and validate post-hoc.
        # The schema is embedded in the prompt so the model knows the shape to produce.
        user_msg = (
            f"{cacheable_prefix}\n\n"
            f"--- CANDIDATE ---\n{candidate_block}\n\n"
            f"--- OUTPUT (return ONLY a single JSON object conforming to this schema; "
            f"do not include backticks, comments, or any prose) ---\n"
            f"{json.dumps(output_schema)}"
        )
        payload = {
            "model": self.model,
            "stream": False,
            "format": "json",
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user_msg},
            ],
            "options": {"temperature": 0.1},
        }
        if self.disable_thinking:
            payload["think"] = False
        url = f"{self.base_url}/api/chat"

        last_err: Exception | None = None
        for attempt, delay in enumerate((0.0,) + LLM_RETRY_DELAYS_SECONDS):
            if delay:
                await asyncio.sleep(delay)
            try:
                async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
                    resp = await client.post(url, json=payload)
                    resp.raise_for_status()
                    body = resp.json()
                content = body.get("message", {}).get("content", "")
                if not content:
                    raise RuntimeError(f"Empty content from Ollama: {body!r}")
                return json.loads(content)
            except Exception as e:  # noqa: BLE001
                last_err = e
                log.warning("Qwen call attempt %d failed: %s", attempt + 1, e)
        raise RuntimeError(f"Qwen scoring failed after {len(LLM_RETRY_DELAYS_SECONDS) + 1} attempts: {last_err}")
