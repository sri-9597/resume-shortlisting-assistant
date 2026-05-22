from __future__ import annotations

from pathlib import Path

import pytest

from shortlister.scoring.rubric import Rubric, load_rubric, render_rubric_block


SAMPLE = """
role: T
version: 1
knockouts:
  - {id: must_india, description: India based}
criteria:
  - {id: a, weight: 0.5, description: A}
  - {id: b, weight: 0.5, description: B}
"""


def test_loads_and_validates(tmp_path: Path) -> None:
    p = tmp_path / "r.yaml"
    p.write_text(SAMPLE)
    r = load_rubric(p)
    assert isinstance(r, Rubric)
    assert r.role == "T"
    assert [c.id for c in r.criteria] == ["a", "b"]
    block = render_rubric_block(r)
    assert "KNOCKOUTS" in block and "must_india" in block
    assert "a (weight 0.50)" in block


def test_weights_must_sum_to_one(tmp_path: Path) -> None:
    bad = SAMPLE.replace("{id: b, weight: 0.5, description: B}", "{id: b, weight: 0.4, description: B}")
    assert "0.4" in bad  # sanity-check the replacement actually fired
    p = tmp_path / "r.yaml"
    p.write_text(bad)
    with pytest.raises(Exception):
        load_rubric(p)


def test_duplicate_criterion_ids_rejected(tmp_path: Path) -> None:
    bad = """
role: T
version: 1
knockouts:
  - {id: k1, description: x}
criteria:
  - {id: a, weight: 0.5, description: A}
  - {id: a, weight: 0.5, description: B}
"""
    p = tmp_path / "r.yaml"
    p.write_text(bad)
    with pytest.raises(Exception):
        load_rubric(p)


@pytest.mark.parametrize(
    "rubric_name",
    ["backend-engineer.yaml", "qa-engineer.yaml", "customer-support.yaml"],
)
def test_example_rubrics_load(rubric_name: str) -> None:
    # Every rubric shipped under examples/rubrics/ must validate and have
    # weights that sum to 1.0.
    project_root = Path(__file__).resolve().parents[1]
    r = load_rubric(project_root / "examples" / "rubrics" / rubric_name)
    assert abs(sum(c.weight for c in r.criteria) - 1.0) < 1e-3
