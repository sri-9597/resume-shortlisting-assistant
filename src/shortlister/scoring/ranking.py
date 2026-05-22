from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path

from ..logging import get_logger
from ..storage.layout import RoleLayout
from ..storage.manifest import Manifest

log = get_logger(__name__)


EXCLUDED_STATUSES = {
    "knocked_out",
    "no_resume",
    "unparseable",
    "failed_scrape",
    "failed_parse",
    "failed_score",
    "discovered",  # never reached scoring
    "ok",          # scraped but never scored
}


@dataclass
class RankedRow:
    rank: int
    candidate_id: str
    name: str
    headline: str
    location: str
    current_title: str
    current_company: str
    weighted_total: float
    recommend: bool
    summary: str
    profile_url: str


def _load_csv_index(layout: RoleLayout) -> dict[str, dict[str, str]]:
    if not layout.candidates_csv.exists():
        return {}
    with layout.candidates_csv.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return {row["candidate_id"]: row for row in reader if row.get("candidate_id")}


def _tiebreak_key(row) -> str:
    return row.score_stage2_at or row.score_stage1_at or ""


def rank(layout: RoleLayout, manifest: Manifest, *, top_n: int = 50) -> dict[str, int]:
    csv_index = _load_csv_index(layout)
    rows = manifest.all_candidates()
    ranked: list[tuple[float, str, dict, dict]] = []  # (-weighted, tiebreak, score, csv_row)

    for row in rows:
        if row.status in EXCLUDED_STATUSES:
            continue
        score_path = layout.score_json(row.candidate_id)
        if not score_path.exists():
            continue
        try:
            score = json.loads(score_path.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            log.warning("Could not read score JSON for %s: %s", row.candidate_id, e)
            continue
        weighted = float(score.get("weighted_total", 0.0))
        ranked.append((-weighted, _tiebreak_key(row), score, csv_index.get(row.candidate_id, {})))

    ranked.sort(key=lambda t: (t[0], t[1]))

    full: list[RankedRow] = []
    for i, (neg, _tie, score, csv_row) in enumerate(ranked, start=1):
        full.append(
            RankedRow(
                rank=i,
                candidate_id=score.get("candidate_id", csv_row.get("candidate_id", "")),
                name=csv_row.get("name", ""),
                headline=csv_row.get("headline", ""),
                location=csv_row.get("location", ""),
                current_title=csv_row.get("current_title", ""),
                current_company=csv_row.get("current_company", ""),
                weighted_total=-neg,
                recommend=bool(score.get("recommend", False)),
                summary=score.get("summary", ""),
                profile_url=csv_row.get("profile_url", ""),
            )
        )

    _write_csv(layout.ranked_full_csv, full)
    _write_csv(layout.ranked_csv, full[:top_n])
    return {"ranked": len(full), "top_n_written": min(top_n, len(full))}


def _write_csv(path: Path, rows: list[RankedRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    headers = [
        "rank",
        "candidate_id",
        "name",
        "headline",
        "location",
        "current_title",
        "current_company",
        "weighted_total",
        "recommend",
        "summary",
        "profile_url",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        for r in rows:
            writer.writerow(
                {
                    "rank": r.rank,
                    "candidate_id": r.candidate_id,
                    "name": r.name,
                    "headline": r.headline,
                    "location": r.location,
                    "current_title": r.current_title,
                    "current_company": r.current_company,
                    "weighted_total": f"{r.weighted_total:.3f}",
                    "recommend": "true" if r.recommend else "false",
                    "summary": r.summary,
                    "profile_url": r.profile_url,
                }
            )
