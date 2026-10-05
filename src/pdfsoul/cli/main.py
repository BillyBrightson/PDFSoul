"""``pdfsoul`` command line: the same core operations as the desktop app.

Exit codes: 0 success, 1 the operation failed, 2 bad usage, 130 cancelled (Ctrl+C).
"""

from __future__ import annotations

import re
import sys
from collections.abc import Callable
from enum import StrEnum
from pathlib import Path
from threading import Event
from typing import Annotated, Any

import typer

from pdfsoul import __version__
from pdfsoul.core import (
    convert,
    document,
    edit,
    engines,
    export,
    ocr,
    optimise,
    organise,
    secure,
    to_pdf,
)
from pdfsoul.core.safe_io import derive_output, same_file, unique_path
from pdfsoul.core.types import Cancelled, PasswordRequired, PdfSoulError, Result

app = typer.Typer(
    name="pdfsoul",
    help="PDFSoul By Billy — offline PDF tools. Files never leave your computer.",
    no_args_is_help=True,
    add_completion=False,
    pretty_exceptions_enable=False,
)

Input = Annotated[Path, typer.Argument(exists=True, dir_okay=False, readable=True,
                                       help="Input PDF.")]
OutputFile = Annotated[Path | None, typer.Option("--output", "-o",
                                                  help="Output file (default: name_<tool>.pdf).")]
OutputDir = Annotated[Path | None, typer.Option("--output", "-o", file_okay=False,
                                                 help="Output folder (default: beside input).")]
Password = Annotated[str | None, typer.Option("--password", "-p",
                                               help="Password, if the input is encrypted.")]
Pages = Annotated[str, typer.Option("--pages", help="Pages, e.g. 1-3,5,8- (blank = all).")]
Overwrite = Annotated[bool, typer.Option("--overwrite", help="Allow writing over the input file.")]


def _version(value: bool) -> None:
    if value:
        typer.echo(f"pdfsoul {__version__}")
        raise typer.Exit()


@app.callback()
def _main(
    version: Annotated[bool, typer.Option("--version", callback=_version, is_eager=True,
                                          help="Show the version and exit.")] = False,
) -> None:
    pass


# ---------------------------------------------------------------------------------------------
# Plumbing


def _output_for(source: Path, given: Path | None, tag: str, ext: str = ".pdf",
                overwrite: bool = False) -> Path:
    if given is None:
        return unique_path(derive_output(source, tag, ext))
    if same_file(given, source) and not overwrite:
        _fail("Refusing to overwrite the input file. Pass --overwrite to allow it.", code=2)
    return given


def _run(op: Callable[..., Result], inputs: list[Path], output: Path, opts: Any,
         password_field: str | None = "password") -> None:
    """Run an operation with a progress bar; prompt for a password once if one is needed."""
    cancel = Event()
    for attempt in range(2):
        try:
            with typer.progressbar(length=1000, label="Working", show_eta=False,
                                   file=sys.stderr) as bar:
                done = [0]

                def tick(fraction: float, bar: Any = bar, done: list[int] = done) -> None:
                    target = int(fraction * 1000)
                    if target > done[0]:
                        bar.update(target - done[0])
                        done[0] = target

                result = op(inputs, output, opts, tick, cancel)
            break
        except PasswordRequired as exc:
            if attempt or password_field is None or not sys.stdin.isatty():
                _fail(f"{exc} Pass it with --password.")
            setattr(opts, password_field, typer.prompt("Password", hide_input=True))
        except KeyboardInterrupt:
            cancel.set()
            _fail("Cancelled.", code=130)
        except Cancelled:
            _fail("Cancelled.", code=130)
        except PdfSoulError as exc:
            _fail(str(exc))
    typer.echo(result.message)
    for path in result.outputs[:20]:
        typer.echo(f"  → {path}")
    if len(result.outputs) > 20:
        typer.echo(f"  … and {len(result.outputs) - 20} more in {result.outputs[0].parent}")


def _fail(message: str, code: int = 1) -> None:
    typer.secho(f"Error: {message}", fg=typer.colors.RED, err=True)
    raise typer.Exit(code)


