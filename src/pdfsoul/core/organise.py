"""Merge, split, and page edits (rotate, delete, reorder, duplicate, insert blank, extract).

All page edits are expressed as a *plan*: a list of :class:`PageRef` describing the output,
page by page. The UI organiser builds a plan interactively; the CLI builds one from a range.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from threading import Event

import pymupdf as fitz

from pdfsoul.core.document import normalise_toc, open_pdf, save_pdf
from pdfsoul.core.ranges import format_ranges, parse_page_set, parse_pages, parse_ranges
from pdfsoul.core.safe_io import safe_filename
from pdfsoul.core.types import PdfSoulError, Progress, ProgressFn, Result, no_progress

A4 = (595.0, 842.0)
METADATA_KEYS = ("title", "author", "subject", "keywords", "creator", "producer",
                 "creationDate", "modDate")


@dataclass(frozen=True)
class PageRef:
    """One output page: a source page (0-based) with extra rotation, or a blank page."""

    source: int | None
    rotation: int = 0
    width: float = A4[0]
    height: float = A4[1]

    @property
    def is_blank(self) -> bool:
        return self.source is None

    def rotated(self, angle: int) -> PageRef:
        return PageRef(self.source, (self.rotation + angle) % 360, self.width, self.height)


def identity_plan(page_count: int) -> list[PageRef]:
    return [PageRef(i) for i in range(page_count)]


# ---------------------------------------------------------------------------------------------
# Building documents from plans


def build_from_plan(src: fitz.Document, plan: list[PageRef]) -> fitz.Document:
    """Make a new document laid out as ``plan`` says. Bookmarks follow their pages."""
    if not plan:
        raise PdfSoulError("The result would have no pages.")
    out = fitz.open()
    for run in _runs(plan):
        first = run[0]
        if first.is_blank:
            for ref in run:
                out.new_page(width=ref.width, height=ref.height)
        else:
            assert first.source is not None and run[-1].source is not None
            # final=False keeps shared fonts/images as one copy across runs and duplicates.
            out.insert_pdf(src, from_page=first.source, to_page=run[-1].source, final=False)
    for index, ref in enumerate(plan):
        if ref.rotation and not ref.is_blank:
            page = out[index]
            page.set_rotation((page.rotation + ref.rotation) % 360)
    _copy_metadata(src, out)
    out.set_toc(_remap_toc(src.get_toc(simple=True), plan))
    return out


def apply_plan(
    inputs: list[Path],
    output: Path,
    plan: list[PageRef],
    password: str | None = None,
    progress: ProgressFn = no_progress,
    cancel: Event | None = None,
) -> Result:
    """Write ``inputs[0]`` laid out as ``plan`` to ``output``."""
    tick = Progress(progress, cancel, 3)
    with open_pdf(inputs[0], password) as src:
        tick.step()
        out = build_from_plan(src, plan)
        tick.step()
        save_pdf(out, output)
        out.close()
    tick.done()
    return Result([Path(output)], f"Saved {len(plan)} pages.")


def _runs(plan: list[PageRef]) -> list[list[PageRef]]:
    """Group consecutive refs into runs that can be copied with one insert_pdf call."""
    runs: list[list[PageRef]] = []
    for ref in plan:
        if runs:
            last = runs[-1][-1]
            if ref.is_blank and last.is_blank:
                runs[-1].append(ref)
                continue
            if (
                not ref.is_blank
                and not last.is_blank
                and ref.source == (last.source or 0) + 1
            ):
                runs[-1].append(ref)
                continue
        runs.append([ref])
    return runs


def _remap_toc(toc: list[list], plan: list[PageRef]) -> list[list]:
    """Point each bookmark at the first output page made from its source page; drop the rest."""
    first_seen: dict[int, int] = {}
    for index, ref in enumerate(plan):
        if ref.source is not None:
            first_seen.setdefault(ref.source, index)
    kept = [
        [level, title, first_seen[page - 1] + 1]
        for level, title, page, *_ in toc
        if page - 1 in first_seen
    ]
    return normalise_toc(kept)


def _copy_metadata(src: fitz.Document, out: fitz.Document) -> None:
    meta = src.metadata or {}
    out.set_metadata({k: meta[k] for k in METADATA_KEYS if meta.get(k)})


# ---------------------------------------------------------------------------------------------
# Single-file page edits (used by the CLI; the UI goes through PageList + apply_plan)


@dataclass
class PagesOptions:
    pages: str = ""
    password: str | None = None


@dataclass
class RotateOptions(PagesOptions):
    angle: int = 90


@dataclass
class InsertBlankOptions:
    after: int = 0  # 1-based page number; 0 = before the first page
    count: int = 1
    password: str | None = None


def rotate(inputs: list[Path], output: Path, opts: RotateOptions,
           progress: ProgressFn = no_progress, cancel: Event | None = None) -> Result:
    if opts.angle % 90:
        raise PdfSoulError("Rotation must be a multiple of 90 degrees.")
    count = _count(inputs[0], opts.password)
    chosen = set(parse_page_set(opts.pages, count))
    plan = [ref.rotated(opts.angle) if ref.source in chosen else ref
            for ref in identity_plan(count)]
    return apply_plan(inputs, output, plan, opts.password, progress, cancel)


def delete_pages(inputs: list[Path], output: Path, opts: PagesOptions,
                 progress: ProgressFn = no_progress, cancel: Event | None = None) -> Result:
    count = _count(inputs[0], opts.password)
    doomed = set(parse_page_set(opts.pages, count))
    plan = [ref for ref in identity_plan(count) if ref.source not in doomed]
    if not plan:
        raise PdfSoulError("You can't delete every page.")
    return apply_plan(inputs, output, plan, opts.password, progress, cancel)


def extract_pages(inputs: list[Path], output: Path, opts: PagesOptions,
                  progress: ProgressFn = no_progress, cancel: Event | None = None) -> Result:
    """Copy the chosen pages, in the order written, into a new file."""
    pages = parse_pages(opts.pages, _count(inputs[0], opts.password))
    return apply_plan(inputs, output, [PageRef(p) for p in pages], opts.password, progress,
                      cancel)


def reorder(inputs: list[Path], output: Path, opts: PagesOptions,
            progress: ProgressFn = no_progress, cancel: Event | None = None) -> Result:
    """Reorder pages; pages not mentioned in ``opts.pages`` follow in their original order."""
    count = _count(inputs[0], opts.password)
    order = parse_pages(opts.pages, count)
    rest = [p for p in range(count) if p not in set(order)]
    return apply_plan(inputs, output, [PageRef(p) for p in order + rest], opts.password,
                      progress, cancel)


def insert_blank(inputs: list[Path], output: Path, opts: InsertBlankOptions,
                 progress: ProgressFn = no_progress, cancel: Event | None = None) -> Result:
    with open_pdf(inputs[0], opts.password) as src:
        count = src.page_count
        if not 0 <= opts.after <= count:
            raise PdfSoulError(f"Page {opts.after} is out of range (1–{count}).")
        ref_page = src[max(opts.after - 1, 0)]
        size = (ref_page.rect.width, ref_page.rect.height)
    plan = identity_plan(count)
    blanks = [PageRef(None, 0, *size) for _ in range(max(opts.count, 1))]
    plan[opts.after:opts.after] = blanks
    return apply_plan(inputs, output, plan, opts.password, progress, cancel)


def duplicate_pages(inputs: list[Path], output: Path, opts: PagesOptions,
                    progress: ProgressFn = no_progress, cancel: Event | None = None) -> Result:
    """Insert a copy of each chosen page right after it."""
    count = _count(inputs[0], opts.password)
    chosen = set(parse_page_set(opts.pages, count))
    plan: list[PageRef] = []
    for ref in identity_plan(count):
        plan.append(ref)
        if ref.source in chosen:
            plan.append(ref)
    return apply_plan(inputs, output, plan, opts.password, progress, cancel)


def _count(path: Path, password: str | None) -> int:
    with open_pdf(path, password) as doc:
        return doc.page_count


# ---------------------------------------------------------------------------------------------
# Merge


@dataclass
class MergeOptions:
    page_ranges: list[str] = field(default_factory=list)  # one per input; blank = all pages
    passwords: dict[str, str] = field(default_factory=dict)  # str(path) → password
    bookmarks: bool = True


def merge(inputs: list[Path], output: Path, opts: MergeOptions | None = None,
          progress: ProgressFn = no_progress, cancel: Event | None = None) -> Result:
    """Join PDFs in order. Each file's bookmarks are kept; a file without any gets one entry."""
    opts = opts or MergeOptions()
    if len(inputs) < 1:
        raise PdfSoulError("Add at least one PDF to merge.")
    tick = Progress(progress, cancel, len(inputs) + 1)
    out = fitz.open()
    toc: list[list] = []
    for i, path in enumerate(inputs):
        path = Path(path)
        spec = opts.page_ranges[i] if i < len(opts.page_ranges) else ""
        with open_pdf(path, opts.passwords.get(str(path))) as src:
            pages = parse_pages(spec, src.page_count)
            start = out.page_count
            plan = [PageRef(p) for p in pages]
            for run in _runs(plan):
                out.insert_pdf(src, from_page=run[0].source, to_page=run[-1].source, final=False)
            if opts.bookmarks:
                own = _remap_toc(src.get_toc(simple=True), plan)
                if own:
                    toc.extend([lvl, title, page + start] for lvl, title, page in own)
                else:
                    toc.append([1, path.stem, start + 1])
            if i == 0:
                _copy_metadata(src, out)
        tick.step()
    if opts.bookmarks:
        out.set_toc(normalise_toc(toc))
    save_pdf(out, output)
    total = out.page_count
    out.close()
    tick.done()
    return Result([Path(output)], f"Merged {len(inputs)} files into {total} pages.")


