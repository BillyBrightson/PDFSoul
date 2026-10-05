"""Fixture PDFs, generated once per test session.

The awkward cases from the PRD: scanned (image-only), encrypted, form, 1,000-page, corrupted,
non-Latin text, rotated pages, plus a bookmarked file and an image-heavy one for compression.
Drop real-world files into tests/fixtures/ and they join the robustness sweep automatically.
"""

from __future__ import annotations

import io
from pathlib import Path

import pikepdf
import pymupdf as fitz
import pytest
from PIL import Image

FIXTURE_DIR = Path(__file__).parent / "fixtures"
PASSWORD = "secret"


def _text_pdf(path: Path, pages: int, *, bookmarks: bool = False) -> Path:
    doc = fitz.open()
    for i in range(pages):
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 100), f"Page {i + 1} of the sample", fontsize=20)
        page.insert_text((72, 140), "The quick brown fox jumps over the lazy dog.", fontsize=11)
    if bookmarks:
        doc.set_toc([
            [1, "Introduction", 1],
            [2, "Background", 2],
            [1, "Methods", 4],
            [1, "Results", 7],
            [2, "Tables", 8],
        ])
    doc.set_metadata({"title": "Sample document", "author": "PDFSoul tests"})
    doc.save(path)
    return path


def _photo_bytes(width: int, height: int) -> bytes:
    """A smooth, photo-like image stored losslessly so compression has work to do."""
    img = Image.radial_gradient("L").resize((width, height)).convert("RGB")
    r, g, b = img.split()
    img = Image.merge("RGB", (r, g.rotate(90), b.transpose(Image.Transpose.FLIP_LEFT_RIGHT)))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture(scope="session")
def fixtures(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    d = tmp_path_factory.mktemp("fixtures")
    files: dict[str, Path] = {}

    files["simple"] = _text_pdf(d / "simple.pdf", 10, bookmarks=True)
    files["thousand"] = _text_pdf(d / "thousand.pdf", 1000)

    files["encrypted"] = d / "encrypted.pdf"
    with pikepdf.open(files["simple"]) as pdf:
        pdf.save(files["encrypted"], encryption=pikepdf.Encryption(user=PASSWORD,
                                                                   owner=PASSWORD, R=6))

    files["scanned"] = d / "scanned.pdf"
    doc = fitz.open()
    photo = _photo_bytes(1700, 2200)
    for _ in range(3):
        page = doc.new_page(width=612, height=792)
        page.insert_image(page.rect, stream=photo)
    doc.save(files["scanned"])

    files["form"] = d / "form.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 90), "Name:", fontsize=12)
    widget = fitz.Widget()
    widget.field_name = "name"
    widget.field_type = fitz.PDF_WIDGET_TYPE_TEXT
    widget.rect = fitz.Rect(120, 75, 400, 95)
    widget.field_value = "Ada"
    page.add_widget(widget)
    doc.save(files["form"])

    files["nonlatin"] = d / "nonlatin.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 100), "你好，世界 — PDF 工具", fontname="china-s", fontsize=16)
    page.insert_text((72, 140), "Ελληνικά και Кириллица", fontname="china-s", fontsize=14)
    doc.save(files["nonlatin"])

    files["rotated"] = d / "rotated.pdf"
    doc = fitz.open(files["simple"])
    doc[0].set_rotation(90)
    doc[1].set_rotation(180)
    doc.save(files["rotated"])

    files["corrupted"] = d / "corrupted.pdf"
    raw = files["simple"].read_bytes()
    cut = raw.rfind(b"xref")
    files["corrupted"].write_bytes(raw[:cut] + b"garbage\n%%EOF")  # xref table destroyed

    for real in sorted(FIXTURE_DIR.glob("*.pdf")):
        files[f"real:{real.name}"] = real
    return files


@pytest.fixture
def out(tmp_path: Path) -> Path:
    return tmp_path


def page_texts(path: Path, password: str | None = None) -> list[str]:
    with fitz.open(path) as doc:
        if password:
            doc.authenticate(password)
        return [p.get_text().strip() for p in doc]


def first_lines(path: Path) -> list[str]:
    return [t.splitlines()[0] if t else "" for t in page_texts(path)]
