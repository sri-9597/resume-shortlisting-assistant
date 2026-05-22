from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field, model_validator


class Knockout(BaseModel):
    id: str
    description: str


class Criterion(BaseModel):
    id: str
    weight: float = Field(gt=0, le=1)
    description: str


class Rubric(BaseModel):
    role: str
    version: int = 1
    knockouts: list[Knockout]
    criteria: list[Criterion]

    @model_validator(mode="after")
    def _check_weights_and_ids(self) -> "Rubric":
        total = sum(c.weight for c in self.criteria)
        if abs(total - 1.0) > 1e-3:
            raise ValueError(f"Criterion weights must sum to 1.0, got {total:.4f}")
        ids = [c.id for c in self.criteria]
        if len(ids) != len(set(ids)):
            raise ValueError("Criterion ids must be unique.")
        ko_ids = [k.id for k in self.knockouts]
        if len(ko_ids) != len(set(ko_ids)):
            raise ValueError("Knockout ids must be unique.")
        return self


def load_rubric(path: Path) -> Rubric:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return Rubric.model_validate(data)


def render_rubric_block(rubric: Rubric) -> str:
    """Render the rubric as a deterministic text block for the LLM prompt."""
    lines: list[str] = [f"ROLE: {rubric.role}", "", "KNOCKOUTS (any failure ⇒ recommend=false):"]
    for k in rubric.knockouts:
        lines.append(f"  - {k.id}: {k.description}")
    lines.append("")
    lines.append("CRITERIA (score each 0–10):")
    for c in rubric.criteria:
        lines.append(f"  - {c.id} (weight {c.weight:.2f}): {c.description}")
    return "\n".join(lines)
