# Contributing

Thanks for considering a contribution. This project is small and intentionally
scoped — please read this guide before opening a PR.

## Project scope

`resume-shortlisting-assistant` is a generic resume-screening pipeline:

```
ingest → parse → score → rank
```

It takes a `candidates.csv` + a directory of resume PDFs as input. **It does
not include any data-collection mechanism** — see "No scrapers in this repo"
below.

## No scrapers in this repo

Pull requests that add web scraping, browser automation (Playwright, Selenium,
Puppeteer, etc.), or any other code whose purpose is to collect candidate data
from third-party services will be closed without review.

This is a deliberate boundary, not a hostile one. Reasons:

- Most candidate-data sources (LinkedIn, Indeed, etc.) have terms of service
  that prohibit scraping. Including such code here would taint the rest of the
  project for downstream users.
- We want the public surface area to be the *processing* pipeline. Ingestion
  is up to you — write a script that exports from your ATS, parse an email
  attachment, type the CSV by hand, whatever. We accept any conforming input.
- Different scraping needs deserve different repos with different risk
  profiles. We won't be that repo.

If you want to share an ingestion helper that *imports* this package and
writes the contract layout, please publish it as a separate repository.

## What we welcome

- **New LLM providers.** Adding OpenAI / Anthropic / Qwen / etc. taught us that
  the `LLMProvider` ABC is the right abstraction. Adding Mistral, Gemini,
  Together, etc. is straightforward.
- **Rubric authoring tools.** Validators, linters, weight-rebalancers, schema
  upgraders.
- **PDF-parsing improvements.** Layout-aware extraction, table support,
  signature handling, etc.
- **Documentation.** Rubric design patterns, regulatory references, BYO-ingestion
  recipes for specific ATSes.
- **Performance / cost.** Smarter batching, better prompt caching strategies,
  observability around per-candidate cost and latency.
- **Bias / fairness tooling.** Helpers to compare score distributions across
  self-reported demographics on a holdout set. This is a real gap.

## How to add a new LLM provider

1. Create `src/shortlister/scoring/providers/<name>.py`.
2. Subclass `LLMProvider` (from `.base`).
3. Implement `async def score(self, *, system, cacheable_prefix, candidate_block, output_schema, tool_name, tool_description) -> dict`. The returned dict must conform to `output_schema`.
4. Wire the retry loop using `LLM_RETRY_DELAYS_SECONDS` from `shortlister.config` so retries are consistent across providers.
5. Register the provider in `cli._make_provider` and add it to the `--provider` help text in the `score` and `run` commands.
6. Add `DEFAULT_<NAME>_MODEL` (and `DEFAULT_<NAME>_KNOCKOUT_MODEL` if applicable) to `config.py`.
7. Read any API key from env via `RuntimeConfig.from_env()` — don't read env vars from inside the provider.
8. Write tests in `tests/test_<name>_provider.py`. Mirror the structure of `test_anthropic_provider.py` or `test_openai_provider.py`. Stub the network — **no live API calls in tests**.

Patch `LLM_RETRY_DELAYS_SECONDS` to `(0.0, 0.0, 0.0)` in retry-path tests so they don't sleep.

## Code style

- Black / ruff defaults. We don't run a formatter in CI yet, but match the
  surrounding style.
- Type hints required on new public APIs.
- No comments that just restate what the code does. Comments are for the *why*.
- Tests use `pytest`, `pytest-asyncio` (auto-mode), and `tmp_path` for fixtures.
  See existing tests for the pattern.

## PR conventions

- Small, focused PRs. One feature or one fix per PR.
- Include tests. PRs without tests for new behavior will be asked for tests.
- Update `README.md` if you change a CLI surface.
- Update `CLAUDE.md` if you change the project's high-level architecture.
- For new third-party dependencies, add an attribution line to `NOTICE`.

## Data hygiene

**Never commit real candidate data.** The repo has a CI guard that should block
this, but please don't rely on it. The role-output directories (`<role>/`),
all `*.pdf` files outside `examples/sample-resumes/`, and `manifest.sqlite`
are gitignored. If you find a gap in the `.gitignore`, send a PR.

## Disclaimer reminder

If your contribution touches the scoring or ranking surface, please remember
this tool produces *suggestions for human reviewers*, not autonomous hiring
decisions. The README disclaimer covers EEOC, EU AI Act, and NYC Local Law
144 considerations — please don't introduce features that meaningfully change
that framing without discussion first.
