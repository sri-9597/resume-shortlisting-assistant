from __future__ import annotations

from types import SimpleNamespace

import pytest

from shortlister.scoring.providers.anthropic import AnthropicProvider


class _StreamCtx:
    """Async context manager that mimics anthropic's stream interface."""

    def __init__(self, final_message) -> None:
        self._final = final_message
        self.captured: dict = {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get_final_message(self):
        return self._final


@pytest.mark.asyncio
async def test_anthropic_provider_sets_cache_control_and_extracts_tool_use(monkeypatch) -> None:
    """Verifies the cacheable_prefix is sent with cache_control and the tool_use input is returned."""
    captured = {}

    fake_tool_block = SimpleNamespace(
        type="tool_use",
        name="record_candidate_score",
        input={"candidate_id": "c1", "score": 9},
    )
    final_msg = SimpleNamespace(content=[fake_tool_block])

    def fake_stream(**kwargs):
        captured.update(kwargs)
        return _StreamCtx(final_msg)

    provider = AnthropicProvider(api_key="dummy", model="claude-sonnet-4-6")
    # Patch the messages.stream method on the underlying client.
    monkeypatch.setattr(provider._client.messages, "stream", fake_stream)

    out = await provider.score(
        system="sys",
        cacheable_prefix="STABLE-PREFIX",
        candidate_block="CANDIDATE-DATA",
        output_schema={"type": "object", "properties": {}, "required": []},
        tool_name="record_candidate_score",
        tool_description="record",
    )
    assert out == {"candidate_id": "c1", "score": 9}

    user_msg = captured["messages"][0]
    assert user_msg["role"] == "user"
    content = user_msg["content"]
    assert content[0]["text"] == "STABLE-PREFIX"
    assert content[0]["cache_control"] == {"type": "ephemeral"}
    assert content[1]["text"] == "CANDIDATE-DATA"
    assert "cache_control" not in content[1]

    assert captured["tool_choice"] == {"type": "tool", "name": "record_candidate_score"}
    assert captured["tools"][0]["name"] == "record_candidate_score"


@pytest.mark.asyncio
async def test_anthropic_provider_raises_when_no_tool_use_block(monkeypatch) -> None:
    # Patch the retry delays so this test doesn't sleep the full 42s.
    monkeypatch.setattr("shortlister.scoring.providers.anthropic.LLM_RETRY_DELAYS_SECONDS", (0.0, 0.0, 0.0))

    text_block = SimpleNamespace(type="text", text="hi")
    final_msg = SimpleNamespace(content=[text_block])

    provider = AnthropicProvider(api_key="dummy")
    monkeypatch.setattr(provider._client.messages, "stream", lambda **k: _StreamCtx(final_msg))

    with pytest.raises(RuntimeError, match="Anthropic scoring failed"):
        await provider.score(
            system="s",
            cacheable_prefix="p",
            candidate_block="c",
            output_schema={"type": "object"},
            tool_name="record_candidate_score",
            tool_description="d",
        )
