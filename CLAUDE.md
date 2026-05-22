# Project: resume-shortlisting-assistant

A four-stage pipeline that turns a directory of resume PDFs + a candidates CSV
into a ranked shortlist using an LLM scoring rubric.

```
ingest → parse → score → rank
```

## Stages

1. **ingest** — Validates an input `candidates.csv` against the contract schema,
   copies it and the resume PDFs into the role layout, seeds the SQLite manifest.
2. **parse** — Extracts text from each PDF using `pypdf` with a `pdfplumber`
   fallback for tricky layouts.
3. **score** — Runs each candidate through a YAML rubric + JD + system prompt via
   a pluggable LLM backend. Output is structured JSON: per-criterion scores
   (0–10), 2-line reasoning, weighted total, knockouts, recommend flag.
4. **rank** — Computes weighted totals from per-criterion scores, writes
   `ranked.csv` (top N) and `ranked_full.csv` (everyone, in order).

## Ingestion contract

```
<role>/
  candidates.csv          # required input
  resumes/<candidate_id>.pdf
```

The CSV's only required column is `candidate_id`. Optional columns: `name`,
`headline`, `location`, `current_title`, `current_company`, `years_experience`,
`top_skills`, `education`, `applied_at`, `source_url`.

Anything that can produce these two artifacts can feed the pipeline — a manual
collation, a CSV exported from an ATS (Greenhouse, Lever, Workable), or a custom
scraper.

## Providers

Provider-agnostic via `LLMProvider` (`src/shortlister/scoring/providers/base.py`).
Current backends:

- `claude` — Anthropic API, streaming + tool-use, prompt-caching on the rubric/JD prefix.
- `claude-code` — Shells out to local `claude -p` CLI (uses the Claude Code subscription).
- `openai` — OpenAI Structured Outputs (`json_schema` response format, strict mode).
- `qwen` — Local Qwen via Ollama; zero-cost knockout pass.

Adding a new provider is a single subclass — see `CONTRIBUTING.md`.

## Two-stage funnel

`--mode two-stage` runs cheap knockouts on every candidate first, then deep
scoring only on survivors. Useful for cost control at scale. Mix providers:
local Qwen for knockouts, Claude/OpenAI for the scoring pass.

## Layout

```
src/shortlister/
  ingest/csv.py          # CSV → manifest seeding
  parsing/pdf.py         # PDF → text
  scoring/
    rubric.py            # YAML rubric loader + validator
    pipeline.py          # the scoring loop
    ranking.py           # weighted-total computation + CSV output
    providers/
      base.py            # LLMProvider ABC
      anthropic.py
      claude_code.py
      openai.py
      qwen.py
  storage/
    layout.py            # RoleLayout dataclass + path helpers
    manifest.py          # SQLite manifest with resumable stage stamps
  cli.py                 # typer commands: ingest, parse, score, rank, run
  config.py              # constants + RuntimeConfig.from_env()
  logging.py
```

## Key invariants

- Every stage stamps the manifest before moving on — re-running picks up where
  the last invocation stopped.
- Per-candidate failures isolate to that candidate; the batch continues.
- `ingest` is idempotent: re-running with the same CSV upserts by `candidate_id`
  and never wipes downstream state.
- Knockout failures stamp `score_stage1_at` but leave `score_stage2_at` null;
  this is how the manifest distinguishes "knocked out" from "fully scored."

## Disclaimer

This tool produces ranked suggestions, not hiring decisions. A human must
review and decide on every candidate. Rubric authors are responsible for
ensuring their criteria are job-related and non-discriminatory. See the
disclaimer section of the README for regulatory context (EEOC, EU AI Act,
NYC Local Law 144).
