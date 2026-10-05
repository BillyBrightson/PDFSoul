"""Stamping: text/image watermarks and page numbers.

Positions are worked out in the page's *visible* (rotated) space and converted to PDF space,
so stamps come out upright on rotated pages too.
"""

from __future__ import annotations

import io
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from threading import Event

import pymupdf as fitz
from PIL import Image

from pdfsoul.core.document import open_pdf, save_pdf
from pdfsoul.core.ranges import parse_page_set
from pdfsoul.core.types import PdfSoulError, Progress, ProgressFn, Result, no_progress


class Position(StrEnum):
    TOP_LEFT = "top-left"
    TOP_CENTER = "top-center"
    TOP_RIGHT = "top-right"
    MIDDLE_LEFT = "middle-left"
    CENTER = "center"
    MIDDLE_RIGHT = "middle-right"
    BOTTOM_LEFT = "bottom-left"
    BOTTOM_CENTER = "bottom-center"
    BOTTOM_RIGHT = "bottom-right"


@dataclass
class WatermarkOptions:
    text: str = ""
    image: Path | None = None  # used instead of text when set
    font_size: float = 72
    color: str = "#808080"
    opacity: float = 0.45
    angle: float = 45  # degrees, counter-clockwise
    position: Position = Position.CENTER
    image_scale: float = 0.5  # image width as a fraction of page width
    margin: float = 36
    pages: str = ""
    behind: bool = False  # draw under the page content instead of over it
    password: str | None = None


class NumberFormat(StrEnum):
    PLAIN = "{n}"
    OF_TOTAL = "{n} / {total}"
    PAGE_OF = "Page {n} of {total}"
    DASHED = "- {n} -"


@dataclass
class PageNumberOptions:
    fmt: str = NumberFormat.PLAIN.value  # any text with {n} and {total}
    position: Position = Position.BOTTOM_CENTER
    start: int = 1
    font_size: float = 11
    color: str = "#000000"
    margin: float = 28
    pages: str = ""
    password: str | None = None


# ---------------------------------------------------------------------------------------------
# File operations


def watermark(inputs: list[Path], output: Path, opts: WatermarkOptions,
              progress: ProgressFn = no_progress, cancel: Event | None = None) -> Result:
    _validate_watermark(opts)
    return _stamp_file(inputs, output, opts.password, opts.pages,
                       lambda doc, pages, tick: apply_watermark(doc, opts, pages, tick),
                       "Watermarked", progress, cancel)


def page_numbers(inputs: list[Path], output: Path, opts: PageNumberOptions,
                 progress: ProgressFn = no_progress, cancel: Event | None = None) -> Result:
    if "{n}" not in opts.fmt:
        raise PdfSoulError("The number format must contain {n}.")
    return _stamp_file(inputs, output, opts.password, opts.pages,
                       lambda doc, pages, tick: apply_page_numbers(doc, opts, pages, tick),
                       "Numbered", progress, cancel)


def preview(path: Path, password: str | None, page: int, dpi: int,
            stamp: WatermarkOptions | PageNumberOptions) -> bytes:
    """Render one page with the stamp applied (in memory only) as PNG bytes."""
    with open_pdf(path, password) as doc:
        page = max(0, min(page, doc.page_count - 1))
        if isinstance(stamp, WatermarkOptions):
            _validate_watermark(stamp)
            apply_watermark(doc, stamp, [page])
        else:
            selected = parse_page_set(stamp.pages, doc.page_count)
            if page in selected:
                apply_page_numbers(doc, stamp, selected, only=page)
        return doc[page].get_pixmap(dpi=dpi, alpha=False).tobytes("png")


def _stamp_file(inputs: list[Path], output: Path, password: str | None, spec: str,
                apply: Callable[[fitz.Document, list[int], Progress], None], verb: str,
                progress: ProgressFn, cancel: Event | None) -> Result:
    with open_pdf(Path(inputs[0]), password) as doc:
        pages = parse_page_set(spec, doc.page_count)
        tick = Progress(progress, cancel, len(pages) + 1)
        apply(doc, pages, tick)
        save_pdf(doc, output)
    tick.done()
    return Result([Path(output)], f"{verb} {len(pages)} pages.")


# ---------------------------------------------------------------------------------------------
# In-memory stamping


def apply_watermark(doc: fitz.Document, opts: WatermarkOptions, pages: list[int],
                    tick: Progress | None = None) -> None:
    image_png = _prepare_image(opts) if opts.image else None
    font = fitz.Font("helv")
    for p in pages:
        page = doc[p]
        if image_png is not None:
            _place_image(page, image_png, opts)
        else:
            _place_text(page, opts.text.splitlines() or [""], font, opts.font_size,
                        _rgb(opts.color), opts.opacity, opts.angle, opts.position, opts.margin,
                        overlay=not opts.behind)
        if tick:
            tick.step()


