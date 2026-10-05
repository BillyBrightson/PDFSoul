"""OCR: make scanned PDFs searchable and copyable with Tesseract.

Each page is rendered, Tesseract writes an invisible text layer for it, and that layer is laid
over the original page. The page itself is untouched, so nothing gets blurrier.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path
from threading import Event

import pymupdf as fitz

from pdfsoul.core import engines
from pdfsoul.core.document import open_pdf, save_pdf
from pdfsoul.core.ranges import parse_pages
from pdfsoul.core.types import PdfSoulError, Progress, ProgressFn, Result, no_progress

LANGUAGE_NAMES = {
    "eng": "English", "fra": "French", "deu": "German", "spa": "Spanish", "ita": "Italian",
    "por": "Portuguese", "nld": "Dutch", "swe": "Swedish", "dan": "Danish", "nor": "Norwegian",
    "fin": "Finnish", "pol": "Polish", "ces": "Czech", "rus": "Russian", "ukr": "Ukrainian",
    "ell": "Greek", "tur": "Turkish", "ara": "Arabic", "heb": "Hebrew", "hin": "Hindi",
    "chi_sim": "Chinese (simplified)", "chi_tra": "Chinese (traditional)", "jpn": "Japanese",
    "kor": "Korean", "vie": "Vietnamese", "tha": "Thai", "ind": "Indonesian", "swa": "Swahili",
}


@dataclass
class OcrOptions:
    language: str = "eng"  # Tesseract codes; join several with "+", e.g. "eng+fra"
    dpi: int = 300
    pages: str = ""
    skip_text_pages: bool = True  # pages that already have real text are left alone
    password: str | None = None


def languages() -> list[str]:
    """Installed Tesseract languages (``osd`` excluded); empty if Tesseract isn't found."""
    exe = engines.find("tesseract")
    if exe is None:
        return []
    try:
        listing = engines.run([str(exe), "--list-langs"], timeout=20)
    except PdfSoulError:
        return []
    names = [ln.strip() for ln in listing.splitlines()[1:] if ln.strip()]
    return [n for n in names if n not in {"osd", "equ"}]


def language_label(code: str) -> str:
    return " + ".join(LANGUAGE_NAMES.get(c, c) for c in code.split("+"))


def has_text(page: fitz.Page, min_chars: int = 20) -> bool:
    return len(page.get_text("text").strip()) >= min_chars


def ocr(inputs: list[Path], output: Path, opts: OcrOptions | None = None,
        progress: ProgressFn = no_progress, cancel: Event | None = None) -> Result:
    opts = opts or OcrOptions()
    if not 150 <= opts.dpi <= 600:
        raise PdfSoulError("OCR resolution must be between 150 and 600 dpi.")
    tesseract = engines.require("tesseract")
    installed = languages()
    for code in opts.language.split("+"):
        if installed and code not in installed:
            raise PdfSoulError(f"The Tesseract language pack '{code}' isn't installed.")
    done = skipped = 0
    with open_pdf(Path(inputs[0]), opts.password) as doc, \
            tempfile.TemporaryDirectory(prefix="pdfsoul-ocr-") as tmp_name:
        tmp = Path(tmp_name)
        pages = parse_pages(opts.pages, doc.page_count)
        tick = Progress(progress, cancel, len(pages))
        for p in pages:
            page = doc[p]
            if opts.skip_text_pages and has_text(page):
                skipped += 1
                tick.step()
                continue
            _ocr_page(tesseract, page, opts, tmp / f"p{p}", cancel)
            done += 1
            tick.step()
        save_pdf(doc, Path(output))
    if not done:
        return Result([Path(output)], "Every page already had text, so nothing needed OCR.",
                      {"ocr_pages": 0, "skipped": skipped})
    note = f" ({skipped} already had text)" if skipped else ""
    return Result([Path(output)], f"Recognised text on {done} page{'s' if done != 1 else ''}"
                  f"{note}. The PDF is now searchable.", {"ocr_pages": done, "skipped": skipped})


def _ocr_page(tesseract: Path, page: fitz.Page, opts: OcrOptions, base: Path,
              cancel: Event | None) -> None:
    rotation = page.rotation
    page.set_rotation(0)  # OCR the page as stored, so the text layer lines up after rotating back
    try:
        pix = page.get_pixmap(dpi=opts.dpi, colorspace=fitz.csGRAY, alpha=False)
        pix.set_dpi(opts.dpi, opts.dpi)
        image = base.with_suffix(".png")
        pix.save(image)
        engines.run([str(tesseract), str(image), str(base), "-l", opts.language,
                     "--dpi", str(opts.dpi), "-c", "textonly_pdf=1", "pdf"], cancel=cancel)
        layer_path = base.with_suffix(".pdf")
        if not layer_path.is_file():
            raise PdfSoulError("Tesseract didn't produce any output.")
        with fitz.open(layer_path) as layer:
            page.show_pdf_page(page.rect, layer, 0, overlay=True)
    finally:
        page.set_rotation(rotation)