_MERGE_ITEM = re.compile(r"^(?P<path>.+\.pdf):(?P<pages>[\d,\s-]+|end)$", re.IGNORECASE)


# ---------------------------------------------------------------------------------------------
# Organise


@app.command()
def merge(
    files: Annotated[list[str], typer.Argument(help="PDFs in order. Add :RANGE to take only "
                                                    "some pages, e.g. report.pdf:1-3,7")],
    output: Annotated[Path, typer.Option("--output", "-o", help="Merged PDF.")] = Path(
        "merged.pdf"),
    no_bookmarks: Annotated[bool, typer.Option("--no-bookmarks")] = False,
) -> None:
    """Merge PDFs into one, in the order given."""
    paths, ranges = [], []
    for item in files:
        m = _MERGE_ITEM.match(item)
        path, spec = (Path(m["path"]), m["pages"]) if m and not Path(item).exists() else (
            Path(item), "")
        if not path.is_file():
            _fail(f"File not found: {path}", code=2)
        paths.append(path)
        ranges.append(spec)
    if any(same_file(p, output) for p in paths):
        _fail("The output can't be one of the inputs.", code=2)
    _run(organise.merge, paths, output,
         organise.MergeOptions(page_ranges=ranges, bookmarks=not no_bookmarks),
         password_field=None)


@app.command()
def split(
    file: Input,
    output: OutputDir = None,
    mode: Annotated[organise.SplitMode, typer.Option(help="How to split.")] = (
        organise.SplitMode.EACH_PAGE),
    ranges: Annotated[str, typer.Option(help="For --mode ranges: 1-3,4-6,7-")] = "",
    every: Annotated[int, typer.Option(help="For --mode every: pages per file.")] = 1,
    password: Password = None,
) -> None:
    """Split a PDF into several files."""
    folder = output or file.parent / f"{file.stem}_split"
    _run(organise.split, [file], folder,
         organise.SplitOptions(mode=mode, ranges=ranges, every=every, password=password))


@app.command()
def rotate(file: Input, pages: Pages = "", angle: Annotated[int, typer.Option(
        help="Degrees clockwise: 90, 180 or 270.")] = 90, output: OutputFile = None,
           password: Password = None, overwrite: Overwrite = False) -> None:
    """Rotate pages."""
    _run(organise.rotate, [file], _output_for(file, output, "rotated", overwrite=overwrite),
         organise.RotateOptions(pages=pages, angle=angle, password=password))


@app.command()
def delete(file: Input, pages: Annotated[str, typer.Option("--pages", help="Pages to delete.")],
           output: OutputFile = None, password: Password = None,
           overwrite: Overwrite = False) -> None:
    """Delete pages."""
    _run(organise.delete_pages, [file], _output_for(file, output, "edited", overwrite=overwrite),
         organise.PagesOptions(pages=pages, password=password))


@app.command()
def extract(file: Input, pages: Annotated[str, typer.Option("--pages", help="Pages to keep.")],
            output: OutputFile = None, password: Password = None) -> None:
    """Copy some pages into a new PDF."""
    _run(organise.extract_pages, [file], _output_for(file, output, "extract"),
         organise.PagesOptions(pages=pages, password=password))


@app.command()
def reorder(file: Input, order: Annotated[str, typer.Option(
        help="New order, e.g. 3,1,2 (unlisted pages follow).")], output: OutputFile = None,
            password: Password = None, overwrite: Overwrite = False) -> None:
    """Reorder pages."""
    _run(organise.reorder, [file], _output_for(file, output, "reordered", overwrite=overwrite),
         organise.PagesOptions(pages=order, password=password))


@app.command("insert-blank")
def insert_blank(file: Input, after: Annotated[int, typer.Option(
        help="Insert after this page (0 = at the start).")] = 0, count: int = 1,
                 output: OutputFile = None, password: Password = None,
                 overwrite: Overwrite = False) -> None:
    """Insert blank pages."""
    _run(organise.insert_blank, [file], _output_for(file, output, "edited", overwrite=overwrite),
         organise.InsertBlankOptions(after=after, count=count, password=password))


