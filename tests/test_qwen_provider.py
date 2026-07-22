from __future__ import annotations

import json

import httpx
import pytest

from shortlister.scoring.providers.qwen import QwenProvider


@pytest.mark.asyncio
async def test_qwen_provider_posts_to_ollama_and_parses_json(monkeypatch) -> None:
    captured = {}

    class _MockResponse:
        status_code = 200

        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict:
            return {"message": {"content": json.dumps({"hello": "world"})}}

    class _MockClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, json):  # noqa: A002 - matches httpx API name
            captured["url"] = url
            captured["payload"] = json
            return _MockResponse()

    monkeypatch.setattr(httpx, "AsyncClient", _MockClient)

    provider = QwenProvider(base_url="http://localhost:11434", model="qwen2.5:14b-instruct")
    result = await provider.score(
        system="sys",
        cacheable_prefix="prefix",
        candidate_block="cand",
        output_schema={"type": "object"},
        tool_name="record",
        tool_description="d",
    )
    assert result == {"hello": "world"}
    assert captured["url"] == "http://localhost:11434/api/chat"
    assert captured["payload"]["model"] == "qwen2.5:14b-instruct"
    assert captured["payload"]["format"] == "json"
    # Ensure cacheable_prefix and candidate_block both reached the user message.
    msgs = captured["payload"]["messages"]
    user = next(m for m in msgs if m["role"] == "user")
    assert "prefix" in user["content"] and "cand" in user["content"]


def _capturing_client(captured: dict):
    class _MockResponse:
        status_code = 200

        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict:
            return {"message": {"content": json.dumps({"ok": True})}}

    class _MockClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, json):  # noqa: A002 - matches httpx API name
            captured["payload"] = json
            return _MockResponse()

    return _MockClient


async def _run_score(provider: QwenProvider) -> None:
    await provider.score(
        system="sys",
        cacheable_prefix="prefix",
        candidate_block="cand",
        output_schema={"type": "object"},
        tool_name="record",
        tool_description="d",
    )


@pytest.mark.asyncio
async def test_qwen_disables_thinking_by_default(monkeypatch) -> None:
    captured: dict = {}
    monkeypatch.setattr(httpx, "AsyncClient", _capturing_client(captured))

    await _run_score(QwenProvider(base_url="http://localhost:11434", model="qwen3:30b"))

    assert captured["payload"]["think"] is False


@pytest.mark.asyncio
async def test_qwen_omits_think_when_disabled(monkeypatch) -> None:
    captured: dict = {}
    monkeypatch.setattr(httpx, "AsyncClient", _capturing_client(captured))

    provider = QwenProvider(
        base_url="http://localhost:11434",
        model="qwen2.5:14b-instruct",
        disable_thinking=False,
    )
    await _run_score(provider)

    assert "think" not in captured["payload"]
