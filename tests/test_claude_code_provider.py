from __future__ import annotations

import asyncio
import json

import pytest

from shortlister.scoring.providers import claude_code as cc_module
from shortlister.scoring.providers.claude_code import ClaudeCodeProvider, _extract_json_payload


class _FakeProcess:
    def __init__(self, stdout: bytes, returncode: int = 0, stderr: bytes = b"") -> None:
        self._stdout = stdout
        self._stderr = stderr
        self.returncode = returncode

    async def communicate(self, _stdin_bytes: bytes) -> tuple[bytes, bytes]:
        return self._stdout, self._stderr

    def kill(self) -> None:  # pragma: no cover - only used on timeout
        pass

    async def wait(self) -> int:  # pragma: no cover
        return self.returncode


@pytest.mark.asyncio
async def test_claude_code_provider_invokes_cli_with_expected_flags(monkeypatch) -> None:
    captured_args: list[str] = []

    payload = {
        "candidate_id": "c1",
        "criteria": [{"id": "a", "score": 9, "reasoning": "good"}],
        "knockouts": [{"id": "k1", "passed": True, "reasoning": "ok"}],
        "weighted_total": 8.5,
        "recommend": True,
        "summary": "strong",
    }
    envelope = {
        "type": "result",
        "subtype": "success",
        "result": json.dumps(payload),
        "session_id": "abc",
        "total_cost_usd": 0.01,
    }

    async def fake_exec(*args, **kwargs):
        captured_args.extend(args)
        return _FakeProcess(json.dumps(envelope).encode("utf-8"))

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    provider = ClaudeCodeProvider(model="sonnet", binary="claude")
    schema = {"type": "object", "properties": {}, "required": []}
    result = await provider.score(
        system="sys",
        cacheable_prefix="prefix",
        candidate_block="cand",
        output_schema=schema,
        tool_name="record",
        tool_description="d",
    )
    assert result == payload
    assert "claude" in captured_args[0]
    assert "-p" in captured_args
    # `--bare` forces API-key-only auth and never reads the OAuth/keychain login
    # the Claude Code subscription uses, so it must NOT be passed here.
    assert "--bare" not in captured_args
    assert "--no-session-persistence" in captured_args
    assert "--output-format" in captured_args
    fmt_idx = captured_args.index("--output-format")
    assert captured_args[fmt_idx + 1] == "json"
    assert "--json-schema" in captured_args
    schema_idx = captured_args.index("--json-schema")
    assert json.loads(captured_args[schema_idx + 1]) == schema
    assert "--system-prompt" in captured_args
    sys_idx = captured_args.index("--system-prompt")
    assert captured_args[sys_idx + 1] == "sys"
    assert "--model" in captured_args
    model_idx = captured_args.index("--model")
    assert captured_args[model_idx + 1] == "sonnet"


@pytest.mark.asyncio
async def test_claude_code_provider_retries_then_raises(monkeypatch) -> None:
    monkeypatch.setattr(cc_module, "LLM_RETRY_DELAYS_SECONDS", (0.0, 0.0, 0.0))

    async def fake_exec(*args, **kwargs):
        return _FakeProcess(b"", returncode=1, stderr=b"boom")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    provider = ClaudeCodeProvider(model="sonnet", binary="claude")
    with pytest.raises(RuntimeError, match="claude-code scoring failed"):
        await provider.score(
            system="s",
            cacheable_prefix="p",
            candidate_block="c",
            output_schema={"type": "object"},
            tool_name="record",
            tool_description="d",
        )


@pytest.mark.asyncio
async def test_claude_code_provider_surfaces_stdout_error_on_nonzero_exit(monkeypatch) -> None:
    # The CLI reports auth failures ("Not logged in") in stdout's JSON envelope
    # with an EMPTY stderr and exit 1. The old handler only read stderr, so the
    # error message was blank. Verify the stdout reason is now surfaced.
    monkeypatch.setattr(cc_module, "LLM_RETRY_DELAYS_SECONDS", (0.0,))
    envelope = {
        "type": "result",
        "subtype": "success",
        "is_error": True,
        "result": "Not logged in · Please run /login",
    }

    async def fake_exec(*args, **kwargs):
        return _FakeProcess(json.dumps(envelope).encode("utf-8"), returncode=1, stderr=b"")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    provider = ClaudeCodeProvider(model="sonnet", binary="claude")
    with pytest.raises(RuntimeError, match="Not logged in"):
        await provider.score(
            system="s",
            cacheable_prefix="p",
            candidate_block="c",
            output_schema={"type": "object"},
            tool_name="record",
            tool_description="d",
        )


def test_extract_json_payload_raises_on_is_error_even_when_subtype_success() -> None:
    # A zero-exit envelope can still carry is_error=True with subtype "success".
    env = {"type": "result", "subtype": "success", "is_error": True, "result": "Not logged in"}
    with pytest.raises(RuntimeError, match="Not logged in"):
        _extract_json_payload(json.dumps(env))


def test_extract_json_payload_handles_string_result() -> None:
    payload = {"candidate_id": "c1", "ok": True}
    env = {"type": "result", "subtype": "success", "result": json.dumps(payload)}
    assert _extract_json_payload(json.dumps(env)) == payload


def test_extract_json_payload_handles_object_result() -> None:
    payload = {"candidate_id": "c1", "ok": True}
    env = {"type": "result", "subtype": "success", "result": payload}
    assert _extract_json_payload(json.dumps(env)) == payload


def test_extract_json_payload_strips_markdown_fences() -> None:
    payload = {"candidate_id": "c1", "ok": True}
    fenced = "```json\n" + json.dumps(payload) + "\n```"
    env = {"type": "result", "subtype": "success", "result": fenced}
    assert _extract_json_payload(json.dumps(env)) == payload


def test_extract_json_payload_raises_on_error_subtype() -> None:
    env = {"type": "result", "subtype": "error_during_execution", "result": "boom"}
    with pytest.raises(RuntimeError, match="non-success result"):
        _extract_json_payload(json.dumps(env))


def test_extract_json_payload_falls_back_to_bare_object() -> None:
    # If for some reason the envelope shape changes and the CLI returns the model's
    # JSON directly, we should still recover it.
    payload = {"candidate_id": "c1", "ok": True}
    assert _extract_json_payload(json.dumps(payload)) == payload
