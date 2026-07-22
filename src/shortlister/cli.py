from __future__ import annotations

import asyncio
import shutil
import sys
from pathlib import Path
from typing import Optional

import typer

from .config import (
    DEFAULT_ANTHROPIC_KNOCKOUT_MODEL,
    DEFAULT_ANTHROPIC_MODEL,
    DEFAULT_OPENAI_KNOCKOUT_MODEL,
    DEFAULT_OPENAI_MODEL,
    DEFAULT_QWEN_KNOCKOUT_MODEL,
    DEFAULT_QWEN_MODEL,
    DEFAULT_SCORE_CONCURRENCY,
    RuntimeConfig,
)
from .logging import get_logger, setup_logging
from .ingest.csv import IngestError, ingest_from_csv
from .parsing.pdf import run_parse
from .scoring.pipeline import load_jd, run_scoring
from .scoring.providers.anthropic import AnthropicProvider
from .scoring.providers.base import LLMProvider
from .scoring.providers.claude_code import DEFAULT_CLAUDE_CODE_MODEL, ClaudeCodeProvider
from .scoring.providers.openai import OpenAIProvider
from .scoring.providers.qwen import QwenProvider
from .scoring.ranking import rank as run_rank
from .scoring.rubric import load_rubric
from .storage.layout import layout_for
from .storage.manifest import Manifest

log = get_logger(__name__)

app = typer.Typer(no_args_is_help=True, add_completion=False)


def _print_summary(prefix: str, summary: dict) -> None:
    typer.echo(prefix + " " + ", ".join(f"{k}={v}" for k, v in summary.items()))


def _make_provider(
    name: str,
    model: str | None,
    runtime: RuntimeConfig,
    *,
    qwen_thinking: bool = False,
) -> LLMProvider:
    name = name.lower()
    if name == "claude":
        return AnthropicProvider(api_key=runtime.anthropic_api_key, model=model or DEFAULT_ANTHROPIC_MODEL)
    if name == "claude-code":
        return ClaudeCodeProvider(model=model or DEFAULT_CLAUDE_CODE_MODEL)
    if name == "openai":
        return OpenAIProvider(api_key=runtime.openai_api_key, model=model or DEFAULT_OPENAI_MODEL)
    if name == "qwen":
        return QwenProvider(
            base_url=runtime.ollama_base_url,
            model=model or DEFAULT_QWEN_MODEL,
            disable_thinking=not qwen_thinking,
        )
    raise typer.BadParameter(
        f"Unknown provider: {name!r} (expected 'claude', 'claude-code', 'openai', or 'qwen')"
    )


