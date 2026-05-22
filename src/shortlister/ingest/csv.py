"""CSV-based ingestion for the resume-screening pipeline.

This is the generic alternative to scraping: any process that can produce a
candidates.csv matching the expected schema + a directory of resume PDFs named
`<candidate_id>.pdf` can feed the pipeline through this module.
"""
from __future__ import annotations

import csv
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from ..logging import get_logger
from ..storage.layout import RoleLayout
from ..storage.manifest import Manifest

log = get_logger(__name__)


REQUIRED_COLUMNS: tuple[str, ...] = ("candidate_id",)

OPTIONAL_COLUMNS: tuple[str, ...] = (
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
)

EXPECTED_COLUMNS: tuple[str, ...] = REQUIRED_COLUMNS + OPTIONAL_COLUMNS


class IngestError(Exception):
    """Raised when the input CSV is malformed in a way ingest cannot recover from."""


@dataclass
class IngestSummary:
    ingested: int = 0
    with_resume: int = 0
    without_resume: int = 0
    duplicates_skipped: int = 0
    unknown_columns: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "ingested": self.ingested,
            "with_resume": self.with_resume,
            "without_resume": self.without_resume,
            "duplicates_skipped": self.duplicates_skipped,
            "unknown_columns": list(self.unknown_columns),
        }


def ingest_from_csv(
    layout: RoleLayout,
    manifest: Manifest,
    csv_path: Path,
    resumes_dir: Path,
) -> dict:
    """Seed the manifest from an external candidates.csv and resume directory.

    Copies the CSV into `<role>/candidates.csv` (if not already there) and each
    `<candidate_id>.pdf` into `<role>/resumes/`. Re-running with the same input
    is idempotent — rows are upserted by `candidate_id`.
    """
    csv_path = Path(csv_path)
    resumes_dir = Path(resumes_dir)
    if not csv_path.exists():
        raise IngestError(f"CSV not found: {csv_path}")
    if not resumes_dir.exists() or not resumes_dir.is_dir():
        raise IngestError(f"Resumes directory not found or not a directory: {resumes_dir}")

    layout.ensure_dirs()

    summary = IngestSummary()
    seen_ids: set[str] = set()

    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise IngestError(f"CSV has no header row: {csv_path}")

        missing_required = [c for c in REQUIRED_COLUMNS if c not in reader.fieldnames]
        if missing_required:
            raise IngestError(
                f"CSV missing required column(s): {missing_required}. "
                f"Found columns: {list(reader.fieldnames)}"
            )

        summary.unknown_columns = [c for c in reader.fieldnames if c not in EXPECTED_COLUMNS]
        if summary.unknown_columns:
            log.warning(
                "CSV has unknown columns (preserved in candidates.csv but ignored by ingest): %s",
                summary.unknown_columns,
            )

        for row_idx, row in enumerate(reader, start=2):  # row 1 is the header
            candidate_id = (row.get("candidate_id") or "").strip()
            if not candidate_id:
                log.warning("Row %d has empty candidate_id; skipping", row_idx)
                continue

            if candidate_id in seen_ids:
                log.warning("Row %d has duplicate candidate_id=%s; skipping", row_idx, candidate_id)
                summary.duplicates_skipped += 1
                continue
            seen_ids.add(candidate_id)

            source_url = (row.get("source_url") or "").strip()
            current_title = (row.get("current_title") or "").strip() or None
            current_company = (row.get("current_company") or "").strip() or None

            manifest.upsert_discovered(candidate_id, source_url)
            manifest.mark_profile_scraped(
                candidate_id,
                current_title=current_title,
                current_company=current_company,
            )

            source_pdf = resumes_dir / f"{candidate_id}.pdf"
            target_pdf = layout.resume_pdf(candidate_id)

            if source_pdf.exists():
                try:
                    same_file = source_pdf.resolve() == target_pdf.resolve()
                except OSError:
                    same_file = False
                if not same_file:
                    shutil.copy2(source_pdf, target_pdf)
                manifest.mark_resume_downloaded(candidate_id)
                summary.with_resume += 1
            else:
                manifest.mark_no_resume(candidate_id)
                summary.without_resume += 1
                log.warning(
                    "No resume PDF for candidate_id=%s (expected at %s)",
                    candidate_id, source_pdf,
                )

            summary.ingested += 1

    try:
        same_csv = csv_path.resolve() == layout.candidates_csv.resolve()
    except OSError:
        same_csv = False
    if not same_csv:
        shutil.copy2(csv_path, layout.candidates_csv)

    return summary.as_dict()
