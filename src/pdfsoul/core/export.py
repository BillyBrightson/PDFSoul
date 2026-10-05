"""PDF → Word, Excel, PowerPoint, HTML, Markdown, PDF/A and grayscale PDF."""

from __future__ import annotations

import html
import io
import logging
import re
import tempfile
from collections import Counter
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from threading import Event

import pikepdf
import pymupdf as fitz

from pdfsoul.core import engines
from pdfsoul.core.document import open_pdf
from pdfsoul.core.optimise import _decrypted_copy
from pdfsoul.core.ranges import parse_pages
from pdfsoul.core.safe_io import atomic_output
from pdfsoul.core.types import (
    Cancelled,
    PdfSoulError,
    Progress,
    ProgressFn,
    Result,
    check_cancel,
    no_progress,
)

log = logging.getLogger(__name__)

EMU_PER_PT = 12700


def _count(pages: list[int]) -> str:
    return f"{len(pages)} page{'s' if len(pages) != 1 else ''}"


def _plain_bytes(doc: fitz.Document) -> bytes:
    """The document as unencrypted PDF bytes, for libraries that open files themselves."""
    return doc.tobytes(garbage=0, encryption=getattr(fitz, "PDF_ENCRYPT_NONE", 1))


# ---------------------------------------------------------------------------------------------
# PDF → Word


@dataclass
class PdfToWordOptions:
    pages: str = ""
    password: str | None = None


class _Pdf2DocxProgress(logging.Handler):
    """pdf2docx reports "[3/4] Parsing pages…" then "(i/n) Page p"; map that onto 0..1."""

    _PHASE = re.compile(r"\[(\d)/4\]")
    _PAGE = re.compile(r"\((\d+)/(\d+)\) Page")

    def __init__(self, progress: ProgressFn, cancel: Event | None) -> None:
        super().__init__(logging.INFO)
        self._progress, self._cancel, self._phase = progress, cancel, 1

    def handle(self, record: logging.LogRecord) -> bool:  # raising here aborts the conversion
        check_cancel(self._cancel)
        message = record.getMessage()
        if m := self._PHASE.search(message):
            self._phase = int(m.group(1))
        elif m := self._PAGE.search(message):
            done, total = int(m.group(1)), max(int(m.group(2)), 1)
            start, span = (0.1, 0.5) if self._phase <= 3 else (0.6, 0.35)
            self._progress(start + span * done / total)
        return True


def pdf_to_word(inputs: list[Path], output: Path, opts: PdfToWordOptions | None = None,
                progress: ProgressFn = no_progress, cancel: Event | None = None) -> Result:
    """Editable .docx with paragraphs, fonts, tables and images rebuilt from the layout."""
    from pdf2docx import Converter

    opts = opts or PdfToWordOptions()
    with open_pdf(Path(inputs[0]), opts.password) as doc:
        pages = parse_pages(opts.pages, doc.page_count)
        data = _plain_bytes(doc)
    progress(0.05)
    handler = _Pdf2DocxProgress(progress, cancel)
    pdf2docx_log = logging.getLogger()  # pdf2docx logs through the root logger
    pdf2docx_log.addHandler(handler)
    previous_level = pdf2docx_log.level
    pdf2docx_log.setLevel(min(previous_level or logging.INFO, logging.INFO))
    try:
        with atomic_output(Path(output)) as tmp:
            converter = Converter(stream=data)
            try:
                converter.convert(str(tmp), pages=pages)
            finally:
                converter.close()
    except Cancelled:
        raise
    except Exception as exc:
        raise PdfSoulError(f"Couldn't convert to Word: {exc}") from exc
    finally:
        pdf2docx_log.removeHandler(handler)
        pdf2docx_log.setLevel(previous_level)
    progress(1.0)
    return Result([Path(output)], f"Converted {_count(pages)} to Word.")


# ---------------------------------------------------------------------------------------------
# PDF → Excel


