"""Opening and saving PDFs: passwords, automatic repair of damaged files, safe saving."""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass, field
from pathlib import Path

import pikepdf
import pymupdf as fitz

from pdfsoul.core.safe_io import atomic_output
from pdfsoul.core.types import PasswordRequired, PdfSoulError, WrongPassword

log = logging.getLogger(__name__)

# Small enough to be fast on 1,000-page files, still drops unused objects.
SAVE_OPTIONS = {"garbage": 3, "deflate": True,
                "encryption": getattr(fitz, "PDF_ENCRYPT_NONE", 1)}  # missing from the stubs


def open_pdf(path: Path, password: str | None = None, *, repair: bool = True) -> fitz.Document:
    """Open a PDF, unlocking it with ``password`` and repairing it with qpdf if MuPDF can't.

    Raises :class:`PasswordRequired`, :class:`WrongPassword` or :class:`PdfSoulError`.
    """
    path = Path(path)
    if not path.is_file():
        raise PdfSoulError(f"File not found: {path}")
    with path.open("rb") as fh:
        if b"%PDF" not in fh.read(1024):
            raise PdfSoulError(f"{path.name} isn't a PDF.")
    try:
        doc = fitz.open(path, filetype="pdf")
        if doc.page_count == 0 and not doc.needs_pass:
            raise PdfSoulError("No pages")
    except Exception as exc:
        if not repair:
            raise PdfSoulError(f"Couldn't read {path.name}: {exc}") from exc
        log.warning("MuPDF could not open %s (%s); trying qpdf repair", path, exc)
        doc = fitz.open(stream=repair_bytes(path, password), filetype="pdf")
    return unlock(_require_pdf(doc, path.name), password, path.name)


def _require_pdf(doc: fitz.Document, name: str) -> fitz.Document:
    """MuPDF also opens EPUB, XPS, images and Markdown; PDFSoul only works on PDFs."""
    if not doc.is_pdf:
        doc.close()
        raise PdfSoulError(f"{name} isn't a PDF.")
    return doc


def open_bytes(data: bytes, password: str | None = None, name: str = "document") -> fitz.Document:
    """Open a PDF held in memory (the viewer does this so the file on disk is never locked)."""
    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception as exc:
        raise PdfSoulError(f"Couldn't read {name}: {exc}") from exc
    return unlock(_require_pdf(doc, name), password, name)


def unlock(doc: fitz.Document, password: str | None, name: str) -> fitz.Document:
    if doc.needs_pass:
        if not password:
            doc.close()
            raise PasswordRequired(f"{name} is password protected.")
        if not doc.authenticate(password):
            doc.close()
            raise WrongPassword(f"Wrong password for {name}.")
    return doc


def is_encrypted(path: Path) -> bool:
    """True if opening ``path`` needs a password."""
    try:
        with fitz.open(path, filetype="pdf") as doc:
            return bool(doc.needs_pass)
    except Exception:
        return False


def repair_bytes(path: Path, password: str | None = None) -> bytes:
    """Rebuild a damaged PDF with qpdf and return the repaired bytes."""
    try:
        with pikepdf.open(path, password=password or "", attempt_recovery=True) as pdf:
            buf = io.BytesIO()
            pdf.save(buf)
            return buf.getvalue()
    except pikepdf.PasswordError as exc:
        raise (WrongPassword if password else PasswordRequired)(
            f"{Path(path).name} is password protected."
        ) from exc
    except Exception as exc:
        raise PdfSoulError(
            f"Couldn't read {Path(path).name}. It looks damaged beyond repair ({exc})."
        ) from exc


def save_pdf(doc: fitz.Document, target: Path, **options: object) -> Path:
    """Save ``doc`` to ``target`` through a temp file, so a crash never leaves a broken file."""
    with atomic_output(target) as tmp:
        doc.save(tmp, **{**SAVE_OPTIONS, **options})
    return Path(target)


@dataclass
class PdfInfo:
    path: Path
    pages: int
    encrypted: bool
    size_bytes: int
    metadata: dict[str, str] = field(default_factory=dict)
    bookmarks: int = 0
    form_fields: int = 0
    first_page_size_pt: tuple[float, float] = (0.0, 0.0)


def info(path: Path, password: str | None = None) -> PdfInfo:
    """Basic facts about a PDF, for the CLI ``info`` command and the UI's status bar."""
    path = Path(path)
    encrypted = is_encrypted(path)
    with open_pdf(path, password) as doc:
        rect = doc[0].rect if doc.page_count else fitz.Rect()
        fields = sum(1 for page in doc for _ in page.widgets())
        return PdfInfo(
            path=path,
            pages=doc.page_count,
            encrypted=encrypted,
            size_bytes=path.stat().st_size,
            metadata={k: v for k, v in (doc.metadata or {}).items() if v},
            bookmarks=len(doc.get_toc(simple=True)),
            form_fields=fields,
            first_page_size_pt=(round(rect.width, 1), round(rect.height, 1)),
        )


def normalise_toc(toc: list[list]) -> list[list]:
    """Fix bookmark levels so MuPDF accepts them: start at 1, never jump more than one level."""
    fixed: list[list] = []
    prev = 0
    for entry in toc:
        level = max(1, min(int(entry[0]), prev + 1))
        fixed.append([level, *entry[1:]])
        prev = level
    return fixed