@app.command()
def duplicate(file: Input, pages: Annotated[str, typer.Option("--pages")],
              output: OutputFile = None, password: Password = None,
              overwrite: Overwrite = False) -> None:
    """Duplicate pages (each copy goes right after its original)."""
    _run(organise.duplicate_pages, [file],
         _output_for(file, output, "edited", overwrite=overwrite),
         organise.PagesOptions(pages=pages, password=password))


# ---------------------------------------------------------------------------------------------
# Optimise


@app.command()
def compress(
    file: Input,
    preset: Annotated[optimise.CompressPreset, typer.Option(
        help="low = smallest file, medium = recommended, high = best quality.")] = (
        optimise.CompressPreset.MEDIUM),
    output: OutputFile = None,
    password: Password = None,
    no_ghostscript: Annotated[bool, typer.Option(help="Use the built-in engine only.")] = False,
    overwrite: Overwrite = False,
) -> None:
    """Make a PDF smaller."""
    _run(optimise.compress, [file], _output_for(file, output, "compressed", overwrite=overwrite),
         optimise.CompressOptions(preset=preset, password=password,
                                  use_ghostscript=not no_ghostscript))


@app.command()
def repair(file: Input, output: OutputFile = None, password: Password = None) -> None:
    """Rebuild a damaged PDF."""
    _run(optimise.repair, [file], _output_for(file, output, "repaired"),
         optimise.RepairOptions(password=password))


# ---------------------------------------------------------------------------------------------
# Convert


@app.command("images-to-pdf")
def images_to_pdf(
    images: Annotated[list[Path], typer.Argument(exists=True, dir_okay=False)],
    output: Annotated[Path, typer.Option("--output", "-o")] = Path("images.pdf"),
    page_size: Annotated[convert.PageSize, typer.Option()] = convert.PageSize.FIT,
    margin: Annotated[float, typer.Option(help="Margin in points (72 = 1 inch).")] = 0,
) -> None:
    """Make a PDF from images (JPG, PNG, HEIC, TIFF…), one per page."""
    _run(convert.images_to_pdf, images, output,
         convert.ImagesToPdfOptions(page_size=page_size, margin_pt=margin), password_field=None)


@app.command("to-images")
def to_images(
    file: Input,
    output: OutputDir = None,
    fmt: Annotated[convert.ImageFormat, typer.Option("--format")] = convert.ImageFormat.PNG,
    dpi: Annotated[int, typer.Option(min=72, max=600)] = 150,
    pages: Pages = "",
    password: Password = None,
) -> None:
    """Save pages as PNG or JPG images."""
    _run(convert.pdf_to_images, [file], output or file.parent / f"{file.stem}_images",
         convert.PdfToImagesOptions(fmt=fmt, dpi=dpi, pages=pages, password=password))


@app.command()
def text(file: Input, output: OutputFile = None, pages: Pages = "",
         password: Password = None) -> None:
    """Extract text to a .txt file."""
    _run(convert.extract_text, [file], _output_for(file, output, "text", ".txt"),
         convert.ExtractTextOptions(pages=pages, password=password))


class Target(StrEnum):
    DOCX = "docx"
    XLSX = "xlsx"
    PPTX = "pptx"
    HTML = "html"
    MD = "md"
    TXT = "txt"
    PDFA = "pdfa"
    GRAY = "gray"
    PNG = "png"
    JPG = "jpg"
    WEBP = "webp"
    TIFF = "tiff"
    SVG = "svg"


