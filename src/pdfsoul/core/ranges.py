"""Page range parsing. Users type 1-based ranges; core works with 0-based indexes."""

from __future__ import annotations

from pdfsoul.core.types import PdfSoulError


def parse_ranges(spec: str, page_count: int) -> list[list[int]]:
    """Parse ``"1-3,5,8-"`` into groups of 0-based page indexes.

    Each comma-separated part becomes one group, in the order written. ``8-`` runs to the
    last page, ``-3`` starts at page 1, and ``5-2`` counts down. Blank means every page.
    """
    spec = spec.strip()
    if not spec:
        return [list(range(page_count))]
    groups: list[list[int]] = []
    for raw in spec.split(","):
        part = raw.strip().lower().replace(" ", "")
        if not part:
            continue
        if part in {"end", "last"}:
            part = str(page_count)
        if "-" in part:
            left, _, right = part.partition("-")
            start = _page_number(left, page_count) if left else 1
            end = _page_number(right, page_count) if right else page_count
        else:
            start = end = _page_number(part, page_count)
        step = 1 if end >= start else -1
        groups.append([p - 1 for p in range(start, end + step, step)])
    if not groups:
        raise PdfSoulError(f"No pages in range '{spec}'.")
    return groups


def parse_pages(spec: str, page_count: int) -> list[int]:
    """Parse a range spec into a flat list of 0-based indexes, keeping order and duplicates."""
    return [p for group in parse_ranges(spec, page_count) for p in group]


def parse_page_set(spec: str, page_count: int) -> list[int]:
    """Parse a range spec into sorted unique 0-based indexes."""
    return sorted(set(parse_pages(spec, page_count)))


def format_ranges(pages: list[int]) -> str:
    """Format 0-based indexes as a compact 1-based spec: ``[0, 1, 2, 4]`` → ``"1-3,5"``."""
    if not pages:
        return ""
    ordered = sorted(set(pages))
    parts: list[str] = []
    start = prev = ordered[0]
    for p in ordered[1:]:
        if p == prev + 1:
            prev = p
            continue
        parts.append(_span(start, prev))
        start = prev = p
    parts.append(_span(start, prev))
    return ",".join(parts)


def _span(start: int, end: int) -> str:
    return str(start + 1) if start == end else f"{start + 1}-{end + 1}"


def _page_number(text: str, page_count: int) -> int:
    if text in {"end", "last"}:
        return page_count
    try:
        n = int(text)
    except ValueError:
        raise PdfSoulError(f"'{text}' is not a page number.") from None
    if not 1 <= n <= page_count:
        raise PdfSoulError(f"Page {n} is out of range (this file has {page_count} pages).")
    return n
