from __future__ import annotations

import csv
from pathlib import Path

import pytest

from shortlister.ingest.csv import IngestError, ingest_from_csv
from shortlister.storage.layout import RoleLayout
from shortlister.storage.manifest import Manifest


# ---------- helpers ----------

def _make_layout(tmp_path: Path) -> RoleLayout:
    layout = RoleLayout(role="senior-sde", root=tmp_path / "senior-sde")
    layout.ensure_dirs()
    return layout


def _open_manifest(layout: RoleLayout) -> Manifest:
    return Manifest(layout.manifest_path)


def _write_csv(path: Path, rows: list[dict], fieldnames: list[str] | None = None) -> None:
    if fieldnames is None:
        fieldnames = list(rows[0].keys()) if rows else ["candidate_id"]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)


def _make_pdf(path: Path, content: bytes = b"%PDF-1.4 fake\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


# ---------- tests ----------

def test_happy_path_all_candidates_with_resumes(tmp_path: Path) -> None:
    layout = _make_layout(tmp_path)
    src_csv = tmp_path / "input.csv"
    src_resumes = tmp_path / "input_resumes"
    src_resumes.mkdir()

    _write_csv(src_csv, [
        {"candidate_id": "c1", "current_title": "SDE2", "current_company": "Acme", "source_url": "https://example/c1"},
        {"candidate_id": "c2", "current_title": "QA Lead", "current_company": "Beta", "source_url": "https://example/c2"},
    ])
    _make_pdf(src_resumes / "c1.pdf")
    _make_pdf(src_resumes / "c2.pdf")

    manifest = _open_manifest(layout)
    try:
        summary = ingest_from_csv(layout, manifest, src_csv, src_resumes)
        assert summary["ingested"] == 2
        assert summary["with_resume"] == 2
        assert summary["without_resume"] == 0
        assert summary["duplicates_skipped"] == 0

        # PDFs copied into layout
        assert (layout.resumes_dir / "c1.pdf").exists()
        assert (layout.resumes_dir / "c2.pdf").exists()
        # CSV copied
        assert layout.candidates_csv.exists()

        # Manifest state
        counts = manifest.status_counts()
        assert counts.get("ok", 0) == 2
        # Nothing left to scrape; everything ready for parse
        assert not manifest.candidates_needing_profile()
        assert not manifest.candidates_needing_resume()
        parse_queue = manifest.candidates_needing_parse()
        assert sorted(r.candidate_id for r in parse_queue) == ["c1", "c2"]
    finally:
        manifest.close()


def test_missing_pdf_marks_no_resume(tmp_path: Path) -> None:
    layout = _make_layout(tmp_path)
    src_csv = tmp_path / "input.csv"
    src_resumes = tmp_path / "input_resumes"
    src_resumes.mkdir()

    _write_csv(src_csv, [
        {"candidate_id": "c1", "current_title": "SDE", "current_company": "X"},
        {"candidate_id": "c2", "current_title": "PM", "current_company": "Y"},
    ])
    _make_pdf(src_resumes / "c1.pdf")
    # c2.pdf intentionally absent

    manifest = _open_manifest(layout)
    try:
        summary = ingest_from_csv(layout, manifest, src_csv, src_resumes)
        assert summary["with_resume"] == 1
        assert summary["without_resume"] == 1

        counts = manifest.status_counts()
        assert counts.get("ok", 0) == 1
        assert counts.get("no_resume", 0) == 1
    finally:
        manifest.close()


def test_missing_required_column_raises(tmp_path: Path) -> None:
    layout = _make_layout(tmp_path)
    src_csv = tmp_path / "input.csv"
    src_resumes = tmp_path / "input_resumes"
    src_resumes.mkdir()

    # CSV without candidate_id column
    _write_csv(src_csv, [{"name": "Alice", "current_title": "SDE"}])

    manifest = _open_manifest(layout)
    try:
        with pytest.raises(IngestError, match="candidate_id"):
            ingest_from_csv(layout, manifest, src_csv, src_resumes)
    finally:
        manifest.close()


def test_duplicate_candidate_id_is_skipped(tmp_path: Path) -> None:
    layout = _make_layout(tmp_path)
    src_csv = tmp_path / "input.csv"
    src_resumes = tmp_path / "input_resumes"
    src_resumes.mkdir()

    _write_csv(src_csv, [
        {"candidate_id": "c1", "current_title": "SDE"},
        {"candidate_id": "c1", "current_title": "DUPLICATE"},
        {"candidate_id": "c2", "current_title": "PM"},
    ])
    _make_pdf(src_resumes / "c1.pdf")
    _make_pdf(src_resumes / "c2.pdf")

    manifest = _open_manifest(layout)
    try:
        summary = ingest_from_csv(layout, manifest, src_csv, src_resumes)
        assert summary["ingested"] == 2
        assert summary["duplicates_skipped"] == 1
    finally:
        manifest.close()


def test_csv_not_found_raises(tmp_path: Path) -> None:
    layout = _make_layout(tmp_path)
    src_resumes = tmp_path / "input_resumes"
    src_resumes.mkdir()
    manifest = _open_manifest(layout)
    try:
        with pytest.raises(IngestError, match="CSV not found"):
            ingest_from_csv(layout, manifest, tmp_path / "nope.csv", src_resumes)
    finally:
        manifest.close()


def test_resumes_dir_not_found_raises(tmp_path: Path) -> None:
    layout = _make_layout(tmp_path)
    src_csv = tmp_path / "input.csv"
    _write_csv(src_csv, [{"candidate_id": "c1"}])

    manifest = _open_manifest(layout)
    try:
        with pytest.raises(IngestError, match="Resumes directory not found"):
            ingest_from_csv(layout, manifest, src_csv, tmp_path / "missing_dir")
    finally:
        manifest.close()


def test_idempotent_rerun(tmp_path: Path) -> None:
    layout = _make_layout(tmp_path)
    src_csv = tmp_path / "input.csv"
    src_resumes = tmp_path / "input_resumes"
    src_resumes.mkdir()

    _write_csv(src_csv, [
        {"candidate_id": "c1", "current_title": "SDE"},
        {"candidate_id": "c2", "current_title": "PM"},
    ])
    _make_pdf(src_resumes / "c1.pdf")
    _make_pdf(src_resumes / "c2.pdf")

    manifest = _open_manifest(layout)
    try:
        ingest_from_csv(layout, manifest, src_csv, src_resumes)
        # Second call should not double-count or fail
        summary2 = ingest_from_csv(layout, manifest, src_csv, src_resumes)
        assert summary2["ingested"] == 2

        # Still only two candidates total
        all_rows = manifest.all_candidates()
        assert len(all_rows) == 2
    finally:
        manifest.close()


def test_unknown_columns_logged_but_accepted(tmp_path: Path) -> None:
    layout = _make_layout(tmp_path)
    src_csv = tmp_path / "input.csv"
    src_resumes = tmp_path / "input_resumes"
    src_resumes.mkdir()

    _write_csv(src_csv, [
        {"candidate_id": "c1", "extra_field": "some-value"},
    ])
    _make_pdf(src_resumes / "c1.pdf")

    manifest = _open_manifest(layout)
    try:
        summary = ingest_from_csv(layout, manifest, src_csv, src_resumes)
        assert summary["ingested"] == 1
        assert "extra_field" in summary["unknown_columns"]
    finally:
        manifest.close()


def test_csv_already_at_layout_path_not_overwritten(tmp_path: Path) -> None:
    """If the input CSV path IS the layout's candidates.csv, ingest should not
    try to copy it onto itself (which would either error or no-op)."""
    layout = _make_layout(tmp_path)
    src_resumes = tmp_path / "input_resumes"
    src_resumes.mkdir()

    _write_csv(layout.candidates_csv, [{"candidate_id": "c1"}])
    _make_pdf(src_resumes / "c1.pdf")

    manifest = _open_manifest(layout)
    try:
        summary = ingest_from_csv(layout, manifest, layout.candidates_csv, src_resumes)
        assert summary["ingested"] == 1
        assert layout.candidates_csv.exists()
    finally:
        manifest.close()
