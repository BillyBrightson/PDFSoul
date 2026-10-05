"""The open document: its file, password (memory only), page plan, and render caches.

The PDF is read into memory so the file on disk is never locked — on Windows that lets any
operation write over it (when the user explicitly chooses to) while it is on screen.
"""

from __future__ import annotations

import logging
from collections import OrderedDict
from collections.abc import Callable
from pathlib import Path

import pymupdf as fitz
from PySide6.QtCore import QObject, QSize, Signal
from PySide6.QtGui import QImage

from pdfsoul.core import render
from pdfsoul.core.document import open_bytes, repair_bytes
from pdfsoul.core.organise import PageRef
from pdfsoul.core.pagelist import PageList
from pdfsoul.core.types import PasswordRequired, PdfSoulError, WrongPassword

log = logging.getLogger(__name__)

PAGE_CACHE_BYTES = 256 * 1024 * 1024
THUMB_CACHE_ITEMS = 400


class _LRU(OrderedDict):
    def __init__(self, max_items: int = 0, max_bytes: int = 0) -> None:
        super().__init__()
        self.max_items, self.max_bytes, self.bytes = max_items, max_bytes, 0

    def get_image(self, key: object) -> QImage | None:
        image = self.get(key)
        if image is not None:
            self.move_to_end(key)
        return image

    def put(self, key: object, image: QImage) -> None:
        if key in self:
            self.bytes -= self.pop(key).sizeInBytes()
        self[key] = image
        self.bytes += image.sizeInBytes()
        while self and ((self.max_items and len(self) > self.max_items)
                        or (self.max_bytes and self.bytes > self.max_bytes)):
            _, old = self.popitem(last=False)
            self.bytes -= old.sizeInBytes()

    def reset(self) -> None:
        self.clear()
        self.bytes = 0


def to_qimage(pix: fitz.Pixmap) -> QImage:
    image = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format.Format_RGB888)
    return image.copy()  # own the pixels; the pixmap's buffer goes away


class DocumentSession(QObject):
    opened = Signal()
    closed = Signal()
    planChanged = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.path: Path | None = None
        self.password: str | None = None
        self.doc: fitz.Document | None = None
        self.pages: PageList = PageList(0)
        self.repaired = False
        self._page_cache = _LRU(max_bytes=PAGE_CACHE_BYTES)
        self._thumb_cache = _LRU(max_items=THUMB_CACHE_ITEMS)

    # -- lifecycle -----------------------------------------------------------------------------

    @property
    def is_open(self) -> bool:
        return self.doc is not None

    @property
    def dirty(self) -> bool:
        return self.is_open and self.pages.dirty

    def open(self, path: Path, password: str | None = None) -> None:
        """Load ``path``. Raises PasswordRequired / WrongPassword / PdfSoulError."""
        path = Path(path)
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise PdfSoulError(f"Couldn't open {path.name}: {exc.strerror or exc}") from exc
        repaired = False
        try:
            doc = open_bytes(data, password, path.name)
        except (PasswordRequired, WrongPassword):
            raise
        except PdfSoulError:
            log.warning("Repairing %s on open", path)
            doc = open_bytes(repair_bytes(path, password), None, path.name)
            repaired = True
        if doc.page_count == 0:
            doc.close()
            raise PdfSoulError(f"{path.name} has no pages.")
        self.close()
        self.doc, self.path, self.password, self.repaired = doc, path.resolve(), password, repaired
        sizes = [(p.rect.width, p.rect.height) for p in doc]
        self.pages = PageList(doc.page_count, sizes)
        self.opened.emit()

    def close(self) -> None:
        if self.doc is None:
            return
        self.doc.close()
        self.doc, self.path, self.password = None, None, None
        self.pages = PageList(0)
        self._page_cache.reset()
        self._thumb_cache.reset()
        self.closed.emit()

    # -- editing (organiser) -------------------------------------------------------------------

    def edit(self, change: Callable[[PageList], object]) -> object:
        result = change(self.pages)
        self.planChanged.emit()
        return result

    def undo(self) -> None:
        if self.pages.undo():
            self.planChanged.emit()

    def redo(self) -> None:
        if self.pages.redo():
            self.planChanged.emit()

    @property
    def plan(self) -> list[PageRef]:
        return list(self.pages.pages)

    # -- geometry and rendering ----------------------------------------------------------------

    def page_size(self, index: int) -> tuple[float, float]:
        assert self.doc is not None
        return render.display_size(self.doc, self.pages[index])

    def render_page(self, index: int, scale: float) -> QImage:
        """Render plan entry ``index`` at ``scale`` device pixels per point (cached)."""
        assert self.doc is not None
        ref = self.pages[index]
        key = (ref, round(scale, 3))
        image = self._page_cache.get_image(key)
        if image is None:
            image = to_qimage(render.render_pixmap(self.doc, ref, scale))
            self._page_cache.put(key, image)
        return image

    def cached_page(self, index: int, scale: float) -> QImage | None:
        return self._page_cache.get_image((self.pages[index], round(scale, 3)))

    def thumbnail(self, index: int, box: QSize) -> QImage:
        assert self.doc is not None
        ref = self.pages[index]
        key = (ref, box.width(), box.height())
        image = self._thumb_cache.get_image(key)
        if image is None:
            w, h = render.display_size(self.doc, ref)
            scale = min(box.width() / w, box.height() / h)
            image = to_qimage(render.render_pixmap(self.doc, ref, scale))
            self._thumb_cache.put(key, image)
        return image

    def cached_thumbnail(self, index: int, box: QSize) -> QImage | None:
        return self._thumb_cache.get_image((self.pages[index], box.width(), box.height()))

    def search(self, index: int, term: str, case_sensitive: bool) -> list[fitz.Rect]:
        assert self.doc is not None
        return render.search(self.doc, self.pages[index], term, case_sensitive=case_sensitive)

    def page_label(self, index: int) -> str:
        ref = self.pages[index]
        return "blank" if ref.is_blank else str((ref.source or 0) + 1)
