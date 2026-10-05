"""Compression and repair.

Compression runs Ghostscript (image downsampling) when it is available, then a lossless
pikepdf pass. Without Ghostscript it falls back to MuPDF's image rewriting. The result is only
kept if it is actually smaller than the original.
"""

from __future__ import annotations

import contextlib
import re
import tempfile
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from threading import Event

import pikepdf
import pymupdf as fitz

from pdfsoul.core import engines
from pdfsoul.core.document import open_pdf, repair_bytes
from pdfsoul.core.safe_io import atomic_output
from pdfsoul.core.types import (
    PasswordRequired,
    PdfSoulError,
    ProgressFn,
    Result,
    WrongPassword,
    check_cancel,
    no_progress,
)


class CompressPreset(StrEnum):
    """Output quality. LOW gives the smallest file; HIGH keeps print quality."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


GS_SETTINGS = {CompressPreset.LOW: "/screen", CompressPreset.MEDIUM: "/ebook",
               CompressPreset.HIGH: "/printer"}
TARGET_DPI = {CompressPreset.LOW: 72, CompressPreset.MEDIUM: 150, CompressPreset.HIGH: 300}
JPEG_QUALITY = {CompressPreset.LOW: 50, CompressPreset.MEDIUM: 70, CompressPreset.HIGH: 85}
PRESET_LABELS = {
    CompressPreset.LOW: "Low quality · smallest file (72 dpi)",
    CompressPreset.MEDIUM: "Medium · recommended (150 dpi)",
    CompressPreset.HIGH: "High quality · light compression (300 dpi)",
}


@dataclass
class CompressOptions:
    preset: CompressPreset = CompressPreset.MEDIUM
    password: str | None = None
    use_ghostscript: bool = True


def compress(inputs: list[Path], output: Path, opts: CompressOptions | None = None,
             progress: ProgressFn = no_progress, cancel: Event | None = None) -> Result:
    opts = opts or CompressOptions()
    preset = CompressPreset(opts.preset)
    source = Path(inputs[0])
    before = source.stat().st_size
    with tempfile.TemporaryDirectory(prefix="pdfsoul-") as tmp_dir:
        tmp = Path(tmp_dir)
        stage = _decrypted_copy(source, opts.password, tmp)
        progress(0.05)

        gs = engines.find("gs") if opts.use_ghostscript else None
        shrunk = tmp / "shrunk.pdf"
        if gs is not None:
            _ghostscript(gs, stage, shrunk, preset, progress, cancel)
            engine = "Ghostscript"
        else:
            _mupdf_shrink(stage, shrunk, preset)
            engine = "MuPDF"
        check_cancel(cancel)
        progress(0.85)

        candidates = [tmp / "final.pdf", tmp / "lossless.pdf"]
        _lossless(shrunk, candidates[0])
        check_cancel(cancel)
        if candidates[0].stat().st_size >= before:
            # Downsampling didn't help (already-optimised file); try lossless only.
            _lossless(stage, candidates[1])
        progress(0.95)
        best = min((c for c in candidates if c.exists()), key=lambda c: c.stat().st_size)
        after = best.stat().st_size
        details = {"before": before, "after": after, "engine": engine, "preset": preset.value}
        if after >= before:
            details.update(after=before, kept_original=True)
            progress(1.0)
            return Result([], "This file is already as small as it gets — original kept.",
                          details)
        with atomic_output(Path(output)) as target:
            target.write_bytes(best.read_bytes())
    progress(1.0)
    saved = 100 * (before - after) / before
    return Result([Path(output)],
                  f"{human_size(before)} → {human_size(after)} ({saved:.0f}% smaller).", details)


def _decrypted_copy(source: Path, password: str | None, tmp: Path) -> Path:
    """Ghostscript can't be trusted with encrypted input; hand it a decrypted temp copy."""
    try:
        with pikepdf.open(source, password=password or "", attempt_recovery=True) as pdf:
            if not pdf.is_encrypted:
                return source
            out = tmp / "decrypted.pdf"
            pdf.save(out)
            return out
    except pikepdf.PasswordError as exc:
        raise (WrongPassword if password else PasswordRequired)(
            f"{source.name} is password protected."
        ) from exc
    except pikepdf.PdfError:
        out = tmp / "repaired.pdf"
        out.write_bytes(repair_bytes(source, password))
        return out


_PAGE_LINE = re.compile(r"^Page (\d+)")
_TOTAL_LINE = re.compile(r"Processing pages \d+ through (\d+)")


def _ghostscript(gs: Path, src: Path, dst: Path, preset: CompressPreset,
                 progress: ProgressFn, cancel: Event | None) -> None:
    total = [0]

    def on_line(line: str) -> None:
        if m := _TOTAL_LINE.search(line):
            total[0] = int(m.group(1))
        elif (m := _PAGE_LINE.match(line)) and total[0]:
            progress(0.05 + 0.8 * int(m.group(1)) / total[0])

    engines.run(
        [
            str(gs),
            "-sDEVICE=pdfwrite",
            "-dCompatibilityLevel=1.7",
            f"-dPDFSETTINGS={GS_SETTINGS[preset]}",
            "-dDetectDuplicateImages=true",
            "-dCompressFonts=true",
            "-dNOPAUSE",
            "-dBATCH",
            "-dSAFER",
            f"-sOutputFile={dst}",
            str(src),
        ],
        cancel=cancel,
        on_line=on_line,
    )


def _mupdf_shrink(src: Path, dst: Path, preset: CompressPreset) -> None:
    dpi = TARGET_DPI[preset]
    with open_pdf(src) as doc:
        doc.rewrite_images(
            dpi_threshold=int(dpi * 1.3),
            dpi_target=dpi,
            quality=JPEG_QUALITY[preset],
            lossy=True,
            lossless=True,
            bitonal=False,
        )
        with contextlib.suppress(Exception):  # subsetting is a bonus; never fail over it
            doc.subset_fonts()
        doc.save(dst, garbage=4, deflate=True, deflate_images=True, deflate_fonts=True,
                 clean=True, use_objstms=1)


def _lossless(src: Path, dst: Path) -> None:
    with pikepdf.open(src) as pdf:
        pdf.remove_unreferenced_resources()
        pdf.save(
            dst,
            compress_streams=True,
            recompress_flate=True,
            object_stream_mode=pikepdf.ObjectStreamMode.generate,
        )


@dataclass
class RepairOptions:
    password: str | None = None


def repair(inputs: list[Path], output: Path, opts: RepairOptions | None = None,
           progress: ProgressFn = no_progress, cancel: Event | None = None) -> Result:
    """Rebuild a damaged PDF's structure with qpdf, then check MuPDF can render every page."""
    opts = opts or RepairOptions()
    data = repair_bytes(Path(inputs[0]), opts.password)
    progress(0.5)
    with fitz.open(stream=data, filetype="pdf") as doc:
        if doc.needs_pass and not doc.authenticate(opts.password or ""):
            raise WrongPassword("Wrong password.")
        pages = doc.page_count
        if pages == 0:
            raise PdfSoulError("No readable pages were recovered.")
    with atomic_output(Path(output)) as target:
        target.write_bytes(data)
    progress(1.0)
    return Result([Path(output)], f"Repaired — {pages} pages recovered.")


def human_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"