@app.callback()
def _main(verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose logging.")) -> None:
    setup_logging(verbose=verbose)


# ----------------------- ingest -----------------------
@app.command()
def ingest(
    role: str = typer.Option(..., "--role", help="Role slug, used as the output directory name."),
    csv: Path = typer.Option(..., "--csv", exists=True, dir_okay=False, readable=True, help="Path to a candidates.csv conforming to the ingestion schema."),
    resumes_dir: Path = typer.Option(..., "--resumes-dir", exists=True, file_okay=False, readable=True, help="Directory containing <candidate_id>.pdf files."),
) -> None:
    """Seed the manifest for ROLE from an external candidates.csv + resumes directory."""
    layout = layout_for(role)
    layout.ensure_dirs()
    manifest = Manifest(layout.manifest_path)
    try:
        try:
            summary = ingest_from_csv(layout, manifest, csv, resumes_dir)
        except IngestError as e:
            typer.echo(f"Ingest failed: {e}", err=True)
            raise typer.Exit(code=1)
    finally:
        manifest.close()
    _print_summary("Ingest:", summary)
    _print_status(layout)


# ----------------------- parse -----------------------
@app.command()
def parse(
    role: str = typer.Option(..., "--role"),
    retry_failed: bool = typer.Option(False, "--retry-failed"),
) -> None:
    """Extract text from downloaded resume PDFs for ROLE."""
    layout = layout_for(role)
    layout.ensure_dirs()
    manifest = Manifest(layout.manifest_path)
    try:
        if retry_failed:
            n = manifest.clear_failures_for_retry()
            typer.echo(f"Re-queued {n} previously-failed candidates.")
        summary = run_parse(layout, manifest)
    finally:
        manifest.close()
    _print_summary("Parse:", summary)
    _print_status(layout)


# ----------------------- score -----------------------
@app.command()
def score(
    role: str = typer.Option(..., "--role"),
    rubric: Path = typer.Option(..., "--rubric", exists=True, dir_okay=False, readable=True),
    jd: Path = typer.Option(..., "--jd", exists=True, dir_okay=False, readable=True),
    mode: str = typer.Option("single", "--mode", help="single | two-stage"),
    provider: str = typer.Option("claude", "--provider", help="claude | claude-code | openai | qwen"),
    model: Optional[str] = typer.Option(None, "--model"),
    knockout_provider: Optional[str] = typer.Option(None, "--knockout-provider"),
    knockout_model: Optional[str] = typer.Option(None, "--knockout-model"),
    qwen_thinking: bool = typer.Option(
        False,
        "--qwen-thinking/--no-qwen-thinking",
        help="For qwen only. Default (--no-qwen-thinking) sends think:false to suppress the "
        "reasoning preamble that would corrupt JSON-mode output on thinking models like qwen3. "
        "Pass --qwen-thinking for non-thinking models (e.g. qwen2.5) that reject the field.",
    ),
    concurrency: int = typer.Option(
        DEFAULT_SCORE_CONCURRENCY,
        "--concurrency",
        min=1,
        help="Number of candidates to score concurrently per stage. For local Ollama, "
        "also set OLLAMA_NUM_PARALLEL to the same value so the server serves them in parallel.",
    ),
    retry_failed: bool = typer.Option(False, "--retry-failed"),
) -> None:
    """Score parsed candidates against RUBRIC + JD using PROVIDER."""
    if mode not in ("single", "two-stage"):
        raise typer.BadParameter("--mode must be 'single' or 'two-stage'")
    runtime = RuntimeConfig.from_env()
    layout = layout_for(role)
    layout.ensure_dirs()
    manifest = Manifest(layout.manifest_path)
    try:
        if retry_failed:
            n = manifest.clear_failures_for_retry()
            typer.echo(f"Re-queued {n} previously-failed candidates.")
        loaded_rubric = load_rubric(rubric)
        jd_text = load_jd(jd)
        full_provider = _make_provider(provider, model, runtime, qwen_thinking=qwen_thinking)
        ko_provider: LLMProvider | None = None
        if mode == "two-stage":
            ko_name = knockout_provider or provider
            ko_model = knockout_model
            if ko_model is None and ko_name.lower() == "claude":
                ko_model = DEFAULT_ANTHROPIC_KNOCKOUT_MODEL
            if ko_model is None and ko_name.lower() == "openai":
                ko_model = DEFAULT_OPENAI_KNOCKOUT_MODEL
            if ko_model is None and ko_name.lower() == "qwen":
                ko_model = DEFAULT_QWEN_KNOCKOUT_MODEL
            ko_provider = _make_provider(ko_name, ko_model, runtime, qwen_thinking=qwen_thinking)
        summary = asyncio.run(
            run_scoring(
                layout,
                manifest,
                rubric=loaded_rubric,
                jd_text=jd_text,
                mode=mode,  # type: ignore[arg-type]
                full_provider=full_provider,
                knockout_provider=ko_provider,
                concurrency=concurrency,
            )
        )
    finally:
        manifest.close()
    _print_summary("Score:", summary)
    _print_status(layout)


# ----------------------- rank -----------------------
@app.command()
def rank(
    role: str = typer.Option(..., "--role"),
    top: int = typer.Option(50, "--top", min=1),
) -> None:
    """Write ranked.csv (top N) and ranked_full.csv for ROLE."""
    layout = layout_for(role)
    layout.ensure_dirs()
    manifest = Manifest(layout.manifest_path)
    try:
        summary = run_rank(layout, manifest, top_n=top)
    finally:
        manifest.close()
    _print_summary("Rank:", summary)
    typer.echo(f"Wrote {layout.ranked_csv} and {layout.ranked_full_csv}")


# ----------------------- run -----------------------
@app.command(name="run")
def run(
    role: str = typer.Option(..., "--role"),
    csv: Optional[Path] = typer.Option(None, "--csv", exists=True, dir_okay=False, readable=True, help="candidates.csv path (required when starting fresh)."),
    resumes_dir: Optional[Path] = typer.Option(None, "--resumes-dir", exists=True, file_okay=False, readable=True, help="Directory of <candidate_id>.pdf files (required when starting fresh)."),
    rubric: Path = typer.Option(..., "--rubric", exists=True, dir_okay=False, readable=True),
    jd: Path = typer.Option(..., "--jd", exists=True, dir_okay=False, readable=True),
    mode: str = typer.Option("single", "--mode"),
    provider: str = typer.Option("claude", "--provider", help="claude | claude-code | openai | qwen"),
    model: Optional[str] = typer.Option(None, "--model"),
    knockout_provider: Optional[str] = typer.Option(None, "--knockout-provider"),
    knockout_model: Optional[str] = typer.Option(None, "--knockout-model"),
    qwen_thinking: bool = typer.Option(
        False,
        "--qwen-thinking/--no-qwen-thinking",
        help="For qwen only. Default (--no-qwen-thinking) sends think:false to suppress the "
        "reasoning preamble that would corrupt JSON-mode output on thinking models like qwen3. "
        "Pass --qwen-thinking for non-thinking models (e.g. qwen2.5) that reject the field.",
    ),
    concurrency: int = typer.Option(
        DEFAULT_SCORE_CONCURRENCY,
        "--concurrency",
        min=1,
        help="Number of candidates to score concurrently per stage. For local Ollama, "
        "also set OLLAMA_NUM_PARALLEL to the same value so the server serves them in parallel.",
    ),
    top: int = typer.Option(50, "--top", min=1),
    resume: bool = typer.Option(True, "--resume/--new", help="Resume from manifest (default) or start fresh."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation when --new wipes the role dir."),
) -> None:
    """Run ingest → parse → score → rank end-to-end, non-interactively."""
    layout = layout_for(role)
    starting_fresh = not resume

    if not starting_fresh and not layout.manifest_path.exists():
        typer.echo(f"No existing manifest at {layout.manifest_path}; falling back to --new behavior.")
        starting_fresh = True

    if starting_fresh and layout.root.exists():
        if not yes:
            confirm = typer.confirm(
                f"--new will delete the existing directory {layout.root}. Continue?",
                default=False,
            )
            if not confirm:
                typer.echo("Aborted.")
                raise typer.Exit(code=1)
        shutil.rmtree(layout.root)

    if starting_fresh and (csv is None or resumes_dir is None):
        raise typer.BadParameter(
            "--csv and --resumes-dir are required when starting fresh "
            "(or use --resume with an existing manifest)."
        )

    layout.ensure_dirs()
    runtime = RuntimeConfig.from_env()
    manifest = Manifest(layout.manifest_path)

    try:
        if starting_fresh:
            typer.echo("=== Stage 1: ingest ===")
            try:
                ingest_summary = ingest_from_csv(layout, manifest, csv, resumes_dir)
            except IngestError as e:
                typer.echo(f"Ingest failed: {e}", err=True)
                raise typer.Exit(code=1)
            _print_summary("Ingest:", ingest_summary)
        else:
            typer.echo("=== Stage 1: ingest (skipped — resuming from existing manifest) ===")

        typer.echo("=== Stage 2: parse ===")
        parse_summary = run_parse(layout, manifest)
        _print_summary("Parse:", parse_summary)

        typer.echo("=== Stage 3: score ===")
        loaded_rubric = load_rubric(rubric)
        jd_text = load_jd(jd)
        full_provider = _make_provider(provider, model, runtime, qwen_thinking=qwen_thinking)
        ko_provider: LLMProvider | None = None
        if mode == "two-stage":
            ko_name = knockout_provider or provider
            ko_model = knockout_model
            if ko_model is None and ko_name.lower() == "claude":
                ko_model = DEFAULT_ANTHROPIC_KNOCKOUT_MODEL
            if ko_model is None and ko_name.lower() == "openai":
                ko_model = DEFAULT_OPENAI_KNOCKOUT_MODEL
            if ko_model is None and ko_name.lower() == "qwen":
                ko_model = DEFAULT_QWEN_KNOCKOUT_MODEL
            ko_provider = _make_provider(ko_name, ko_model, runtime, qwen_thinking=qwen_thinking)
        score_summary = asyncio.run(
            run_scoring(
                layout,
                manifest,
                rubric=loaded_rubric,
                jd_text=jd_text,
                mode=mode,  # type: ignore[arg-type]
                full_provider=full_provider,
                knockout_provider=ko_provider,
                concurrency=concurrency,
            )
        )
        _print_summary("Score:", score_summary)

        typer.echo("=== Stage 4: rank ===")
        rank_summary = run_rank(layout, manifest, top_n=top)
        _print_summary("Rank:", rank_summary)
        typer.echo(f"Wrote {layout.ranked_csv} and {layout.ranked_full_csv}")
    finally:
        manifest.close()
    _print_status(layout)


# ----------------------- status (utility) -----------------------
def _print_status(layout) -> None:
    manifest = Manifest(layout.manifest_path)
    try:
        counts = manifest.status_counts()
    finally:
        manifest.close()
    if counts:
        typer.echo("Manifest status counts: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))


def main() -> None:
    try:
        app()
    except KeyboardInterrupt:
        typer.echo("Interrupted.", err=True)
        sys.exit(130)


if __name__ == "__main__":
    main()
