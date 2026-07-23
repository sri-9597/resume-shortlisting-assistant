from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RoleLayout:
    role: str
    root: Path

    @property
    def manifest_path(self) -> Path:
        return self.root / "manifest.sqlite"

    @property
    def candidates_csv(self) -> Path:
        return self.root / "candidates.csv"

    @property
    def resumes_dir(self) -> Path:
        return self.root / "resumes"

    @property
    def scores_dir(self) -> Path:
        return self.root / "scores"

    @property
    def ranked_csv(self) -> Path:
        return self.root / "ranked.csv"

    @property
    def ranked_full_csv(self) -> Path:
        return self.root / "ranked_full.csv"

    @property
    def ranked_resumes_dir(self) -> Path:
        return self.root / "ranked_resumes"

    def resume_pdf(self, candidate_id: str) -> Path:
        return self.resumes_dir / f"{candidate_id}.pdf"

    def resume_txt(self, candidate_id: str) -> Path:
        return self.resumes_dir / f"{candidate_id}.txt"

    def score_json(self, candidate_id: str) -> Path:
        return self.scores_dir / f"{candidate_id}.json"

    def ensure_dirs(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.resumes_dir.mkdir(parents=True, exist_ok=True)
        self.scores_dir.mkdir(parents=True, exist_ok=True)


def layout_for(role: str, cwd: Path | None = None) -> RoleLayout:
    base = cwd or Path.cwd()
    return RoleLayout(role=role, root=base / role)
