from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from shortlister.scoring.providers.openai import OpenAIProvider


def _make_completion(content: str | None, *, refusal: str | None = None, finish_reason: str = "stop"):
    choice = SimpleNamespace(
        message=SimpleNamespace(content=content, refusal=refusal),
        finish_reason=finish_reason,
    )
    return SimpleNamespace(choices=[choice])


@pytest.mark.asyncio
async def test_openai_provider_sends_strict_json_schema_and_returns_parsed(monkeypatch) -> None:
    captured: dict = {}
    payload = {"candidate_id": "c1", "score": 9}
    fake_completion = _make_completion(json.dumps(payload))

    async def fake_create(**kwargs):
        captured.update(kwargs)
        return fake_completion

    provider = OpenAIProvider(api_key="dummy", model="gpt-4o")
    monkeypatch.setattr(provider._client.chat.completions, "create", fake_create)

    out = await provider.score(
        system="sys",
        cacheable_prefix="STABLE-PREFIX",
        candidate_block="CANDIDATE-DATA",
        output_schema={
            "type": "object",
            "properties": {"candidate_id": {"type": "string"}, "score": {"type": "integer"}},
            "required": ["candidate_id", "score"],
            "additionalProperties": False,
        },
        tool_name="record_candidate_score",
        tool_description="record",
    )
    assert out == payload

    assert captured["model"] == "gpt-4o"
    rf = captured["response_format"]
    assert rf["type"] == "json_schema"
    assert rf["json_schema"]["name"] == "record_candidate_score"
    assert rf["json_schema"]["description"] == "record"
    assert rf["json_schema"]["strict"] is True

    messages = captured["messages"]
    assert messages[0] == {"role": "system", "content": "sys"}
    user_content = messages[1]["content"]
    assert messages[1]["role"] == "user"
    # Cacheable prefix first (auto-cache friendly), candidate block after.
    assert user_content.startswith("STABLE-PREFIX")
    assert "CANDIDATE-DATA" in user_content
    assert user_content.index("STABLE-PREFIX") < user_content.index("CANDIDATE-DATA")


@pytest.mark.asyncio
async def test_openai_provider_retries_then_raises(monkeypatch) -> None:
    monkeypatch.setattr(
        "shortlister.scoring.providers.openai.LLM_RETRY_DELAYS_SECONDS", (0.0, 0.0, 0.0)
    )

    async def boom(**kwargs):
        raise RuntimeError("api error")

    provider = OpenAIProvider(api_key="dummy")
    monkeypatch.setattr(provider._client.chat.completions, "create", boom)

    with pytest.raises(RuntimeError, match="OpenAI scoring failed"):
        await provider.score(
            system="s",
            cacheable_prefix="p",
            candidate_block="c",
            output_schema={"type": "object"},
            tool_name="t",
            tool_description="d",
        )


@pytest.mark.asyncio
async def test_openai_provider_raises_on_refusal(monkeypatch) -> None:
    monkeypatch.setattr(
        "shortlister.scoring.providers.openai.LLM_RETRY_DELAYS_SECONDS", (0.0, 0.0, 0.0)
    )

    fake_completion = _make_completion(None, refusal="cannot evaluate candidates")

    async def fake_create(**kwargs):
        return fake_completion

    provider = OpenAIProvider(api_key="dummy")
    monkeypatch.setattr(provider._client.chat.completions, "create", fake_create)

    with pytest.raises(RuntimeError, match="OpenAI scoring failed"):
        await provider.score(
            system="s",
            cacheable_prefix="p",
            candidate_block="c",
            output_schema={"type": "object"},
            tool_name="t",
            tool_description="d",
        )


@pytest.mark.asyncio
async def test_openai_provider_raises_on_length_truncation(monkeypatch) -> None:
    monkeypatch.setattr(
        "shortlister.scoring.providers.openai.LLM_RETRY_DELAYS_SECONDS", (0.0, 0.0, 0.0)
    )

    fake_completion = _make_completion('{"partial":', finish_reason="length")

    async def fake_create(**kwargs):
        return fake_completion

    provider = OpenAIProvider(api_key="dummy")
    monkeypatch.setattr(provider._client.chat.completions, "create", fake_create)

    with pytest.raises(RuntimeError, match="OpenAI scoring failed"):
        await provider.score(
            system="s",
            cacheable_prefix="p",
            candidate_block="c",
            output_schema={"type": "object"},
            tool_name="t",
            tool_description="d",
        )
