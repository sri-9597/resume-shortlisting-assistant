from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator


CANDIDATE_STATUSES = {
    "discovered",
    "ok",
    "no_resume",
    "knocked_out",
    "scored",
    "failed_scrape",
    "failed_parse",
    "failed_score",
    "unparseable",
}

TERMINAL_FAILURE_STATUSES = {"failed_scrape", "failed_parse", "failed_score", "unparseable"}


SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS candidates (
    candidate_id           TEXT PRIMARY KEY,
    applicant_url          TEXT NOT NULL,
    current_title          TEXT,
    current_company        TEXT,
    profile_scraped_at     TEXT,
    resume_downloaded_at   TEXT,
    resume_parsed_at       TEXT,
    score_stage1_at        TEXT,
    score_stage2_at        TEXT,
    status                 TEXT NOT NULL DEFAULT 'discovered',
    last_error             TEXT,
    created_at             TEXT NOT NULL,
    updated_at             TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_candidates_status ON candidates(status);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class CandidateRow:
    candidate_id: str
    applicant_url: str
    current_title: str | None
    current_company: str | None
    profile_scraped_at: str | None
    resume_downloaded_at: str | None
    resume_parsed_at: str | None
    score_stage1_at: str | None
    score_stage2_at: str | None
    status: str
    last_error: str | None


class Manifest:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        try:
            yield self._conn
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    # ----- meta -----
    def set_meta(self, key: str, value: str) -> None:
        with self.transaction() as c:
            c.execute(
                "INSERT INTO meta(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )

    def get_meta(self, key: str) -> str | None:
        row = self._conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def init_meta(self, *, role: str, project_id: str, job_id: str, source_url: str) -> None:
        if not self.get_meta("created_at"):
            self.set_meta("created_at", _now())
        self.set_meta("role", role)
        self.set_meta("project_id", project_id)
        self.set_meta("job_id", job_id)
        self.set_meta("source_url", source_url)

    # ----- candidates -----
    def upsert_discovered(self, candidate_id: str, applicant_url: str) -> None:
        now = _now()
        with self.transaction() as c:
            c.execute(
                """
                INSERT INTO candidates (candidate_id, applicant_url, status, created_at, updated_at)
                VALUES (?, ?, 'discovered', ?, ?)
                ON CONFLICT(candidate_id) DO UPDATE SET
                    applicant_url = excluded.applicant_url,
                    updated_at    = excluded.updated_at
                """,
                (candidate_id, applicant_url, now, now),
            )

    def mark_profile_scraped(
        self,
        candidate_id: str,
        *,
        current_title: str | None,
        current_company: str | None,
    ) -> None:
        now = _now()
        with self.transaction() as c:
            c.execute(
                """
                UPDATE candidates
                   SET profile_scraped_at = ?,
                       current_title      = ?,
                       current_company    = ?,
                       status             = CASE WHEN status IN ('discovered','failed_scrape') THEN 'ok' ELSE status END,
                       last_error         = NULL,
                       updated_at         = ?
                 WHERE candidate_id = ?
                """,
                (now, current_title, current_company, now, candidate_id),
            )

    def mark_resume_downloaded(self, candidate_id: str) -> None:
        now = _now()
        with self.transaction() as c:
            c.execute(
                "UPDATE candidates SET resume_downloaded_at=?, updated_at=? WHERE candidate_id=?",
                (now, now, candidate_id),
            )

    def mark_no_resume(self, candidate_id: str) -> None:
        now = _now()
        with self.transaction() as c:
            c.execute(
                "UPDATE candidates SET status='no_resume', updated_at=? WHERE candidate_id=?",
                (now, candidate_id),
            )

    def mark_resume_parsed(self, candidate_id: str) -> None:
        now = _now()
        with self.transaction() as c:
            c.execute(
                "UPDATE candidates SET resume_parsed_at=?, updated_at=? WHERE candidate_id=?",
                (now, now, candidate_id),
            )

    def mark_unparseable(self, candidate_id: str) -> None:
        now = _now()
        with self.transaction() as c:
            c.execute(
                "UPDATE candidates SET status='unparseable', updated_at=? WHERE candidate_id=?",
                (now, candidate_id),
            )

    def mark_stage1_scored(self, candidate_id: str, *, knocked_out: bool) -> None:
        now = _now()
        new_status = "knocked_out" if knocked_out else None
        with self.transaction() as c:
            if new_status:
                c.execute(
                    "UPDATE candidates SET score_stage1_at=?, status=?, updated_at=? WHERE candidate_id=?",
                    (now, new_status, now, candidate_id),
                )
            else:
                c.execute(
                    "UPDATE candidates SET score_stage1_at=?, updated_at=? WHERE candidate_id=?",
                    (now, now, candidate_id),
                )

    def mark_stage2_scored(self, candidate_id: str) -> None:
        now = _now()
        with self.transaction() as c:
            c.execute(
                "UPDATE candidates SET score_stage2_at=?, status='scored', updated_at=? WHERE candidate_id=?",
                (now, now, candidate_id),
            )

    def mark_failed(self, candidate_id: str, *, status: str, error: str) -> None:
        assert status in TERMINAL_FAILURE_STATUSES, f"bad failure status {status}"
        now = _now()
        with self.transaction() as c:
            c.execute(
                "UPDATE candidates SET status=?, last_error=?, updated_at=? WHERE candidate_id=?",
                (status, error[:2000], now, candidate_id),
            )

    def clear_failures_for_retry(self) -> int:
        """Reset terminal failures back to 'discovered' so they're re-attempted."""
        now = _now()
        with self.transaction() as c:
            cur = c.execute(
                f"""
                UPDATE candidates
                   SET status='discovered', last_error=NULL, updated_at=?
                 WHERE status IN ({','.join('?' * len(TERMINAL_FAILURE_STATUSES))})
                """,
                (now, *sorted(TERMINAL_FAILURE_STATUSES)),
            )
            return cur.rowcount

    # ----- queries -----
    def candidates_needing_profile(self) -> list[CandidateRow]:
        return self._rows(
            "SELECT * FROM candidates WHERE profile_scraped_at IS NULL "
            "AND status NOT IN ('failed_scrape','failed_parse','failed_score','unparseable','no_resume')"
        )

    def candidates_needing_resume(self) -> list[CandidateRow]:
        return self._rows(
            "SELECT * FROM candidates WHERE profile_scraped_at IS NOT NULL "
            "AND resume_downloaded_at IS NULL "
            "AND status NOT IN ('failed_scrape','failed_parse','failed_score','unparseable','no_resume')"
        )

    def candidates_needing_parse(self) -> list[CandidateRow]:
        return self._rows(
            "SELECT * FROM candidates WHERE resume_downloaded_at IS NOT NULL "
            "AND resume_parsed_at IS NULL "
            "AND status NOT IN ('failed_scrape','failed_parse','failed_score','unparseable','no_resume')"
        )

    def candidates_needing_stage1_score(self) -> list[CandidateRow]:
        return self._rows(
            "SELECT * FROM candidates WHERE resume_parsed_at IS NOT NULL "
            "AND score_stage1_at IS NULL "
            "AND status NOT IN ('failed_scrape','failed_parse','failed_score','unparseable','no_resume','knocked_out')"
        )

    def candidates_needing_stage2_score(self) -> list[CandidateRow]:
        return self._rows(
            "SELECT * FROM candidates WHERE score_stage1_at IS NOT NULL "
            "AND score_stage2_at IS NULL "
            "AND status NOT IN ('failed_scrape','failed_parse','failed_score','unparseable','no_resume','knocked_out')"
        )

    def all_candidates(self) -> list[CandidateRow]:
        return self._rows("SELECT * FROM candidates")

    def status_counts(self) -> dict[str, int]:
        rows = self._conn.execute(
            "SELECT status, COUNT(*) as n FROM candidates GROUP BY status"
        ).fetchall()
        return {r["status"]: r["n"] for r in rows}

    def _rows(self, sql: str, params: tuple = ()) -> list[CandidateRow]:
        rows = self._conn.execute(sql, params).fetchall()
        return [self._to_row(r) for r in rows]

    @staticmethod
    def _to_row(r: sqlite3.Row) -> CandidateRow:
        return CandidateRow(
            candidate_id=r["candidate_id"],
            applicant_url=r["applicant_url"],
            current_title=r["current_title"],
            current_company=r["current_company"],
            profile_scraped_at=r["profile_scraped_at"],
            resume_downloaded_at=r["resume_downloaded_at"],
            resume_parsed_at=r["resume_parsed_at"],
            score_stage1_at=r["score_stage1_at"],
            score_stage2_at=r["score_stage2_at"],
            status=r["status"],
            last_error=r["last_error"],
        )
