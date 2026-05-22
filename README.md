# resume-shortlisting-assistant

A generic, provider-agnostic resume-screening pipeline. Feed it a CSV + a folder
of PDF resumes, get back a ranked shortlist scored against a YAML rubric.

```
ingest → parse → score → rank
```

Built for high-volume hiring where reading every resume by hand isn't feasible.
**This tool produces ranked suggestions, not hiring decisions** — see
[Disclaimer](#disclaimer).

## Why it exists

If your role gets thousands of applicants and your ATS can't help, you have
three options: hire someone to skim resumes, build a one-off script, or use a
black-box AI screener you don't trust. This is the middle option, productized:

- **Bring-your-own ingestion.** Anything that can produce a `candidates.csv` +
  a directory of PDFs works. No scraping in this repo.
- **Bring-your-own rubric.** You write the YAML. Knockouts + weighted criteria.
- **Bring-your-own provider.** Claude, OpenAI, local Qwen, or your Claude Code
  subscription via the CLI.
- **Resumable.** SQLite manifest tracks each candidate's stage. Re-run safely.
- **Inspectable.** Every per-criterion score has a 2-line reasoning string.

## Install

```bash
pip install resume-shortlisting-assistant
```

Or from source:

```bash
git clone https://github.com/<org>/resume-shortlisting-assistant.git
cd resume-shortlisting-assistant
pip install -e ".[dev]"
```

## Quick start

```bash
# 1. Get your candidates into the contract layout (see "Ingestion contract" below).
# 2. Author or pick a rubric (see examples/rubrics/).
# 3. Run the pipeline:
export ANTHROPIC_API_KEY=sk-ant-...

resume-shortlist run \
    --role backend-may2026 \
    --csv path/to/candidates.csv \
    --resumes-dir path/to/resumes/ \
    --rubric examples/rubrics/backend-engineer.yaml \
    --jd examples/jd-backend-engineer.txt \
    --provider claude --top 50
```

Output lands in `./backend-may2026/`:

```
backend-may2026/
  manifest.sqlite          # per-candidate state (resumable)
  candidates.csv           # copy of your input
  resumes/<id>.pdf         # input PDFs
  resumes/<id>.txt         # extracted text
  scores/<id>.json         # per-criterion scores + reasoning
  ranked.csv               # top N
  ranked_full.csv          # everyone who scored, in order
```

## Ingestion contract

The pipeline's entry point is two files, side by side:

```
<role>/
  candidates.csv
  resumes/<candidate_id>.pdf
```

**CSV columns** (only `candidate_id` is required):

| Column | Required | Notes |
|---|---|---|
| `candidate_id` | yes | Stable unique key; used as the resume filename |
| `name` | no | |
| `headline` | no | |
| `location` | no | |
| `current_title` | no | |
| `current_company` | no | |
| `years_experience` | no | Numeric |
| `top_skills` | no | Semicolon-separated |
| `education` | no | Free text |
| `applied_at` | no | ISO 8601 |
| `source_url` | no | Anywhere your candidate came from |

Unknown columns are tolerated and preserved in the output CSV but ignored by
ingest. Missing PDFs mark the candidate as `no_resume` — they're skipped at
the parse stage rather than failing the run.

## CLI

```
resume-shortlist ingest --role <name> --csv <path> --resumes-dir <path>
resume-shortlist parse  --role <name> [--retry-failed]
resume-shortlist score  --role <name> --rubric <path> --jd <path>
                        [--mode single|two-stage]
                        [--provider claude|claude-code|openai|qwen] [--model <id>]
                        [--knockout-provider ...] [--knockout-model ...]
                        [--retry-failed]
resume-shortlist rank   --role <name> [--top 50]
resume-shortlist run    --role <name> --csv <path> --resumes-dir <path>
                        --rubric <path> --jd <path>
                        [...scoring flags...] [--resume | --new] [--yes]
```

- `--resume` (default) picks up where the last run stopped; `--new` wipes the
  role directory and starts fresh (`--yes` skips the confirmation).
- `--retry-failed` re-queues candidates in terminal failure states.

## Providers

| Provider | Cost (rough) | Setup | Notes |
|---|---|---|---|
| `claude` | API per token | `ANTHROPIC_API_KEY` env | Streaming + tool-use. Prompt caching on the rubric/JD prefix — best per-candidate cost at scale. Default model: `claude-sonnet-4-6`. |
| `claude-code` | Included in Claude Code subscription | Local `claude` CLI installed | Shells out to `claude -p --bare --json-schema ...`. No API key needed. No cross-candidate prompt caching; ~1-2s subprocess overhead. Fine for hundreds, slower than `claude` for thousands. |
| `openai` | API per token | `OPENAI_API_KEY` env | Structured Outputs (`json_schema`, strict mode). Auto-cached on stable prefixes. Default model: `gpt-4o`. |
| `qwen` | Free (local) | Ollama running on `localhost:11434` (override with `OLLAMA_HOST`) | Local Qwen 2.5 via Ollama, JSON-mode output. Quality below Sonnet/GPT-4o; great for knockout passes. |

Adding a new provider is a single subclass — see [`CONTRIBUTING.md`](CONTRIBUTING.md#how-to-add-a-new-llm-provider).

### Two-stage with mixed providers

For thousand-applicant roles, use a cheap knockout pass and reserve the
expensive model for survivors:

```bash
resume-shortlist run --role senior-backend \
    --csv candidates.csv --resumes-dir resumes/ \
    --rubric rubrics/senior-backend.yaml --jd jd.txt \
    --mode two-stage \
    --knockout-provider qwen --knockout-model qwen2.5:7b-instruct \
    --provider claude --model claude-sonnet-4-6
```

## Rubrics

A rubric is YAML with two sections: **knockouts** (hard disqualifiers) and
**criteria** (weighted scoring dimensions, weights summing to 1.0):

```yaml
role: "Backend Engineer"
version: 1
knockouts:
  - id: experience
    description: "At least 4 years of professional backend experience."
criteria:
  - id: backend_depth
    weight: 0.30
    description: "Production experience in a mainstream backend stack..."
  - id: ownership
    weight: 0.20
    description: "Signals of end-to-end ownership..."
  # ...
```

See [`examples/rubrics/`](examples/rubrics/) for three full examples (backend
engineer, QA engineer, customer support).

**Rubric authoring tips:**

- Keep knockouts narrow and job-related. They're binary; one false positive
  loses you a good candidate forever.
- Weights are about *relative importance*, not absolute strength. A weight of
  0.30 means "30% of the final score depends on this criterion."
- Limit yourself to ~5–8 criteria. More than that and the LLM starts thrashing.
- Pair every rubric with a JD. The JD is where you put context the rubric
  doesn't capture (timezone, stack, team culture, current scaling phase).

## Bring-your-own ingestion

The pipeline doesn't care where your `candidates.csv` comes from. Common
sources:

- **Greenhouse / Lever / Workable exports.** Export to CSV from the ATS, then
  rename columns to match the contract above.
- **Email attachments.** A short script that walks a Gmail label, extracts PDF
  attachments + a row per sender.
- **Hand-curated lists.** Open the CSV in a spreadsheet, type rows. For roles
  with <50 applicants this is sometimes fastest.
- **Your own scraper.** If you have a legitimate need to scrape a specific
  source, build it as a separate tool that writes to the contract layout.
  We don't include scrapers in this repo (see [CONTRIBUTING.md](CONTRIBUTING.md)).

A minimal valid CSV is literally one column:

```csv
candidate_id
c001
c002
c003
```

With matching `<resumes-dir>/c001.pdf` etc., the pipeline will still run — the
LLM will see only the resume text.

## Tests

```bash
pytest
```

40+ tests cover CSV ingestion, manifest state transitions, rubric validation,
scoring schemas, and every provider adapter (stubbed — no live API calls).

## Disclaimer

This tool ranks candidates against rubrics you author. The outputs are
**ordered suggestions, not hiring decisions**. A human must review every
candidate before any hiring action. Users are responsible for ensuring their
rubric criteria are job-related and non-discriminatory.

Regulatory context worth knowing:

- **U.S. (federal):** The EEOC has guidance on AI in hiring under Title VII.
  Automated screening tools are still subject to disparate-impact analysis.
- **U.S. (NYC):** Local Law 144 regulates Automated Employment Decision Tools
  used on candidates for jobs in NYC. Bias audits are required.
- **EU:** The EU AI Act classifies AI systems used for recruitment and
  candidate evaluation as "high-risk," with corresponding transparency,
  oversight, and risk-management obligations.
- **EEA/UK:** GDPR/UK-GDPR applies to any personal data processed by the
  pipeline — including candidate metadata and resume contents. Users of this
  tool are the data controllers.

This list isn't legal advice. Talk to your lawyer.

## License

Apache-2.0. See [`LICENSE`](LICENSE) and [`NOTICE`](NOTICE).

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md). PRs welcome — except scrapers.