# ---------------------------------------------------------------------------------------------
# Split


class SplitMode(StrEnum):
    EACH_PAGE = "each"
    RANGES = "ranges"
    EVERY_N = "every"
    BOOKMARKS = "bookmarks"


@dataclass
class SplitOptions:
    mode: SplitMode = SplitMode.EACH_PAGE
    ranges: str = ""
    every: int = 1
    password: str | None = None


def split(inputs: list[Path], output: Path, opts: SplitOptions,
          progress: ProgressFn = no_progress, cancel: Event | None = None) -> Result:
    """Split one PDF into several. ``output`` is the folder the parts go into."""
    source = Path(inputs[0])
    folder = Path(output)
    folder.mkdir(parents=True, exist_ok=True)
    with open_pdf(source, opts.password) as src:
        parts = _split_groups(src, opts)
        tick = Progress(progress, cancel, len(parts))
        written: list[Path] = []
        used: set[str] = set()
        for label, pages in parts:
            name = f"{source.stem}_{label}"
            n = 2
            while name.lower() in used:
                name = f"{source.stem}_{label}_{n}"
                n += 1
            used.add(name.lower())
            part = build_from_plan(src, [PageRef(p) for p in pages])
            written.append(save_pdf(part, folder / f"{name}.pdf"))
            part.close()
            tick.step()
    return Result(written, f"Split into {len(written)} files.")


