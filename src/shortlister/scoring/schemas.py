from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


class CriterionScore(BaseModel):
    id: str
    score: float = Field(ge=0, le=10)
    reasoning: str


class KnockoutResult(BaseModel):
    id: str
    passed: bool
    reasoning: str


class ScoreResult(BaseModel):
    candidate_id: str
    criteria: list[CriterionScore]
    knockouts: list[KnockoutResult]
    weighted_total: float = Field(ge=0, le=10)
    recommend: bool
    summary: str

    @model_validator(mode="after")
    def _recommend_consistency(self) -> "ScoreResult":
        # If any knockout fails, recommend must be False. The model is expected to
        # honor this, but we clamp defensively.
        if any(not k.passed for k in self.knockouts) and self.recommend:
            self.recommend = False
        return self


class KnockoutOnlyResult(BaseModel):
    candidate_id: str
    knockouts: list[KnockoutResult]
    passed: bool

    @model_validator(mode="after")
    def _passed_consistency(self) -> "KnockoutOnlyResult":
        actual = all(k.passed for k in self.knockouts)
        if self.passed != actual:
            self.passed = actual
        return self


def score_result_json_schema(rubric_criteria_ids: list[str], knockout_ids: list[str]) -> dict:
    """JSON schema fed to LLM tool-use / json-mode for the full scoring pass."""
    return {
        "type": "object",
        "properties": {
            "candidate_id": {"type": "string"},
            "criteria": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "enum": rubric_criteria_ids},
                        "score": {"type": "number", "minimum": 0, "maximum": 10},
                        "reasoning": {"type": "string"},
                    },
                    "required": ["id", "score", "reasoning"],
                },
                "minItems": len(rubric_criteria_ids),
                "maxItems": len(rubric_criteria_ids),
            },
            "knockouts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "enum": knockout_ids},
                        "passed": {"type": "boolean"},
                        "reasoning": {"type": "string"},
                    },
                    "required": ["id", "passed", "reasoning"],
                },
                "minItems": len(knockout_ids),
                "maxItems": len(knockout_ids),
            },
            "weighted_total": {"type": "number", "minimum": 0, "maximum": 10},
            "recommend": {"type": "boolean"},
            "summary": {"type": "string"},
        },
        "required": ["candidate_id", "criteria", "knockouts", "weighted_total", "recommend", "summary"],
    }


def knockout_only_json_schema(knockout_ids: list[str]) -> dict:
    return {
        "type": "object",
        "properties": {
            "candidate_id": {"type": "string"},
            "knockouts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "enum": knockout_ids},
                        "passed": {"type": "boolean"},
                        "reasoning": {"type": "string"},
                    },
                    "required": ["id", "passed", "reasoning"],
                },
                "minItems": len(knockout_ids),
                "maxItems": len(knockout_ids),
            },
            "passed": {"type": "boolean"},
        },
        "required": ["candidate_id", "knockouts", "passed"],
    }
