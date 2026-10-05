"""Images ↔ PDF, and text/image extraction."""

from __future__ import annotations

import io
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from threading import Event

import pymupdf as fitz
from PIL import Image, ImageOps

from pdfsoul.core.document import open_pdf, save_pdf
from pdfsoul.core.ranges import parse_pages
from pdfsoul.core.safe_io import atomic_output
from pdfsoul.core.types import PdfSoulError, Progress, ProgressFn, Result, no_progress

try:  # HEIC/HEIF support is optional
    from pillow_heif import register_heif_opener

    register_heif_opener()
    HEIC_SUPPORTED = True
except ImportError:  # pragma: no cover
    HEIC_SUPPORTED = False

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".tif", ".tiff", ".webp"}
if HEIC_SUPPORTED:
    IMAGE_EXTENSIONS |= {".heic", ".heif"}

PAGE_SIZES = {"a4": (595.0, 842.0), "letter": (612.0, 792.0)}


# ---------------------------------------------------------------------------------------------
# Images → PDF


class PageSize(StrEnum):
    FIT = "fit"  # page is the image's size
    A4 = "a4"
    LETTER = "letter"


@dataclass
class ImagesToPdfOptions:
    page_size: PageSize = PageSize.FIT
    margin_pt: float = 0.0
    jpeg_quality: int = 90


def images_to_pdf(inputs: list[Path], output: Path, opts: ImagesToPdfOptions | None = None,
                  progress: ProgressFn = no_progress, cancel: Event | None = None) -> Result:
    """One page per image (every frame of a multi-page TIFF), in the order given."""
    opts = opts or ImagesToPdfOptions()
    if not inputs:
        raise PdfSoulError("Add at least one image.")
    page_size = PageSize(opts.page_size)
    tick = Progress(progress, cancel, len(inputs) + 1)
    out = fitz.open()
    for path in inputs:
        for frame in _frames(Path(path)):
            data, width_px, height_px, dpi = _encode(frame, opts.jpeg_quality)
            img_w, img_h = width_px * 72 / dpi, height_px * 72 / dpi
            if page_size is PageSize.FIT:
                page_w, page_h = img_w + 2 * opts.margin_pt, img_h + 2 * opts.margin_pt
            else:
                page_w, page_h = PAGE_SIZES[page_size.value]
                if (img_w > img_h) != (page_w > page_h):
                    page_w, page_h = page_h, page_w  # match the image's orientation
            page = out.new_page(width=page_w, height=page_h)
            m = opts.margin_pt
            box = fitz.Rect(m, m, page_w - m, page_h - m)
            page.insert_image(box, stream=data, keep_proportion=True)
        tick.step()
    save_pdf(out, output)
    count = out.page_count
    out.close()
    tick.done()
    return Result([Path(output)], f"Made a {count}-page PDF from {len(inputs)} images.")


def _frames(path: Path) -> list[Image.Image]:
    try:
        img = Image.open(path)
    except Exception as exc:
        raise PdfSoulError(f"Couldn't read image {path.name}: {exc}") from exc
    frames = []
    for i in range(getattr(img, "n_frames", 1)):
        img.seek(i)
        frames.append(ImageOps.exif_transpose(img.copy()) or img.copy())
        if path.suffix.lower() in {".gif", ".webp"}:
            break  # animations: first frame only
    return frames


def _encode(img: Image.Image, quality: int) -> tuple[bytes, int, int, float]:
    """Encode as JPEG (photos) or PNG (transparency/palette/line art). Returns bytes, size, dpi."""
    dpi = img.info.get("dpi", (96, 96))[0] or 96
    dpi = float(dpi) if 30 <= float(dpi) <= 1200 else 96.0
    buf = io.BytesIO()
    if img.mode in {"RGBA", "LA", "P", "1"} or img.format == "PNG":
        if img.mode == "P":
            img = img.convert("RGBA")
        img.save(buf, format="PNG", optimize=True)
    else:
        if img.mode not in {"RGB", "L", "CMYK"}:
            img = img.convert("RGB")
        img.save(buf, format="JPEG", quality=quality, optimize=True)
    return buf.getvalue(), img.width, img.height, dpi


# ---------------------------------------------------------------------------------------------
# PDF → images


class ImageFormat(StrEnum):
    PNG = "png"
    JPG = "jpg"
    WEBP = "webp"
    TIFF = "tiff"
    SVG = "svg"  # vector: text and shapes stay sharp at any zoom; dpi is ignored


@dataclass
class PdfToImagesOptions:
    fmt: ImageFormat = ImageFormat.PNG
    dpi: int = 150
    pages: str = ""
    jpeg_quality: int = 90
    password: str | None = None


