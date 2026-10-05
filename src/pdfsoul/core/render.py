"""Page geometry for display: sizes, render matrices and search hits, honouring both the page's
own /Rotate and the organiser's extra rotation. Pure MuPDF, no Qt, so it is unit-tested.

Display space is in points, origin at the top-left of the page as the reader sees it.
"""

from __future__ import annotations

import pymupdf as fitz

from pdfsoul.core.organise import PageRef


def display_size(doc: fitz.Document, ref: PageRef) -> tuple[float, float]:
    """Width and height in points of ``ref`` as shown on screen."""
    if ref.source is None:
        return ref.width, ref.height
    rect = doc[ref.source].rect  # already includes the page's own rotation
    if ref.rotation in (90, 270):
        return rect.height, rect.width
    return rect.width, rect.height


def _extra(page: fitz.Page, rotation: int) -> fitz.Matrix:
    """Turn the visible page by ``rotation`` (clockwise) and shift it back to the origin."""
    turn = fitz.Matrix(rotation)
    box = page.rect * turn
    return turn * fitz.Matrix(1, 0, 0, 1, -box.x0, -box.y0)


def render_pixmap(doc: fitz.Document, ref: PageRef, scale: float) -> fitz.Pixmap:
    """Render ``ref`` at ``scale`` pixels per point (blank pages come back white)."""
    if ref.source is None:
        w, h = max(int(ref.width * scale), 1), max(int(ref.height * scale), 1)
        pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, w, h), False)
        pix.clear_with(255)
        return pix
    matrix = fitz.Matrix(scale, scale).prerotate(ref.rotation)
    return doc[ref.source].get_pixmap(matrix=matrix, alpha=False, annots=True)


def search(doc: fitz.Document, ref: PageRef, term: str, *, case_sensitive: bool = False
           ) -> list[fitz.Rect]:
    """Find ``term`` on the page; hits are returned in display space (points)."""
    if ref.source is None or not term:
        return []
    page = doc[ref.source]
    hits = page.search_for(term)  # MuPDF search ignores case; filter afterwards if asked
    if case_sensitive:
        hits = [r for r in hits
                if term in page.get_textbox(fitz.Rect(r.x0 - 1, r.y0 - 1, r.x1 + 1, r.y1 + 1))]
    to_display = page.rotation_matrix * _extra(page, ref.rotation)
    return [(r * to_display).normalize() for r in hits]
