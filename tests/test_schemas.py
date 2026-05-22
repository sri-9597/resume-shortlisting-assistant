from __future__ import annotations

from shortlister.scoring.schemas import (
    KnockoutOnlyResult,
    ScoreResult,
    knockout_only_json_schema,
    score_result_json_schema,
)


def test_knockout_failure_forces_recommend_false() -> None:
    r = ScoreResult.model_validate(
        {
            "candidate_id": "c1",
            "criteria": [
                {"id": "a", "score": 9, "reasoning": "good"},
                {"id": "b", "score": 8, "reasoning": "ok"},
            ],
            "knockouts": [{"id": "k1", "passed": False, "reasoning": "no"}],
            "weighted_total": 8.5,
            "recommend": True,
            "summary": "x",
        }
    )
    assert r.recommend is False


def test_knockout_only_passed_is_consistent_with_items() -> None:
    r = KnockoutOnlyResult.model_validate(
        {
            "candidate_id": "c1",
            "knockouts": [
                {"id": "k1", "passed": True, "reasoning": "y"},
                {"id": "k2", "passed": False, "reasoning": "n"},
            ],
            "passed": True,
        }
    )
    assert r.passed is False


def test_schema_has_correct_enum_lists() -> None:
    s = score_result_json_schema(["a", "b"], ["k1"])
    crit_enum = s["properties"]["criteria"]["items"]["properties"]["id"]["enum"]
    assert crit_enum == ["a", "b"]
    ko_enum = s["properties"]["knockouts"]["items"]["properties"]["id"]["enum"]
    assert ko_enum == ["k1"]

    ko_only = knockout_only_json_schema(["k1", "k2"])
    assert ko_only["properties"]["knockouts"]["items"]["properties"]["id"]["enum"] == ["k1", "k2"]