class ExcelMode(StrEnum):
    TABLES = "tables"  # one sheet per detected table
    PAGES = "pages"  # one sheet per page: tables if found, otherwise text lines


@dataclass
class PdfToExcelOptions:
    pages: str = ""
    mode: ExcelMode = ExcelMode.TABLES
    password: str | None = None


_NUMBER = re.compile(r"^[-+(]?[$€£¥]?\s?\d{1,3}(?:[,\s]\d{3})*(?:\.\d+)?%?\)?$|^[-+]?\d*\.?\d+$")


def _cell_value(text: str | None) -> object:
    """'1,234.50' → 1234.5, '(12)' → -12, '7%' → 0.07; everything else stays text."""
    if text is None:
        return None
    text = text.strip()
    if not text or not _NUMBER.match(text):
        return text or None
    negative = (text.startswith("(") and text.endswith(")")) or text.startswith("-")
    percent = text.endswith("%") or text.endswith("%)")
    digits = re.sub(r"[^\d.]", "", text)
    try:
        value = float(digits)
    except ValueError:
        return text
    value = -value if negative else value
    value = value / 100 if percent else value
    return int(value) if value.is_integer() and "." not in digits and not percent else value


def _text_rows(page: fitz.Page) -> list[list[str]]:
    """Text lines split into columns wherever there's a wide gap."""
    rows = []
    for line in page.get_text("text", sort=True).splitlines():
        if line.strip():
            rows.append([c for c in re.split(r"\s{2,}|\t", line.strip()) if c])
    return rows


def pdf_to_excel(inputs: list[Path], output: Path, opts: PdfToExcelOptions | None = None,
                 progress: ProgressFn = no_progress, cancel: Event | None = None) -> Result:
    """Tables → worksheets. Numbers become real numbers so formulas work on them."""
    from openpyxl import Workbook
    from openpyxl.utils import get_column_letter

    opts = opts or PdfToExcelOptions()
    mode = ExcelMode(opts.mode)
    book = Workbook()
    book.remove(book.active)
    tables = 0
    with open_pdf(Path(inputs[0]), opts.password) as doc:
        pages = parse_pages(opts.pages, doc.page_count)
        tick = Progress(progress, cancel, len(pages))
        for p in pages:
            page = doc[p]
            found = [t.extract() for t in page.find_tables().tables]
            found = [t for t in found if t and any(any(c for c in row) for row in t)]
            tables += len(found)
            if mode is ExcelMode.TABLES:
                for n, rows in enumerate(found, start=1):
                    _write_sheet(book, f"Page {p + 1} table {n}", rows, header=True)
            else:
                blocks = found or [_text_rows(page)]
                sheet_rows: list[list] = []
                for rows in blocks:
                    sheet_rows.extend(rows)
                    sheet_rows.append([])
                _write_sheet(book, f"Page {p + 1}", sheet_rows, header=bool(found))
            tick.step()
        if not book.worksheets:  # no tables anywhere: fall back to the text so it isn't empty
            for p in pages:
                _write_sheet(book, f"Page {p + 1}", _text_rows(doc[p]), header=False)

    def autosize(sheet) -> None:
        for column in sheet.columns:
            width = max((len(str(c.value)) for c in column if c.value is not None), default=0)
            sheet.column_dimensions[get_column_letter(column[0].column)].width = min(
                max(width + 2, 8), 60)

    for sheet in book.worksheets:
        autosize(sheet)
        if sheet.cell(1, 1).font.bold:
            sheet.freeze_panes = "A2"
    with atomic_output(Path(output)) as tmp:
        book.save(tmp)
    if tables:
        message = f"Exported {tables} table{'s' if tables != 1 else ''} to Excel."
    else:
        message = "No tables found, so each page's text lines were exported to Excel."
    return Result([Path(output)], message, {"tables": tables})


def _write_sheet(book, title: str, rows: list[list], header: bool) -> None:
    from openpyxl.styles import Font

    sheet = book.create_sheet(_sheet_title(book, title))
    for r, row in enumerate(rows, start=1):
        for c, value in enumerate(row, start=1):
            cell = sheet.cell(r, c, _cell_value(value) if isinstance(value, str) else value)
            if header and r == 1:
                cell.font = Font(bold=True)