@app.command("convert")
def convert_cmd(
    file: Input,
    to: Annotated[Target, typer.Option("--to", "-t", help="Target format.")],
    output: Annotated[Path | None, typer.Option(
        "--output", "-o", help="Output file, or folder for image formats.")] = None,
    pages: Pages = "",
    dpi: Annotated[int, typer.Option(help="Image formats and PowerPoint slides.")] = 150,
    html_mode: Annotated[export.HtmlMode, typer.Option(help="HTML layout.")] = (
        export.HtmlMode.REFLOW),
    excel_mode: Annotated[export.ExcelMode, typer.Option(help="Excel sheets.")] = (
        export.ExcelMode.TABLES),
    pdfa_level: Annotated[export.PdfaLevel, typer.Option(help="PDF/A part.")] = (
        export.PdfaLevel.A2B),
    password: Password = None,
) -> None:
    """Convert a PDF to Word, Excel, PowerPoint, HTML, Markdown, text, PDF/A or images."""
    images = {Target.PNG, Target.JPG, Target.WEBP, Target.TIFF, Target.SVG}
    if to in images:
        _run(convert.pdf_to_images, [file], output or file.parent / f"{file.stem}_images",
             convert.PdfToImagesOptions(fmt=convert.ImageFormat(to.value), dpi=dpi,
                                        pages=pages, password=password))
        return
    ops: dict[Target, tuple[Callable[..., Result], str, str, Any]] = {
        Target.DOCX: (export.pdf_to_word, "word", ".docx",
                      export.PdfToWordOptions(pages=pages, password=password)),
        Target.XLSX: (export.pdf_to_excel, "excel", ".xlsx",
                      export.PdfToExcelOptions(pages=pages, mode=excel_mode, password=password)),
        Target.PPTX: (export.pdf_to_powerpoint, "slides", ".pptx",
                      export.PdfToPowerPointOptions(pages=pages, dpi=max(72, min(dpi, 400)),
                                                    password=password)),
        Target.HTML: (export.pdf_to_html, "web", ".html",
                      export.PdfToHtmlOptions(pages=pages, mode=html_mode, password=password)),
        Target.MD: (export.pdf_to_markdown, "markdown", ".md",
                    export.PdfToMarkdownOptions(pages=pages, password=password)),
        Target.TXT: (convert.extract_text, "text", ".txt",
                     convert.ExtractTextOptions(pages=pages, password=password)),
        Target.PDFA: (export.to_pdfa, "pdfa", ".pdf",
                      export.PdfaOptions(level=pdfa_level, password=password)),
        Target.GRAY: (export.to_grayscale, "gray", ".pdf",
                      export.GrayscaleOptions(password=password)),
    }
    op, tag, ext, opts = ops[to]
    _run(op, [file], _output_for(file, output, tag, ext), opts)


@app.command("to-pdf")
def to_pdf_cmd(
    files: Annotated[list[Path], typer.Argument(exists=True, dir_okay=False, help=(
        "Word, Excel, PowerPoint, OpenDocument, HTML, Markdown, text, ePub, XPS or images."))],
    output: Annotated[Path | None, typer.Option(
        "--output", "-o", help="Output PDF (or folder with --separate).")] = None,
    separate: Annotated[bool, typer.Option(help="One PDF per input instead of one merged PDF."
                                           )] = False,
    paper: Annotated[str, typer.Option(help="a4 or letter (text, HTML, eBooks).")] = "a4",
    landscape: bool = False,
    no_libreoffice: Annotated[bool, typer.Option(
        help="Use the built-in Office renderer even if LibreOffice is installed.")] = False,
) -> None:
    """Convert documents to PDF."""
    if separate:
        target = output or files[0].parent
    else:
        target = output or unique_path(files[0].with_suffix(".pdf"))
    _run(to_pdf.to_pdf, files, target,
         to_pdf.ToPdfOptions(merge=not separate, paper=paper, landscape=landscape,
                             use_libreoffice=not no_libreoffice), password_field=None)


@app.command("ocr")
def ocr_cmd(
    file: Input,
    lang: Annotated[str, typer.Option(help="Tesseract language(s), e.g. eng or eng+fra.")] = (
        "eng"),
    dpi: Annotated[int, typer.Option(min=150, max=600)] = 300,
    pages: Pages = "",
    force: Annotated[bool, typer.Option(help="OCR pages that already have text too.")] = False,
    output: OutputFile = None,
    password: Password = None,
) -> None:
    """Make a scanned PDF searchable (needs Tesseract)."""
    _run(ocr.ocr, [file], _output_for(file, output, "ocr"),
         ocr.OcrOptions(language=lang, dpi=dpi, pages=pages, skip_text_pages=not force,
                        password=password))


@app.command()
def images(file: Input, output: OutputDir = None, pages: Pages = "",
           min_size: Annotated[int, typer.Option(help="Skip images smaller than this (px).")] = 32,
           password: Password = None) -> None:
    """Extract embedded images."""
    _run(convert.extract_images, [file], output or file.parent / f"{file.stem}_extracted",
         convert.ExtractImagesOptions(pages=pages, min_size_px=min_size, password=password))


