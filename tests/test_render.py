"""Search highlights must land on the rendered text for every combination of rotations."""

import pymupdf as fitz
import pytest

from pdfsoul.core.organise import PageRef
from pdfsoul.core.render import display_size, render_pixmap, search


@pytest.fixture(scope="module")
def doc():
    d = fitz.open()
    for own in (0, 90, 180, 270):
        page = d.new_page(width=300, height=500)
        page.insert_text((40, 60), "Needle here", fontsize=24)
        page.set_rotation(own)
    yield d
    d.close()


def _ink_inside(pix: fitz.Pixmap, rect: fitz.Rect, scale: float) -> float:
    """Fraction of dark pixels inside ``rect`` (display points) on the rendered pixmap."""
    box = fitz.IRect(rect * scale) & fitz.IRect(0, 0, pix.width, pix.height)
    dark = total = 0
    for y in range(box.y0, box.y1):
        for x in range(box.x0, box.x1):
            total += 1
            dark += sum(pix.pixel(x, y)) < 300
    return dark / max(total, 1)


@pytest.mark.parametrize("extra", [0, 90, 180, 270])
@pytest.mark.parametrize("source", [0, 1, 2, 3])
def test_hits_land_on_rendered_text(doc, source, extra):
    ref = PageRef(source, extra)
    pix = render_pixmap(doc, ref, 1.0)
    w, h = display_size(doc, ref)
    assert (pix.width, pix.height) == (round(w), round(h))
    hits = search(doc, ref, "needle")
    assert len(hits) == 1
    assert _ink_inside(pix, hits[0], 1.0) > 0.05


def test_case_sensitive_search(doc):
    assert search(doc, PageRef(0), "needle", case_sensitive=True) == []
    assert len(search(doc, PageRef(0), "Needle", case_sensitive=True)) == 1


def test_blank_page_renders_white():
    pix = render_pixmap(fitz.open(), PageRef(None, 0, 100, 50), 2.0)
    assert (pix.width, pix.height) == (200, 100)
    assert pix.pixel(10, 10) == (255, 255, 255)
