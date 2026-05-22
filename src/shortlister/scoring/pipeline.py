from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from ..logging import get_logger
from ..storage.layout import RoleLayout
from ..storage.manifest import Manifest
from .providers.base import LLMProvider
from .rubric import Rubric, render_rubric_block
from .schemas import (
    KnockoutOnlyResult,
    ScoreResult,
    knockout_only_json_schema,
    score_result_json_schema,
)

log = get_logger(__name__)


Mode = Literal["single", "two-stage"]


SYSTEM_PROMPT = (
    "You are an expert technical recruiter scoring software engineering candidates "
    "against a fixed rubric. You read the candidate's resume + scraped LinkedIn "
    "metadata and produce a structured assessment. Be specific and evidence-based: "
    "if the resume does not contain evidence for a criterion, score conservatively "
    "and say so in the reasoning. Reasoning fields must be at most 2 short lines."
)


@dataclass
class CandidateInput:
    candidate_id: str
    profile_csv_row: dict[str, str]
    resume_text: str

    def to_block(self) -> str:
        meta = "\n".join(f"{k}: {v}" for k, v in self.profile_csv_row.items() if v)
        return (
            f"CANDIDATE_ID: {self.candidate_id}\n"
            f"--- PROFILE METADATA ---\n{meta}\n"
            f"--- RESUME TEXT ---\n{self.resume_text}\n"
        )


def _build_cacheable_prefix(rubric: Rubric, jd_text: str) -> str:
    return (
        f"--- JOB DESCRIPTION ---\n{jd_text.strip()}\n\n"
        f"--- RUBRIC ---\n{render_rubric_block(rubric)}\n"
    )


async def _score_single_pass(
    provider: LLMProvider,
    rubric: Rubric,
    jd_text: str,
    candidate: CandidateInput,
) -> ScoreResult:
    schema = score_result_json_schema(
        [c.id for c in rubric.criteria],
        [k.id for k in rubric.knockouts],
    )
    raw = await provider.score(
        system=SYSTEM_PROMPT,
        cacheable_prefix=_build_cacheable_prefix(rubric, jd_text),
        candidate_block=candidate.to_block(),
        output_schema=schema,
        tool_name="record_candidate_score",
        tool_description="Record the structured scoring result for a single candidate.",
    )
    raw.setdefault("candidate_id", candidate.candidate_id)
    return ScoreResult.model_validate(raw)


async def _score_knockouts_only(
    provider: LLMProvider,
    rubric: Rubric,
    jd_text: str,
    candidate: CandidateInput,
) -> KnockoutOnlyResult:
    schema = knockout_only_json_schema([k.id for k in rubric.knockouts])
    raw = await provider.score(
        system=SYSTEM_PROMPT,
        cacheable_prefix=_build_cacheable_prefix(rubric, jd_text),
        candidate_block=candidate.to_block(),
        output_schema=schema,
        tool_name="record_knockout_check",
        tool_description="Record only the knockout-criteria evaluation for a single candidate.",
    )
    raw.setdefault("candidate_id", candidate.candidate_id)
    return KnockoutOnlyResult.model_validate(raw)


def _load_candidate_input(layout: RoleLayout, candidate_id: str, profile_csv_row: dict[str, str]) -> CandidateInput | None:
    txt_path = layout.resume_txt(candidate_id)
    if not txt_path.exists():
        return None
    return CandidateInput(
        candidate_id=candidate_id,
        profile_csv_row=profile_csv_row,
        resume_text=txt_path.read_text(encoding="utf-8"),
    )


def _load_csv_index(layout: RoleLayout) -> dict[str, dict[str, str]]:
    import csv

    if not layout.candidates_csv.exists():
        return {}
    with layout.candidates_csv.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return {row["candidate_id"]: row for row in reader if row.get("candidate_id")}


async def run_scoring(
    layout: RoleLayout,
    manifest: Manifest,
    *,
    rubric: Rubric,
    jd_text: str,
    mode: Mode,
    full_provider: LLMProvider,
    knockout_provider: LLMProvider | None = None,
) -> dict[str, int]:
    summary = {"stage1_scored": 0, "stage2_scored": 0, "knocked_out": 0, "failed": 0, "skipped": 0}
    csv_index = _load_csv_index(layout)

    if mode == "two-stage":
        ko_provider = knockout_provider or full_provider
        for row in manifest.candidates_needing_stage1_score():
            cand = _load_candidate_input(layout, row.candidate_id, csv_index.get(row.candidate_id, {}))
            if cand is None:
                summary["skipped"] += 1
                continue
            try:
                ko = await _score_knockouts_only(ko_provider, rubric, jd_text, cand)
            except (ValidationError, RuntimeError) as e:
                log.warning("Knockout pass failed for %s: %s", row.candidate_id, e)
                manifest.mark_failed(row.candidate_id, status="failed_score", error=str(e))
                summary["failed"] += 1
                continue

            layout.score_json(row.candidate_id).write_text(
                json.dumps(ko.model_dump(), indent=2), encoding="utf-8"
            )
            if not ko.passed:
                manifest.mark_stage1_scored(row.candidate_id, knocked_out=True)
                summary["knocked_out"] += 1
            else:
                manifest.mark_stage1_scored(row.candidate_id, knocked_out=False)
                summary["stage1_scored"] += 1

        # Stage 2: full score on survivors.
        for row in manifest.candidates_needing_stage2_score():
            cand = _load_candidate_input(layout, row.candidate_id, csv_index.get(row.candidate_id, {}))
            if cand is None:
                summary["skipped"] += 1
                continue
            try:
                full = await _score_single_pass(full_provider, rubric, jd_text, cand)
            except (ValidationError, RuntimeError) as e:
                log.warning("Full scoring failed for %s: %s", row.candidate_id, e)
                manifest.mark_failed(row.candidate_id, status="failed_score", error=str(e))
                summary["failed"] += 1
                continue
            layout.score_json(row.candidate_id).write_text(
                json.dumps(full.model_dump(), indent=2), encoding="utf-8"
            )
            manifest.mark_stage2_scored(row.candidate_id)
            summary["stage2_scored"] += 1

    else:  # single-pass
        for row in manifest.candidates_needing_stage1_score():
            cand = _load_candidate_input(layout, row.candidate_id, csv_index.get(row.candidate_id, {}))
            if cand is None:
                summary["skipped"] += 1
                continue
            try:
                full = await _score_single_pass(full_provider, rubric, jd_text, cand)
            except (ValidationError, RuntimeError) as e:
                log.warning("Scoring failed for %s: %s", row.candidate_id, e)
                manifest.mark_failed(row.candidate_id, status="failed_score", error=str(e))
                summary["failed"] += 1
                continue

            layout.score_json(row.candidate_id).write_text(
                json.dumps(full.model_dump(), indent=2), encoding="utf-8"
            )
            knocked_out = any(not k.passed for k in full.knockouts)
            manifest.mark_stage1_scored(row.candidate_id, knocked_out=knocked_out)
            if knocked_out:
                summary["knocked_out"] += 1
            else:
                # In single-pass, stage1 IS the full pass, so we also mark scored.
                manifest.mark_stage2_scored(row.candidate_id)
                summary["stage1_scored"] += 1
                summary["stage2_scored"] += 1

    return summary


def load_jd(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()