# ---------------------------------------------------------------------------------------------
# Edit


@app.command()
def watermark(
    file: Input,
    text_: Annotated[str, typer.Option("--text", help="Watermark text.")] = "",
    image: Annotated[Path | None, typer.Option(exists=True, dir_okay=False,
                                               help="Watermark image instead of text.")] = None,
    opacity: Annotated[float, typer.Option(min=0.0, max=1.0)] = 0.45,
    angle: float = 45,
    position: edit.Position = edit.Position.CENTER,
    font_size: float = 72,
    color: str = "#808080",
    scale: Annotated[float, typer.Option(help="Image width as a fraction of the page.")] = 0.5,
    behind: Annotated[bool, typer.Option(help="Put it under the page content.")] = False,
    pages: Pages = "",
    output: OutputFile = None,
    password: Password = None,
) -> None:
    """Stamp a text or image watermark."""
    _run(edit.watermark, [file], _output_for(file, output, "watermarked"),
         edit.WatermarkOptions(text=text_, image=image, opacity=opacity, angle=angle,
                               position=position, font_size=font_size, color=color,
                               image_scale=scale, behind=behind, pages=pages,
                               password=password))


@app.command()
def number(
    file: Input,
    fmt: Annotated[str, typer.Option("--format", help="Use {n} and {total}.")] = "{n}",
    position: edit.Position = edit.Position.BOTTOM_CENTER,
    start: int = 1,
    font_size: float = 11,
    pages: Pages = "",
    output: OutputFile = None,
    password: Password = None,
) -> None:
    """Add page numbers."""
    _run(edit.page_numbers, [file], _output_for(file, output, "numbered"),
         edit.PageNumberOptions(fmt=fmt, position=position, start=start, font_size=font_size,
                                pages=pages, password=password))


# ---------------------------------------------------------------------------------------------
# Secure


@app.command()
def protect(
    file: Input,
    password: Annotated[str, typer.Option(prompt=True, hide_input=True,
                                          confirmation_prompt=True,
                                          help="Password needed to open the file.")],
    owner_password: Annotated[str, typer.Option(help="Password to change permissions.")] = "",
    no_print: bool = False,
    no_copy: bool = False,
    no_edit: bool = False,
    output: OutputFile = None,
) -> None:
    """Encrypt with AES-256 and a password."""
    _run(secure.protect, [file], _output_for(file, output, "protected"),
         secure.ProtectOptions(user_password=password, owner_password=owner_password,
                               allow_print=not no_print, allow_copy=not no_copy,
                               allow_edit=not no_edit),
         password_field="current_password")


@app.command()
def unlock(
    file: Input,
    password: Annotated[str, typer.Option(prompt=True, hide_input=True)],
    output: OutputFile = None,
) -> None:
    """Remove a known password."""
    _run(secure.unlock, [file], _output_for(file, output, "unlocked"),
         secure.UnlockOptions(password=password), password_field=None)


# ---------------------------------------------------------------------------------------------
# Info


@app.command()
def info(file: Input, password: Password = None) -> None:
    """Show page count, size, metadata and protection."""
    try:
        facts = document.info(file, password)
    except PdfSoulError as exc:
        _fail(str(exc))
    w, h = facts.first_page_size_pt
    typer.echo(f"File:       {facts.path}")
    typer.echo(f"Size:       {optimise.human_size(facts.size_bytes)}")
    typer.echo(f"Pages:      {facts.pages}  (first page {w:g} × {h:g} pt)")
    typer.echo(f"Encrypted:  {'yes' if facts.encrypted else 'no'}")
    typer.echo(f"Bookmarks:  {facts.bookmarks}")
    typer.echo(f"Form fields: {facts.form_fields}")
    for key, value in facts.metadata.items():
        typer.echo(f"{key.capitalize() + ':':<12}{value}")


@app.command("engines")
def show_engines() -> None:
    """Show which external engines were found."""
    for name, label in engines.LABELS.items():
        path = engines.find(name)
        typer.echo(f"{label:<14}{path or 'not found'}")


if __name__ == "__main__":
    app()
