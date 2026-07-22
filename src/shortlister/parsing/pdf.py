from __future__ import annotations

from pathlib import Path

from ..config import PARSE_MIN_USEFUL_CHARS
from ..logging import get_logger
from ..storage.layout import RoleLayout
from ..storage.manifest import Manifest

log = get_logger(__name__)


def _extract_with_pypdf(pdf_path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(pdf_path))
    parts: list[str] = []
    for page in reader.pages:
        try:
            txt = page.extract_text() or ""
        except Exception as e:  # noqa: BLE001
            log.debug("pypdf failed on a page of %s: %s", pdf_path.name, e)
            txt = ""
        if txt:
            parts.append(txt)
    return "\n".join(parts).strip()


def _extract_with_pdfplumber(pdf_path: Path) -> str:
    import pdfplumber

    parts: list[str] = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for page in pdf.pages:
            txt = page.extract_text() or ""
            if txt:
                parts.append(txt)
    return "\n".join(parts).strip()


def _strip_unencodable(text: str) -> str:
    """Drop characters that can't be encoded as UTF-8.

    PDF extractors sometimes emit lone surrogates (e.g. the leading half of an
    emoji, \\ud83d) that a Python str tolerates but `str.write_text(encoding="utf-8")`
    rejects with a UnicodeEncodeError. Round-tripping through UTF-8 with
    errors="ignore" drops exactly those code points and leaves valid text intact.
    """
    return text.encode("utf-8", "ignore").decode("utf-8")


def extract_text(pdf_path: Path) -> tuple[str, str]:
    """Extract text from a PDF, falling back from pypdf to pdfplumber if needed.

    Returns (text, extractor_used). `extractor_used` is "pypdf" or "pdfplumber".
    """
    text = _extract_with_pypdf(pdf_path)
    extractor = "pypdf"
    if len(text) < PARSE_MIN_USEFUL_CHARS:
        log.info("pypdf yielded only %d chars for %s, falling back to pdfplumber.", len(text), pdf_path.name)
        text = _extract_with_pdfplumber(pdf_path)
        extractor = "pdfplumber"
    return _strip_unencodable(text), extractor


def run_parse(layout: RoleLayout, manifest: Manifest) -> dict[str, int]:
    summary = {"parsed": 0, "unparseable": 0, "failed": 0, "skipped": 0}
    for row in manifest.candidates_needing_parse():
        pdf_path = layout.resume_pdf(row.candidate_id)
        if not pdf_path.exists():
            log.warning("Resume PDF missing for %s at %s; skipping.", row.candidate_id, pdf_path)
            summary["skipped"] += 1
            continue
        try:
            text, extractor = extract_text(pdf_path)
        except Exception as e:  # noqa: BLE001
            log.exception("PDF extraction failed for %s: %s", row.candidate_id, e)
            manifest.mark_failed(row.candidate_id, status="failed_parse", error=str(e))
            summary["failed"] += 1
            continue

        if len(text) < PARSE_MIN_USEFUL_CHARS:
            manifest.mark_unparseable(row.candidate_id)
            summary["unparseable"] += 1
            log.info("Resume for %s unparseable (< %d chars after both extractors).",
                     row.candidate_id, PARSE_MIN_USEFUL_CHARS)
            continue

        layout.resume_txt(row.candidate_id).write_text(text, encoding="utf-8")
        manifest.mark_resume_parsed(row.candidate_id)
        summary["parsed"] += 1
        log.debug("Parsed %s via %s (%d chars)", row.candidate_id, extractor, len(text))
    return summary
