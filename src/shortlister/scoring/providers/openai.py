from __future__ import annotations

import asyncio
import json

from openai import AsyncOpenAI

from ...config import DEFAULT_OPENAI_MODEL, LLM_RETRY_DELAYS_SECONDS
from ...logging import get_logger
from .base import LLMProvider

log = get_logger(__name__)


class OpenAIProvider(LLMProvider):
    """OpenAI provider using Structured Outputs for guaranteed-shape JSON.

    Trade-offs vs. AnthropicProvider:
      - No user-controlled prompt caching markers — OpenAI does automatic caching
        on long stable prefixes, which we approximate by always putting
        `cacheable_prefix` first in the user message.
      - `strict=true` requires the schema to be a strict-mode-compliant subset
        (no `additionalProperties: true`, all properties in `required`). If the
        rubric schema doesn't comply, the API will reject it and the retry loop
        will surface the error.
    """

    name = "openai"

    def __init__(self, *, api_key: str | None, model: str = DEFAULT_OPENAI_MODEL) -> None:
        self.model = model
        self._client = AsyncOpenAI(api_key=api_key) if api_key else AsyncOpenAI()

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
        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": tool_name,
                "description": tool_description,
                "schema": output_schema,
                "strict": True,
            },
        }
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": f"{cacheable_prefix}\n\n{candidate_block}"},
        ]

        last_err: Exception | None = None
        for attempt, delay in enumerate((0.0,) + LLM_RETRY_DELAYS_SECONDS):
            if delay:
                await asyncio.sleep(delay)
            try:
                return await self._call_once(messages=messages, response_format=response_format)
            except Exception as e:  # noqa: BLE001
                last_err = e
                log.warning("OpenAI call attempt %d failed: %s", attempt + 1, e)
        raise RuntimeError(
            f"OpenAI scoring failed after {len(LLM_RETRY_DELAYS_SECONDS) + 1} attempts: {last_err}"
        )

    async def _call_once(self, *, messages: list[dict], response_format: dict) -> dict:
        completion = await self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            response_format=response_format,
            max_tokens=2048,
        )
        choice = completion.choices[0]
        if choice.finish_reason == "length":
            raise RuntimeError("OpenAI response truncated by max_tokens")

        message = choice.message
        refusal = getattr(message, "refusal", None)
        if refusal:
            raise RuntimeError(f"OpenAI refused: {refusal}")

        content = message.content
        if not content:
            raise RuntimeError("OpenAI returned empty content with no refusal")

        return json.loads(content)
