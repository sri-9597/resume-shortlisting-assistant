from __future__ import annotations

from pathlib import Path

import pytest

from shortlister.parsing import pdf as pdf_module


def _make_simple_pdf(path: Path, body_text: str) -> None:
    """Generate a minimal PDF with the given text using pypdf, no external deps."""
    pypdf = pytest.importorskip("pypdf")
    from pypdf.generic import (
        ArrayObject,
        DictionaryObject,
        FloatObject,
        NameObject,
        NumberObject,
        TextStringObject,
        create_string_object,
        ByteStringObject,
    )
    # Simplest reliable path: use reportlab if available, otherwise skip.
    reportlab = pytest.importorskip("reportlab", reason="reportlab not installed; PDF generation skipped")
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(str(path))
    text_obj = c.beginText(50, 750)
    for line in body_text.splitlines() or [body_text]:
        text_obj.textLine(line)
    c.drawText(text_obj)
    c.showPage()
    c.save()


def test_strip_unencodable_drops_lone_surrogates() -> None:
    # pypdf sometimes emits the leading half of an emoji as a lone surrogate;
    # it must be removed so write_text(encoding="utf-8") doesn't blow up.
    raw = "Jane Doe \ud83d Senior QA Engineer"
    cleaned = pdf_module._strip_unencodable(raw)
    cleaned.encode("utf-8")  # would raise UnicodeEncodeError before stripping
    assert "\ud83d" not in cleaned
    assert "Jane Doe" in cleaned and "Senior QA Engineer" in cleaned


def test_extract_text_pypdf_happy_path(tmp_path: Path) -> None:
    pdf_path = tmp_path / "ok.pdf"
    body = "John Doe\nSenior Software Engineer\n" + ("Python and Java backend work. " * 20)
    _make_simple_pdf(pdf_path, body)
    text, extractor = pdf_module.extract_text(pdf_path)
    assert "Senior Software Engineer" in text or "Software Engineer" in text
    assert extractor in ("pypdf", "pdfplumber")
    assert len(text) >= 100
