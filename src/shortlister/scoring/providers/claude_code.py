from __future__ import annotations

import asyncio
import json
import re
import shutil
import tempfile
from typing import Any

from ...config import LLM_RETRY_DELAYS_SECONDS
from ...logging import get_logger
from .base import LLMProvider

log = get_logger(__name__)


# Default model alias passed to `claude -p`. Aliases the CLI accepts include
# "sonnet", "opus", "haiku", or full IDs like "claude-sonnet-4-6".
DEFAULT_CLAUDE_CODE_MODEL = "sonnet"

# Per-process timeout. Resume scoring tends to take 5-20s; 180s is generous headroom.
CLAUDE_CODE_TIMEOUT_SECONDS = 180.0


_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def _strip_fences(text: str) -> str:
    return _FENCE_RE.sub("", text).strip()


class ClaudeCodeProvider(LLMProvider):
    """Score candidates by shelling out to the local `claude -p` (Claude Code) CLI.

    Uses the user's Claude Code subscription (not the API), so no ANTHROPIC_API_KEY
    is required. Tool-use is disabled and `--json-schema` enforces structured output.

    Trade-offs vs. AnthropicProvider:
      - No prompt-caching across candidates — the rubric/JD prefix is re-tokenized each call.
      - Per-call process startup overhead (~1-2s).
      - Single-process serial execution by default (LinkedIn-side rate limits already cap us).
    """

    name = "claude-code"

    def __init__(
        self,
        *,
        model: str = DEFAULT_CLAUDE_CODE_MODEL,
        binary: str = "claude",
        timeout: float = CLAUDE_CODE_TIMEOUT_SECONDS,
    ) -> None:
        self.model = model
        self.binary = binary
        self.timeout = timeout
        # Run the CLI from a neutral empty directory so it doesn't auto-discover a
        # project CLAUDE.md and inject unrelated instructions into the scoring
        # context. (`--bare` used to suppress that discovery, but it also disabled
        # OAuth/keychain auth, breaking subscription use — so we drop it and
        # isolate the cwd instead.)
        self._cwd = tempfile.mkdtemp(prefix="shortlister-cc-")
        if shutil.which(self.binary) is None:
            log.warning(
                "ClaudeCodeProvider initialized but `%s` is not on PATH. Calls will fail at runtime.",
                self.binary,
            )

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
        # Claude Code's --json-schema enforces the model's *response shape* matches
        # the schema. We still embed the schema textually so the model knows the
        # field semantics; the CLI-side validator is the safety net.
        prompt = (
            f"{cacheable_prefix}\n\n"
            f"--- CANDIDATE ---\n{candidate_block}\n\n"
            "Respond with a single JSON object conforming exactly to the provided schema. "
            "Do not include any prose, markdown, or commentary outside the JSON object."
        )

        # NOTE: no `--bare`. That flag forces API-key-only auth and never reads the
        # OAuth/keychain login the Claude Code *subscription* uses, so under `--bare`
        # a subscription-only user gets "Not logged in" (exit 1). Isolation that
        # `--bare` provided (no CLAUDE.md discovery) is handled by running in
        # `self._cwd`; see __init__.
        args = [
            self.binary,
            "-p",
            "--no-session-persistence",
            "--disable-slash-commands",
            "--tools", "",
            "--output-format", "json",
            "--json-schema", json.dumps(output_schema),
            "--system-prompt", system,
            "--model", self.model,
        ]

        last_err: Exception | None = None
        for attempt, delay in enumerate((0.0,) + LLM_RETRY_DELAYS_SECONDS):
            if delay:
                await asyncio.sleep(delay)
            try:
                return await self._run_once(args, prompt)
            except Exception as e:  # noqa: BLE001
                last_err = e
                log.warning("claude-code call attempt %d failed: %s", attempt + 1, e)
        raise RuntimeError(
            f"claude-code scoring failed after {len(LLM_RETRY_DELAYS_SECONDS) + 1} attempts: {last_err}"
        )

    async def _run_once(self, args: list[str], prompt: str) -> dict:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self._cwd,
        )
        try:
            stdout_b, stderr_b = await asyncio.wait_for(
                proc.communicate(prompt.encode("utf-8")),
                timeout=self.timeout,
            )
        except asyncio.TimeoutError as e:
            proc.kill()
            await proc.wait()
            raise RuntimeError(f"claude-code call timed out after {self.timeout}s") from e

        stdout = stdout_b.decode("utf-8", errors="replace").strip()
        stderr = (stderr_b or b"").decode("utf-8", errors="replace").strip()

        if proc.returncode != 0:
            # The CLI reports some failures (e.g. auth: "Not logged in") in stdout's
            # JSON envelope with an EMPTY stderr, so consult both.
            raise RuntimeError(
                f"claude returned exit {proc.returncode}: {_cli_error_message(stdout, stderr)}"
            )

        return _extract_json_payload(stdout)


def _cli_error_message(stdout: str, stderr: str) -> str:
    """Best-effort human-readable reason for a failed `claude -p` invocation.

    Prefers stderr, then stdout. When the text is a JSON result envelope (the
    common case — the CLI puts auth and API errors in `result` with an empty
    stderr), pull the `result`/`error` message out of it.
    """
    for chunk in (stderr, stdout):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            env = json.loads(chunk)
        except json.JSONDecodeError:
            return chunk[-1000:]
        if isinstance(env, dict):
            msg = env.get("result") or env.get("error")
            return str(msg) if msg else json.dumps(env)[-1000:]
        return chunk[-1000:]
    return "(no output on stdout or stderr)"


def _extract_json_payload(stdout: str) -> dict:
    """Pull the structured scoring object out of `claude -p --output-format json` output.

    The envelope shape is approximately:
      { "type": "result", "subtype": "success", "result": "<model text or object>", ... }

    `result` may be either:
      - a stringified JSON object the model emitted, or
      - already a parsed object (when --json-schema validation is active).

    We handle both. We also tolerate the model wrapping its JSON in ```json fences.
    """
    try:
        envelope: Any = json.loads(stdout)
    except json.JSONDecodeError as e:
        # Some CLI errors print text before the JSON envelope; try to grab the last JSON object.
        match = re.search(r"\{.*\}\s*$", stdout, re.DOTALL)
        if not match:
            raise RuntimeError(f"Could not parse claude envelope: {stdout[-500:]!r}") from e
        envelope = json.loads(match.group(0))

    # `is_error` can be True even when `subtype == "success"` (e.g. an auth failure
    # returned on a zero exit), so check it independently of subtype.
    if isinstance(envelope, dict) and envelope.get("is_error"):
        reason = envelope.get("result") or envelope.get("error") or envelope
        raise RuntimeError(f"claude reported an error: {reason}")

    if isinstance(envelope, dict) and envelope.get("type") == "result" and envelope.get("subtype") != "success":
        raise RuntimeError(f"claude returned non-success result: {envelope!r}")

    result = envelope.get("result") if isinstance(envelope, dict) else None
    if result is None:
        # If the envelope wasn't in the expected shape, maybe the whole envelope IS the payload.
        if isinstance(envelope, dict) and "candidate_id" in envelope:
            return envelope
        raise RuntimeError(f"claude envelope missing 'result' field: {envelope!r}")

    if isinstance(result, dict):
        return result
    if isinstance(result, str):
        cleaned = _strip_fences(result)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"Could not parse model JSON output: {cleaned[-500:]!r}") from e
    raise RuntimeError(f"Unexpected 'result' type from claude: {type(result).__name__}")
