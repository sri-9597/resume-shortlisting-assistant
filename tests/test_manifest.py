from __future__ import annotations

from pathlib import Path

from shortlister.storage.manifest import Manifest


def _open(tmp_path: Path) -> Manifest:
    return Manifest(tmp_path / "m.sqlite")


def test_init_meta_persists_ids(tmp_path: Path) -> None:
    m = _open(tmp_path)
    m.init_meta(role="qa", project_id="P1", job_id="J1", source_url="https://x")
    assert m.get_meta("project_id") == "P1"
    assert m.get_meta("job_id") == "J1"
    assert m.get_meta("role") == "qa"
    created = m.get_meta("created_at")
    assert created is not None
    # Re-init must not overwrite created_at
    m.init_meta(role="qa", project_id="P1", job_id="J1", source_url="https://x")
    assert m.get_meta("created_at") == created
    m.close()


def test_upsert_and_stage_progression(tmp_path: Path) -> None:
    m = _open(tmp_path)
    m.upsert_discovered("c1", "https://linkedin.com/talent/profile/x/c1")
    rows = m.candidates_needing_profile()
    assert [r.candidate_id for r in rows] == ["c1"]

    m.mark_profile_scraped("c1", current_title="SDE2", current_company="Acme")
    assert not m.candidates_needing_profile()
    assert m.candidates_needing_resume()[0].candidate_id == "c1"

    m.mark_resume_downloaded("c1")
    assert not m.candidates_needing_resume()
    assert m.candidates_needing_parse()[0].candidate_id == "c1"

    m.mark_resume_parsed("c1")
    assert not m.candidates_needing_parse()
    assert m.candidates_needing_stage1_score()[0].candidate_id == "c1"

    m.mark_stage1_scored("c1", knocked_out=False)
    assert not m.candidates_needing_stage1_score()
    assert m.candidates_needing_stage2_score()[0].candidate_id == "c1"

    m.mark_stage2_scored("c1")
    assert not m.candidates_needing_stage2_score()
    counts = m.status_counts()
    assert counts.get("scored") == 1
    m.close()


def test_knockout_removes_from_stage2_queue(tmp_path: Path) -> None:
    m = _open(tmp_path)
    m.upsert_discovered("c1", "https://x/c1")
    m.mark_profile_scraped("c1", current_title=None, current_company=None)
    m.mark_resume_downloaded("c1")
    m.mark_resume_parsed("c1")
    m.mark_stage1_scored("c1", knocked_out=True)
    assert not m.candidates_needing_stage2_score()
    assert m.status_counts().get("knocked_out") == 1
    m.close()


def test_no_resume_skips_parse_and_score(tmp_path: Path) -> None:
    m = _open(tmp_path)
    m.upsert_discovered("c1", "https://x/c1")
    m.mark_profile_scraped("c1", current_title=None, current_company=None)
    m.mark_no_resume("c1")
    assert not m.candidates_needing_resume()
    assert not m.candidates_needing_parse()
    assert not m.candidates_needing_stage1_score()
    m.close()


def test_retry_failed_resets_terminal_statuses(tmp_path: Path) -> None:
    m = _open(tmp_path)
    m.upsert_discovered("c1", "https://x/c1")
    m.mark_failed("c1", status="failed_scrape", error="boom")
    assert m.status_counts().get("failed_scrape") == 1
    n = m.clear_failures_for_retry()
    assert n == 1
    assert m.status_counts().get("discovered") == 1
    m.close()