def _split_groups(src: fitz.Document, opts: SplitOptions) -> list[tuple[str, list[int]]]:
    count = src.page_count
    mode = SplitMode(opts.mode)
    if mode is SplitMode.EACH_PAGE:
        groups = [[p] for p in range(count)]
    elif mode is SplitMode.RANGES:
        if not opts.ranges.strip():
            raise PdfSoulError("Enter the page ranges to split out, e.g. 1-3,5,8-")
        groups = parse_ranges(opts.ranges, count)
    elif mode is SplitMode.EVERY_N:
        if opts.every < 1:
            raise PdfSoulError("Pages per file must be at least 1.")
        groups = [list(range(s, min(s + opts.every, count))) for s in range(0, count, opts.every)]
    else:
        return _bookmark_groups(src)
    return [(_page_label(g), g) for g in groups]


def _bookmark_groups(src: fitz.Document) -> list[tuple[str, list[int]]]:
    top = [(title, page - 1) for level, title, page, *_ in src.get_toc(simple=True)
           if level == 1 and page >= 1]
    if not top:
        raise PdfSoulError("This PDF has no bookmarks to split by.")
    top.sort(key=lambda item: item[1])
    starts = [0 if i == 0 else start for i, (_, start) in enumerate(top)]
    groups: list[tuple[str, list[int]]] = []
    for i, (title, _) in enumerate(top):
        start = starts[i]
        end = starts[i + 1] if i + 1 < len(starts) else src.page_count
        if end > start:
            groups.append((f"{i + 1:02d}_{safe_filename(title, 'section', 50)}",
                           list(range(start, end))))
    return groups


def _page_label(pages: list[int]) -> str:
    if len(pages) > 1 and pages == list(range(pages[0], pages[-1] + 1)):
        return f"p{pages[0] + 1}-{pages[-1] + 1}"
    if len(pages) == 1:
        return f"p{pages[0] + 1}"
    return "p" + format_ranges(pages).replace(",", "_")
