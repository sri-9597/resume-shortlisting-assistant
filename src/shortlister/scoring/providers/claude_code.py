from __future__ import annotations

import asyncio
import json
import re
import shutil
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

        args = [
            self.binary,
            "-p",
            "--bare",
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

        if proc.returncode != 0:
            tail = (stderr_b or b"").decode("utf-8", errors="replace")[-1000:]
            raise RuntimeError(f"claude returned exit {proc.returncode}: {tail}")

        stdout = stdout_b.decode("utf-8", errors="replace").strip()
        return _extract_json_payload(stdout)


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