def pdf_to_images(inputs: list[Path], output: Path, opts: PdfToImagesOptions | None = None,
                  progress: ProgressFn = no_progress, cancel: Event | None = None) -> Result:
    """Render pages to image files named ``name_p001.png`` in folder ``output``."""
    opts = opts or PdfToImagesOptions()
    if not 72 <= opts.dpi <= 600:
        raise PdfSoulError("DPI must be between 72 and 600.")
    source, folder = Path(inputs[0]), Path(output)
    folder.mkdir(parents=True, exist_ok=True)
    fmt = ImageFormat(opts.fmt)
    written: list[Path] = []
    with open_pdf(source, opts.password) as doc:
        pages = parse_pages(opts.pages, doc.page_count)
        width = len(str(doc.page_count))
        tick = Progress(progress, cancel, len(pages))
        for p in pages:
            target = folder / f"{source.stem}_p{p + 1:0{max(width, 3)}d}.{fmt.value}"
            with atomic_output(target) as tmp:
                if fmt is ImageFormat.SVG:
                    tmp.write_text(doc[p].get_svg_image(text_as_path=False), encoding="utf-8")
                else:
                    _save_pixmap(doc[p].get_pixmap(dpi=opts.dpi, alpha=False), tmp, fmt, opts)
            written.append(target)
            tick.step()
    detail = "" if fmt is ImageFormat.SVG else f" at {opts.dpi} dpi"
    return Result(written, f"Saved {len(written)} {fmt.value.upper()} images{detail}.")


def _save_pixmap(pix: fitz.Pixmap, path: Path, fmt: ImageFormat,
                 opts: PdfToImagesOptions) -> None:
    dpi = (opts.dpi, opts.dpi)
    if fmt is ImageFormat.PNG:
        pix.set_dpi(opts.dpi, opts.dpi)
        pix.save(path, output="png")
    elif fmt is ImageFormat.JPG:
        pix.pil_save(path, format="JPEG", quality=opts.jpeg_quality, optimize=True, dpi=dpi)
    elif fmt is ImageFormat.WEBP:
        pix.pil_save(path, format="WEBP", quality=opts.jpeg_quality, method=4)
    else:
        pix.pil_save(path, format="TIFF", compression="tiff_lzw", dpi=dpi)


# ---------------------------------------------------------------------------------------------
# Extraction


@dataclass
class ExtractTextOptions:
    pages: str = ""
    page_breaks: bool = True
    password: str | None = None


def extract_text(inputs: list[Path], output: Path, opts: ExtractTextOptions | None = None,
                 progress: ProgressFn = no_progress, cancel: Event | None = None) -> Result:
    """Write the text of the chosen pages to a UTF-8 .txt file."""
    opts = opts or ExtractTextOptions()
    chunks: list[str] = []
    words = 0
    with open_pdf(Path(inputs[0]), opts.password) as doc:
        pages = parse_pages(opts.pages, doc.page_count)
        tick = Progress(progress, cancel, len(pages))
        for p in pages:
            text = doc[p].get_text("text", sort=True).rstrip()
            words += len(text.split())
            chunks.append(f"--- Page {p + 1} ---\n{text}\n" if opts.page_breaks else text + "\n")
            tick.step()
    body = "\n".join(chunks)
    with atomic_output(Path(output)) as tmp:
        tmp.write_text(body, encoding="utf-8")
    note = "" if words >= len(pages) * 5 else " Little text found — this may be a scanned PDF."
    return Result([Path(output)], f"Extracted {words:,} words from {len(pages)} pages.{note}")


@dataclass
class ExtractImagesOptions:
    pages: str = ""
    min_size_px: int = 32
    password: str | None = None


def extract_images(inputs: list[Path], output: Path, opts: ExtractImagesOptions | None = None,
                   progress: ProgressFn = no_progress, cancel: Event | None = None) -> Result:
    """Save each embedded image once, in its original format, into folder ``output``."""
    opts = opts or ExtractImagesOptions()
    source, folder = Path(inputs[0]), Path(output)
    folder.mkdir(parents=True, exist_ok=True)
    seen: set[int] = set()
    written: list[Path] = []
    with open_pdf(source, opts.password) as doc:
        pages = parse_pages(opts.pages, doc.page_count)
        tick = Progress(progress, cancel, len(pages))
        for p in pages:
            for n, info in enumerate(doc[p].get_images(full=True), start=1):
                xref = info[0]
                if xref in seen:
                    continue
                seen.add(xref)
                img = doc.extract_image(xref)
                if not img or min(img["width"], img["height"]) < opts.min_size_px:
                    continue
                data, ext = img["image"], img["ext"]
                if img.get("smask"):  # re-attach transparency so the file looks right
                    data, ext = _with_alpha(doc, xref, img["smask"]), "png"
                elif ext not in {"jpeg", "jpg", "png", "jpx", "bmp", "tiff", "gif"}:
                    data, ext = fitz.Pixmap(doc, xref).tobytes("png"), "png"
                target = folder / f"{source.stem}_p{p + 1}_img{n}.{ext}"
                with atomic_output(target) as tmp:
                    tmp.write_bytes(data)
                written.append(target)
            tick.step()
    if not written:
        return Result([], "No images found in the chosen pages.")
    return Result(written, f"Saved {len(written)} images.")


def _with_alpha(doc: fitz.Document, xref: int, smask: int) -> bytes:
    base = fitz.Pixmap(doc, xref)
    mask = fitz.Pixmap(doc, smask)
    if base.alpha:
        base = fitz.Pixmap(base, 0)
    if base.n - base.alpha > 3:  # CMYK → RGB before adding alpha
        base = fitz.Pixmap(fitz.csRGB, base)
    try:
        return fitz.Pixmap(base, mask).tobytes("png")
    except Exception:
        return base.tobytes("png")