def _sheet_title(book, title: str) -> str:
    title = re.sub(r"[\[\]:*?/\\]", " ", title)[:31]
    base, n = title, 2
    while title in book.sheetnames:
        suffix = f" ({n})"
        title = base[:31 - len(suffix)] + suffix
        n += 1
    return title


# ---------------------------------------------------------------------------------------------
# PDF → PowerPoint


@dataclass
class PdfToPowerPointOptions:
    pages: str = ""
    dpi: int = 200
    notes: bool = True  # put each page's text in the speaker notes (searchable, copyable)
    password: str | None = None


def pdf_to_powerpoint(inputs: list[Path], output: Path,
                      opts: PdfToPowerPointOptions | None = None,
                      progress: ProgressFn = no_progress, cancel: Event | None = None) -> Result:
    """One slide per page, sized to the page, with the page as a crisp picture."""
    from pptx import Presentation
    from pptx.util import Emu

    opts = opts or PdfToPowerPointOptions()
    if not 72 <= opts.dpi <= 400:
        raise PdfSoulError("Slide quality must be between 72 and 400 dpi.")
    deck = Presentation()
    with open_pdf(Path(inputs[0]), opts.password) as doc:
        pages = parse_pages(opts.pages, doc.page_count)
        first = doc[pages[0]].rect
        # PowerPoint allows 1-56 inch slides.
        width = min(max(first.width, 72), 4032)
        height = min(max(first.height, 72), 4032)
        deck.slide_width, deck.slide_height = Emu(int(width * EMU_PER_PT)), Emu(
            int(height * EMU_PER_PT))
        blank = deck.slide_layouts[6]
        tick = Progress(progress, cancel, len(pages))
        for p in pages:
            page = doc[p]
            pix = page.get_pixmap(dpi=opts.dpi, alpha=False)
            slide = deck.slides.add_slide(blank)
            scale = min(width / page.rect.width, height / page.rect.height)
            w, h = page.rect.width * scale, page.rect.height * scale
            slide.shapes.add_picture(io.BytesIO(pix.tobytes("png")),
                                     Emu(int((width - w) / 2 * EMU_PER_PT)),
                                     Emu(int((height - h) / 2 * EMU_PER_PT)),
                                     Emu(int(w * EMU_PER_PT)), Emu(int(h * EMU_PER_PT)))
            text = page.get_text("text", sort=True).strip()
            if opts.notes and text:
                slide.notes_slide.notes_text_frame.text = _xml_safe(text)
            tick.step()
    with atomic_output(Path(output)) as tmp:
        deck.save(str(tmp))
    return Result([Path(output)], f"Made a {len(pages)}-slide PowerPoint deck.")


_XML_BAD = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _xml_safe(text: str) -> str:
    return _XML_BAD.sub("", text)


# ---------------------------------------------------------------------------------------------
# PDF → HTML


class HtmlMode(StrEnum):
    LAYOUT = "layout"  # every line positioned exactly as on the page
    REFLOW = "reflow"  # semantic paragraphs that reflow to any screen width


@dataclass
class PdfToHtmlOptions:
    pages: str = ""
    mode: HtmlMode = HtmlMode.REFLOW
    password: str | None = None