def apply_page_numbers(doc: fitz.Document, opts: PageNumberOptions, pages: list[int],
                       tick: Progress | None = None, only: int | None = None) -> None:
    font = fitz.Font("helv")
    total = opts.start + len(pages) - 1
    for i, p in enumerate(pages):
        if only is None or p == only:
            label = opts.fmt.replace("{n}", str(opts.start + i)).replace("{total}", str(total))
            _place_text(doc[p], [label], font, opts.font_size, _rgb(opts.color), 1.0, 0,
                        opts.position, opts.margin, overlay=True)
        if tick:
            tick.step()


def _place_text(page: fitz.Page, lines: list[str], font: fitz.Font, size: float,
                color: tuple[float, float, float], opacity: float, angle: float,
                position: Position, margin: float, overlay: bool) -> None:
    leading = size * 1.2
    widths = [font.text_length(line, fontsize=size) for line in lines]
    block_w, block_h = max(widths, default=0), leading * len(lines)
    # Footprint of the turned block, so it stays inside the margins.
    rotated = fitz.Rect(-block_w / 2, -block_h / 2, block_w / 2, block_h / 2) * fitz.Matrix(angle)
    centre = _anchor(page.rect, position, rotated.width, rotated.height, margin)

    # TextWriter works in the page's unrotated space: lay the block out horizontally around the
    # mapped centre, then turn it by the stamp angle plus the page rotation so it reads upright.
    pivot = centre * page.derotation_matrix
    writer = fitz.TextWriter(page.rect, opacity=opacity, color=color)
    top = pivot.y - block_h / 2
    for i, (line, width) in enumerate(zip(lines, widths, strict=True)):
        baseline = top + i * leading + size * 0.95
        writer.append(fitz.Point(pivot.x - width / 2, baseline), line, font=font, fontsize=size)
    turn = (angle + page.rotation) % 360
    writer.write_text(page, overlay=overlay,
                      morph=(pivot, fitz.Matrix(turn)) if turn else None)


def _place_image(page: fitz.Page, png: bytes, opts: WatermarkOptions) -> None:
    with Image.open(io.BytesIO(png)) as img:
        aspect = img.height / img.width
    width = page.rect.width * max(0.05, min(opts.image_scale, 1.0))
    height = width * aspect
    if height > page.rect.height - 2 * opts.margin:
        height = max(page.rect.height - 2 * opts.margin, 10)
        width = height / aspect
    centre = _anchor(page.rect, opts.position, width, height, opts.margin)
    visible = fitz.Rect(centre.x - width / 2, centre.y - height / 2,
                        centre.x + width / 2, centre.y + height / 2)
    target = (visible * page.derotation_matrix).normalize()
    page.insert_image(target, stream=png, overlay=not opts.behind, rotate=page.rotation)


def _prepare_image(opts: WatermarkOptions) -> bytes:
    """Apply opacity and rotation with Pillow (PDF images can't be rotated freely)."""
    assert opts.image is not None
    try:
        img = Image.open(opts.image).convert("RGBA")
    except Exception as exc:
        raise PdfSoulError(f"Couldn't read image {Path(opts.image).name}: {exc}") from exc
    alpha = img.getchannel("A").point(lambda a: round(a * max(0.0, min(opts.opacity, 1.0))))
    img.putalpha(alpha)
    if opts.angle % 360:
        img = img.rotate(opts.angle, expand=True, resample=Image.Resampling.BICUBIC)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _anchor(page_rect: fitz.Rect, position: Position, w: float, h: float,
            margin: float) -> fitz.Point:
    """Centre point of a ``w``×``h`` box placed at ``position`` inside the page margins."""
    position = Position(position)  # UI widgets may hand back the plain string value
    vertical, _, horizontal = position.value.partition("-")
    if position is Position.CENTER:
        vertical, horizontal = "middle", "center"
    x = {
        "left": page_rect.x0 + margin + w / 2,
        "center": page_rect.x0 + page_rect.width / 2,
        "right": page_rect.x1 - margin - w / 2,
    }[horizontal]
    y = {
        "top": page_rect.y0 + margin + h / 2,
        "middle": page_rect.y0 + page_rect.height / 2,
        "bottom": page_rect.y1 - margin - h / 2,
    }[vertical]
    return fitz.Point(x, y)


def _rgb(color: str) -> tuple[float, float, float]:
    value = color.strip().lstrip("#")
    if len(value) == 3:
        value = "".join(c * 2 for c in value)
    try:
        r, g, b = (int(value[i:i + 2], 16) / 255 for i in (0, 2, 4))
    except (ValueError, IndexError):
        raise PdfSoulError(f"'{color}' is not a colour like #808080.") from None
    return r, g, b


def _validate_watermark(opts: WatermarkOptions) -> None:
    if not opts.image and not opts.text.strip():
        raise PdfSoulError("Enter watermark text or choose an image.")
    if opts.image and not Path(opts.image).is_file():
        raise PdfSoulError(f"Image not found: {opts.image}")
