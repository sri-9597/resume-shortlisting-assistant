from __future__ import annotations

import json
from pathlib import Path

from shortlister.scoring.ranking import rank
from shortlister.storage.layout import layout_for
from shortlister.storage.manifest import Manifest


def _seed_scored_candidate(
    layout, manifest: Manifest, candidate_id: str, weighted_total: float, *, with_resume: bool = True
) -> None:
    manifest.upsert_discovered(candidate_id, f"https://x/{candidate_id}")
    manifest.mark_profile_scraped(candidate_id, current_title="SDE", current_company="Acme")
    manifest.mark_resume_downloaded(candidate_id)
    manifest.mark_resume_parsed(candidate_id)
    manifest.mark_stage1_scored(candidate_id, knocked_out=False)
    manifest.mark_stage2_scored(candidate_id)

    layout.score_json(candidate_id).write_text(
        json.dumps(
            {
                "candidate_id": candidate_id,
                "weighted_total": weighted_total,
                "recommend": True,
                "summary": f"summary for {candidate_id}",
            }
        ),
        encoding="utf-8",
    )
    if with_resume:
        layout.resume_pdf(candidate_id).write_bytes(b"%PDF-1.4 fake pdf for " + candidate_id.encode())


def test_rank_copies_ranked_resumes_in_order(tmp_path: Path) -> None:
    layout = layout_for("qa", cwd=tmp_path)
    layout.ensure_dirs()
    manifest = Manifest(layout.manifest_path)

    _seed_scored_candidate(layout, manifest, "low", 3.0)
    _seed_scored_candidate(layout, manifest, "high", 9.0)
    _seed_scored_candidate(layout, manifest, "mid", 6.0)

    summary = rank(layout, manifest, top_n=50)
    manifest.close()

    assert summary["ranked"] == 3
    assert summary["resumes_copied"] == 3

    copied = sorted(p.name for p in layout.ranked_resumes_dir.iterdir())
    # Rank order: high (1) > mid (2) > low (3), zero-padded to width 3.
    assert copied == ["001_high.pdf", "002_mid.pdf", "003_low.pdf"]
    assert (layout.ranked_resumes_dir / "001_high.pdf").read_bytes().endswith(b"high")


def test_rank_respects_top_n_for_resume_copy(tmp_path: Path) -> None:
    layout = layout_for("qa", cwd=tmp_path)
    layout.ensure_dirs()
    manifest = Manifest(layout.manifest_path)

    _seed_scored_candidate(layout, manifest, "a", 9.0)
    _seed_scored_candidate(layout, manifest, "b", 8.0)
    _seed_scored_candidate(layout, manifest, "c", 7.0)

    summary = rank(layout, manifest, top_n=2)
    manifest.close()

    assert summary["ranked"] == 3
    assert summary["resumes_copied"] == 2
    copied = sorted(p.name for p in layout.ranked_resumes_dir.iterdir())
    assert copied == ["001_a.pdf", "002_b.pdf"]


def test_rank_rebuilds_ranked_resumes_dir(tmp_path: Path) -> None:
    layout = layout_for("qa", cwd=tmp_path)
    layout.ensure_dirs()
    manifest = Manifest(layout.manifest_path)
    _seed_scored_candidate(layout, manifest, "a", 9.0)
    rank(layout, manifest, top_n=50)

    # A stale file from a previous run must not survive a re-rank.
    stale = layout.ranked_resumes_dir / "999_stale.pdf"
    stale.write_bytes(b"stale")

    rank(layout, manifest, top_n=50)
    manifest.close()

    assert not stale.exists()
    assert [p.name for p in layout.ranked_resumes_dir.iterdir()] == ["001_a.pdf"]


def test_rank_tolerates_missing_resume_pdf(tmp_path: Path) -> None:
    layout = layout_for("qa", cwd=tmp_path)
    layout.ensure_dirs()
    manifest = Manifest(layout.manifest_path)
    _seed_scored_candidate(layout, manifest, "has", 9.0, with_resume=True)
    _seed_scored_candidate(layout, manifest, "gone", 8.0, with_resume=False)

    summary = rank(layout, manifest, top_n=50)
    manifest.close()

    assert summary["ranked"] == 2
    assert summary["resumes_copied"] == 1
    assert [p.name for p in layout.ranked_resumes_dir.iterdir()] == ["001_has.pdf"]
