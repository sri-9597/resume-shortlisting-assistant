"""Regenerate examples/sample-candidates.csv deterministically.

This script writes a fixed set of fake candidates to `sample-candidates.csv`.
It does NOT generate PDF resumes — drop your own PDFs (one per candidate_id)
into `examples/sample-resumes/` to test the full pipeline.

Usage:
    python examples/make_samples.py
"""
from __future__ import annotations

import csv
from pathlib import Path

OUTPUT_PATH = Path(__file__).parent / "sample-candidates.csv"


COLUMNS = [
    "candidate_id",
    "name",
    "headline",
    "location",
    "current_title",
    "current_company",
    "years_experience",
    "top_skills",
    "education",
    "applied_at",
    "source_url",
]


# Stable fake fixtures. Names are intentionally placeholder-style.
# Companies are well-known fictional companies (Hooli, Pied Piper, etc.) to
# signal "not a real person" at a glance.
SAMPLES = [
    {
        "candidate_id": "c001",
        "name": "Alex Backend",
        "headline": "Senior backend engineer | distributed systems",
        "location": "Remote (EU)",
        "current_title": "Senior Software Engineer",
        "current_company": "Globex Corp",
        "years_experience": 8,
        "top_skills": "Java;Spring;Kafka;PostgreSQL;AWS",
        "education": "BSc Computer Science",
        "applied_at": "2026-05-01",
        "source_url": "https://example.invalid/c001",
    },
    {
        "candidate_id": "c002",
        "name": "Sam Newgrad",
        "headline": "Junior dev looking for first role",
        "location": "Remote (US)",
        "current_title": "Intern",
        "current_company": "University Lab",
        "years_experience": 1,
        "top_skills": "Python;Flask;Git",
        "education": "BSc Computer Science (2025)",
        "applied_at": "2026-05-02",
        "source_url": "https://example.invalid/c002",
    },
    {
        "candidate_id": "c003",
        "name": "Riley QA",
        "headline": "QA automation engineer | Playwright + Pytest",
        "location": "Remote (LATAM)",
        "current_title": "Senior QA Engineer",
        "current_company": "Initech",
        "years_experience": 6,
        "top_skills": "Playwright;Pytest;CI/CD;Selenium;TypeScript",
        "education": "BSc Information Systems",
        "applied_at": "2026-05-03",
        "source_url": "https://example.invalid/c003",
    },
    {
        "candidate_id": "c004",
        "name": "Casey Manual",
        "headline": "Manual QA specialist | 8 years exploratory testing",
        "location": "Remote (APAC)",
        "current_title": "QA Analyst",
        "current_company": "Hooli",
        "years_experience": 8,
        "top_skills": "Manual Testing;TestRail;JIRA;Exploratory Testing",
        "education": "Diploma in IT",
        "applied_at": "2026-05-04",
        "source_url": "https://example.invalid/c004",
    },
    {
        "candidate_id": "c005",
        "name": "Jordan Support",
        "headline": "Customer Success Specialist | SaaS B2B",
        "location": "Remote (US)",
        "current_title": "Senior Support Engineer",
        "current_company": "Acme SaaS",
        "years_experience": 5,
        "top_skills": "Zendesk;Intercom;SQL;API Troubleshooting;Help Docs",
        "education": "BA Communications",
        "applied_at": "2026-05-05",
        "source_url": "https://example.invalid/c005",
    },
    {
        "candidate_id": "c006",
        "name": "Morgan Frontend",
        "headline": "Frontend engineer pivoting to fullstack",
        "location": "Remote (EU)",
        "current_title": "Frontend Engineer",
        "current_company": "Pied Piper",
        "years_experience": 4,
        "top_skills": "React;TypeScript;Next.js;Node.js;GraphQL",
        "education": "BSc Software Engineering",
        "applied_at": "2026-05-06",
        "source_url": "https://example.invalid/c006",
    },
    {
        "candidate_id": "c007",
        "name": "Taylor Polyglot",
        "headline": "Generalist engineer | backend + infra + frontend",
        "location": "Remote (Canada)",
        "current_title": "Staff Engineer",
        "current_company": "Stark Industries",
        "years_experience": 12,
        "top_skills": "Go;Python;Kubernetes;Terraform;PostgreSQL",
        "education": "MSc Computer Science",
        "applied_at": "2026-05-07",
        "source_url": "https://example.invalid/c007",
    },
    {
        "candidate_id": "c008",
        "name": "Drew NoResume",
        "headline": "Backend engineer (resume attachment pending)",
        "location": "Remote (UK)",
        "current_title": "Software Engineer",
        "current_company": "Wayne Enterprises",
        "years_experience": 6,
        "top_skills": "Node.js;TypeScript;MongoDB;Docker;CI/CD",
        "education": "BSc Computer Science",
        "applied_at": "2026-05-08",
        "source_url": "https://example.invalid/c008",
    },
]


def main() -> None:
    with OUTPUT_PATH.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        for row in SAMPLES:
            writer.writerow(row)
    print(f"Wrote {len(SAMPLES)} rows to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