_HTML_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  body {{ margin: 0; background: #eceef2; font-family: system-ui, sans-serif; }}
  .page {{ background: #fff; margin: 24px auto; box-shadow: 0 2px 12px rgba(0,0,0,.12); }}
  .reflow {{ max-width: 820px; padding: 48px 56px; line-height: 1.5; color: #1c1c22; }}
  .reflow img {{ max-width: 100%; height: auto; }}
  .layout > div {{ margin: 0 auto; }}
</style>
</head>
<body>
{body}
</body>
</html>
"""


def pdf_to_html(inputs: list[Path], output: Path, opts: PdfToHtmlOptions | None = None,
                progress: ProgressFn = no_progress, cancel: Event | None = None) -> Result:
    """A single self-contained .html file; images are embedded."""
    opts = opts or PdfToHtmlOptions()
    mode = HtmlMode(opts.mode)
    parts: list[str] = []
    source = Path(inputs[0])
    with open_pdf(source, opts.password) as doc:
        pages = parse_pages(opts.pages, doc.page_count)
        tick = Progress(progress, cancel, len(pages))
        title = doc.metadata.get("title") if doc.metadata else ""
        for p in pages:
            page = doc[p]
            if mode is HtmlMode.LAYOUT:
                parts.append(f'<section class="page layout" style="width:{page.rect.width:.0f}pt"'
                             f">\n{page.get_text('html')}\n</section>")
            else:
                parts.append(f'<section class="page reflow" id="page-{p + 1}">\n'
                             f"{page.get_text('xhtml')}\n</section>")
            tick.step()
    body = _HTML_PAGE.format(title=html.escape(title or source.stem), body="\n".join(parts))
    with atomic_output(Path(output)) as tmp:
        tmp.write_text(body, encoding="utf-8")
    return Result([Path(output)], f"Converted {_count(pages)} to HTML.")


# ---------------------------------------------------------------------------------------------
# PDF → Markdown


@dataclass
class PdfToMarkdownOptions:
    pages: str = ""
    page_breaks: bool = False
    password: str | None = None


_BULLET = re.compile(r"^\s*([•◦▪●○■□–·*-])\s+")
_NUMBERED = re.compile(r"^\s*(\d{1,3}|[a-zA-Z])[.)]\s+")


def pdf_to_markdown(inputs: list[Path], output: Path, opts: PdfToMarkdownOptions | None = None,
                    progress: ProgressFn = no_progress, cancel: Event | None = None) -> Result:
    """Headings (from font size), bold/italic, lists and tables as GitHub-flavoured Markdown."""
    opts = opts or PdfToMarkdownOptions()
    out: list[str] = []
    with open_pdf(Path(inputs[0]), opts.password) as doc:
        pages = parse_pages(opts.pages, doc.page_count)
        body_size = _body_font_size(doc, pages)
        tick = Progress(progress, cancel, len(pages))
        for n, p in enumerate(pages):
            if opts.page_breaks and n:
                out.append(f"\n---\n<!-- Page {p + 1} -->\n")
            out.append(_page_markdown(doc[p], body_size))
            tick.step()
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip() + "\n"
    with atomic_output(Path(output)) as tmp:
        tmp.write_text(text, encoding="utf-8")
    words = len(text.split())
    note = "" if words >= len(pages) * 5 else " Little text found — try OCR first."
    return Result([Path(output)], f"Converted {_count(pages)} to Markdown.{note}")


def _body_font_size(doc: fitz.Document, pages: list[int]) -> float:
    sizes: Counter[float] = Counter()
    for p in pages[:50]:
        for block in doc[p].get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                for span in line["spans"]:
                    sizes[round(span["size"], 1)] += len(span["text"].strip())
    return sizes.most_common(1)[0][0] if sizes else 11.0


def _page_markdown(page: fitz.Page, body: float) -> str:
    tables = page.find_tables().tables
    table_boxes = [fitz.Rect(t.bbox) for t in tables]
    pieces: list[tuple[float, str]] = [(t.bbox[1], _table_markdown(t.extract())) for t in tables]
    for block in page.get_text("dict", sort=True)["blocks"]:
        if block.get("type") != 0:
            continue
        box = fitz.Rect(block["bbox"])
        if any(box.intersects(t) and (box & t).get_area() > 0.5 * box.get_area()
               for t in table_boxes):
            continue
        lines = [ln for ln in block["lines"] if "".join(s["text"] for s in ln["spans"]).strip()]
        if not lines:
            continue
        size = max(s["size"] for ln in lines for s in ln["spans"] if s["text"].strip())
        all_bold = all(s["flags"] & 16 or "bold" in s["font"].lower()
                       for ln in lines for s in ln["spans"] if s["text"].strip())
        text_lines = [_line_markdown(ln["spans"], plain=size >= body * 1.12) for ln in lines]
        joined = " ".join(t.strip() for t in text_lines)
        short = len(joined) < 120
        if size >= body * 1.6 and short:
            md = f"# {joined}"
        elif size >= body * 1.3 and short:
            md = f"## {joined}"
        elif (size >= body * 1.12 or (all_bold and len(lines) == 1)) and short:
            md = f"### {joined.strip('*')}"
        else:
            md = _paragraph(text_lines)
        pieces.append((box.y0, md))
    pieces.sort(key=lambda item: item[0])
    return "\n\n".join(md for _, md in pieces)


def _line_markdown(spans: list[dict], plain: bool) -> str:
    out = []
    for span in spans:
        text = span["text"]
        if plain or not text.strip():
            out.append(text)
            continue
        bold = span["flags"] & 16 or "bold" in span["font"].lower()
        italic = span["flags"] & 2 or "italic" in span["font"].lower()
        core = text.strip()
        lead, trail = text[:len(text) - len(text.lstrip())], text[len(text.rstrip()):]
        if bold and italic:
            core = f"***{core}***"
        elif bold:
            core = f"**{core}**"
        elif italic:
            core = f"*{core}*"
        out.append(f"{lead}{core}{trail}")
    return "".join(out).replace("** **", " ")


def _paragraph(lines: list[str]) -> str:
    """Join wrapped lines; keep list items on their own lines."""
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        if _BULLET.match(stripped):
            out.append("- " + _BULLET.sub("", stripped))
        elif _NUMBERED.match(stripped) and (not out or out[-1].startswith(("- ", "1"))
                                             or out[-1][:1].isdigit()):
            out.append(stripped)
        elif out and not out[-1].startswith("- ") and not out[-1][:1].isdigit():
            prev = out[-1]
            out[-1] = prev[:-1] + stripped if prev.endswith("-") else f"{prev} {stripped}"
        elif out and out[-1].startswith("- ") and stripped[:1].islower():
            out[-1] = f"{out[-1]} {stripped}"
        else:
            out.append(stripped)
    return "\n".join(out)


def _table_markdown(raw: list[list[str | None]]) -> str:
    rows = [[(c or "").replace("\n", " ").replace("|", "\\|").strip() for c in row]
            for row in raw if row]
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    lines = ["| " + " | ".join(rows[0]) + " |", "|" + "---|" * width]
    lines += ["| " + " | ".join(r) + " |" for r in rows[1:]]
    return "\n".join(lines)


# ---------------------------------------------------------------------------------------------
# PDF → PDF/A and grayscale (Ghostscript)


class PdfaLevel(StrEnum):
    A1B = "1"
    A2B = "2"
    A3B = "3"


PDFA_LABELS = {
    PdfaLevel.A1B: "PDF/A-1b · oldest, most widely accepted",
    PdfaLevel.A2B: "PDF/A-2b · recommended",
    PdfaLevel.A3B: "PDF/A-3b · allows embedded files",
}


@dataclass
class PdfaOptions:
    level: PdfaLevel = PdfaLevel.A2B
    password: str | None = None


def to_pdfa(inputs: list[Path], output: Path, opts: PdfaOptions | None = None,
            progress: ProgressFn = no_progress, cancel: Event | None = None) -> Result:
    """Archival PDF/A: fonts embedded, sRGB colour, an output intent and PDF/A metadata."""
    opts = opts or PdfaOptions()
    level = PdfaLevel(opts.level)
    gs = engines.require("gs")
    with tempfile.TemporaryDirectory(prefix="pdfsoul-pdfa-") as tmp_name:
        tmp = Path(tmp_name)
        src = _decrypted_copy(Path(inputs[0]), opts.password, tmp)
        converted = tmp / "pdfa.pdf"
        _run_gs(gs, src, converted, [
            f"-dPDFA={level.value}",
            "-dPDFACompatibilityPolicy=1",
            "-sColorConversionStrategy=RGB",
            "-sProcessColorModel=DeviceRGB",
            *(["-dCompatibilityLevel=1.4"] if level is PdfaLevel.A1B else []),
        ], progress, cancel)
        with pikepdf.open(converted) as pdf, atomic_output(Path(output)) as out:
            _add_output_intent(pdf)
            pdf.save(out)
    progress(1.0)
    return Result([Path(output)], f"Saved as PDF/A-{level.value}b for long-term archiving.")


def _add_output_intent(pdf: pikepdf.Pdf) -> None:
    if "/OutputIntents" in pdf.Root:
        return
    from PIL import ImageCms

    icc = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    profile = pikepdf.Stream(pdf, icc)
    profile["/N"] = 3
    pdf.Root["/OutputIntents"] = pikepdf.Array([pdf.make_indirect(pikepdf.Dictionary(
        Type=pikepdf.Name.OutputIntent,
        S=pikepdf.Name.GTS_PDFA1,
        OutputConditionIdentifier=pikepdf.String("sRGB IEC61966-2.1"),
        Info=pikepdf.String("sRGB IEC61966-2.1"),
        DestOutputProfile=pdf.make_indirect(profile),
    ))])


@dataclass
class GrayscaleOptions:
    password: str | None = None


def to_grayscale(inputs: list[Path], output: Path, opts: GrayscaleOptions | None = None,
                 progress: ProgressFn = no_progress, cancel: Event | None = None) -> Result:
    """Convert every colour to gray: cheaper printing, and often a smaller file."""
    opts = opts or GrayscaleOptions()
    source = Path(inputs[0])
    gs = engines.find("gs")
    with tempfile.TemporaryDirectory(prefix="pdfsoul-gray-") as tmp_name:
        tmp = Path(tmp_name)
        if gs is not None:
            src = _decrypted_copy(source, opts.password, tmp)
            with atomic_output(Path(output)) as out:
                _run_gs(gs, src, out, ["-sColorConversionStrategy=Gray",
                                       "-dProcessColorModel=/DeviceGray",
                                       "-dCompatibilityLevel=1.7"], progress, cancel)
        else:
            _mupdf_grayscale(source, Path(output), opts.password, progress, cancel)
    progress(1.0)
    return Result([Path(output)], "Converted to grayscale.")


def _mupdf_grayscale(source: Path, output: Path, password: str | None, progress: ProgressFn,
                     cancel: Event | None) -> None:
    """Without Ghostscript: rasterise each page in gray at 200 dpi (text stays searchable)."""
    from pdfsoul.core.document import save_pdf

    with open_pdf(source, password) as doc:
        out = fitz.open()
        tick = Progress(progress, cancel, doc.page_count)
        for page in doc:
            pix = page.get_pixmap(dpi=200, colorspace=fitz.csGRAY, alpha=False)
            new = out.new_page(width=page.rect.width, height=page.rect.height)
            new.insert_image(new.rect, stream=pix.tobytes("png"))
            tick.step()
        save_pdf(out, output)
        out.close()


_PAGE_LINE = re.compile(r"^Page (\d+)")
_TOTAL_LINE = re.compile(r"Processing pages \d+ through (\d+)")


def _run_gs(gs: Path, src: Path, dst: Path, extra: list[str], progress: ProgressFn,
            cancel: Event | None) -> None:
    total = [0]

    def on_line(line: str) -> None:
        if m := _TOTAL_LINE.search(line):
            total[0] = int(m.group(1))
        elif (m := _PAGE_LINE.match(line)) and total[0]:
            progress(0.05 + 0.85 * int(m.group(1)) / total[0])

    engines.run([str(gs), "-sDEVICE=pdfwrite", *extra, "-dNOPAUSE", "-dBATCH", "-dSAFER",
                 f"-sOutputFile={dst}", str(src)], cancel=cancel, on_line=on_line)
