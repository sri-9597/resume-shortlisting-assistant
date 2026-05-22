from __future__ import annotations

import asyncio
from typing import Any

from anthropic import AsyncAnthropic

from ...config import DEFAULT_ANTHROPIC_MODEL, LLM_RETRY_DELAYS_SECONDS
from ...logging import get_logger
from .base import LLMProvider

log = get_logger(__name__)


class AnthropicProvider(LLMProvider):
    """Claude provider using streaming + tool-use for structured output, with prompt caching."""

    name = "claude"

    def __init__(self, *, api_key: str | None, model: str = DEFAULT_ANTHROPIC_MODEL) -> None:
        self.model = model
        self._client = AsyncAnthropic(api_key=api_key) if api_key else AsyncAnthropic()

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
        tools = [
            {
                "name": tool_name,
                "description": tool_description,
                "input_schema": output_schema,
            }
        ]
        user_content = [
            {
                "type": "text",
                "text": cacheable_prefix,
                "cache_control": {"type": "ephemeral"},
            },
            {
                "type": "text",
                "text": candidate_block,
            },
        ]

        last_err: Exception | None = None
        for attempt, delay in enumerate((0.0,) + LLM_RETRY_DELAYS_SECONDS):
            if delay:
                await asyncio.sleep(delay)
            try:
                return await self._stream_once(
                    system=system,
                    user_content=user_content,
                    tools=tools,
                    tool_name=tool_name,
                )
            except Exception as e:  # noqa: BLE001
                last_err = e
                log.warning("Anthropic call attempt %d failed: %s", attempt + 1, e)
        raise RuntimeError(f"Anthropic scoring failed after {len(LLM_RETRY_DELAYS_SECONDS) + 1} attempts: {last_err}")

    async def _stream_once(
        self,
        *,
        system: str,
        user_content: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_name: str,
    ) -> dict:
        async with self._client.messages.stream(
            model=self.model,
            max_tokens=2048,
            system=system,
            tools=tools,
            tool_choice={"type": "tool", "name": tool_name},
            messages=[{"role": "user", "content": user_content}],
        ) as stream:
            final = await stream.get_final_message()

        for block in final.content:
            block_type = getattr(block, "type", None)
            if block_type == "tool_use" and getattr(block, "name", None) == tool_name:
                return block.input

        raise RuntimeError(
            f"Anthropic response contained no tool_use block named {tool_name!r}; got types: "
            + ", ".join(getattr(b, "type", "?") for b in final.content)
        )
