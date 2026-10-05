"""Continuous-scroll page viewer.

Only visible pages are rendered, one per event-loop tick, so a 1,000-page file opens instantly
and scrolling never blocks. While a page renders at the new zoom, any cached render of it is
stretched in its place.
"""

from __future__ import annotations

from bisect import bisect_right
from enum import Enum

import pymupdf as fitz
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QKeyEvent, QPainter, QPaintEvent, QPen, QWheelEvent
from PySide6.QtWidgets import QAbstractScrollArea, QWidget

from pdfsoul.app.session import DocumentSession

GAP = 14
MARGIN = 20
ZOOM_STEPS = [0.25, 0.33, 0.5, 0.67, 0.75, 0.9, 1.0, 1.1, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0, 4.0,
              5.0, 6.0]
MIN_ZOOM, MAX_ZOOM = ZOOM_STEPS[0], ZOOM_STEPS[-1]


class ZoomMode(Enum):
    CUSTOM = "custom"
    FIT_WIDTH = "fit-width"
    FIT_PAGE = "fit-page"


class PageView(QAbstractScrollArea):
    currentPageChanged = Signal(int)
    zoomChanged = Signal(float)

    def __init__(self, session: DocumentSession, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("PageView")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._session = session
        self._zoom = 1.0
        self._mode = ZoomMode.FIT_WIDTH
        self._offsets: list[float] = []
        self._sizes: list[tuple[float, float]] = []
        self._content_w = self._content_h = 0.0
        self._current = 0
        self._matches: dict[int, list[fitz.Rect]] = {}
        self._active_match: tuple[int, int] | None = None
        self._pending: list[int] = []
        self._render_timer = QTimer(self, singleShot=True, interval=0)
        self._render_timer.timeout.connect(self._render_next)
        self.verticalScrollBar().valueChanged.connect(self._on_scrolled)
        self.horizontalScrollBar().valueChanged.connect(lambda _: self.viewport().update())
        session.opened.connect(self._on_opened)
        session.closed.connect(self._on_plan_changed)
        session.planChanged.connect(self._on_plan_changed)

    # -- public API ----------------------------------------------------------------------------

    @property
    def zoom(self) -> float:
        return self._zoom

    @property
    def zoom_mode(self) -> ZoomMode:
        return self._mode

    @property
    def current_page(self) -> int:
        return self._current

    def set_zoom(self, zoom: float, anchor: QPointF | None = None) -> None:
        self._mode = ZoomMode.CUSTOM
        self._change_zoom(zoom, anchor)

    def set_zoom_mode(self, mode: ZoomMode) -> None:
        self._mode = mode
        if mode is not ZoomMode.CUSTOM:
            self._change_zoom(self._fit_zoom())

    def zoom_in(self) -> None:
        self.set_zoom(next((z for z in ZOOM_STEPS if z > self._zoom + 1e-3), MAX_ZOOM))

    def zoom_out(self) -> None:
        self.set_zoom(next((z for z in reversed(ZOOM_STEPS) if z < self._zoom - 1e-3), MIN_ZOOM))

    def goto_page(self, index: int) -> None:
        if not self._offsets:
            return
        index = max(0, min(index, len(self._offsets) - 1))
        self.verticalScrollBar().setValue(int(self._offsets[index] - GAP / 2))
        self._set_current(index)

    def set_matches(self, matches: dict[int, list[fitz.Rect]]) -> None:
        self._matches = matches
        self.viewport().update()

    def show_match(self, page: int, index: int) -> None:
        """Highlight one match strongly and scroll it into view."""
        self._active_match = (page, index)
        rects = self._matches.get(page, [])
        if page < len(self._offsets) and index < len(rects):
            r = rects[index]
            top = self._offsets[page] + r.y0 * self._zoom
            bar = self.verticalScrollBar()
            if not bar.value() + 40 < top < bar.value() + self.viewport().height() - 60:
                bar.setValue(int(top - self.viewport().height() / 3))
            left = self._page_x(page) + r.x0 * self._zoom
            hbar = self.horizontalScrollBar()
            if not hbar.value() < left < hbar.value() + self.viewport().width() - 40:
                hbar.setValue(int(left - self.viewport().width() / 3))
        self.viewport().update()

    def clear_matches(self) -> None:
        self._matches, self._active_match = {}, None
        self.viewport().update()

    # -- layout --------------------------------------------------------------------------------

    def _on_opened(self) -> None:
        self._current = -1
        self._mode = ZoomMode.FIT_WIDTH
        self.clear_matches()
        self._relayout()
        self._change_zoom(self._fit_zoom())
        self.verticalScrollBar().setValue(0)
        self._set_current(0)

    def _on_plan_changed(self) -> None:
        keep = self._current
        self._relayout()
        if self._mode is not ZoomMode.CUSTOM:
            self._change_zoom(self._fit_zoom())
        self.clear_matches()
        if self._offsets:
            self._set_current(min(keep, len(self._offsets) - 1), force=True)
        self.viewport().update()

    def _relayout(self) -> None:
        session = self._session
        count = len(session.pages) if session.is_open else 0
        self._sizes = [session.page_size(i) for i in range(count)]
        self._offsets = []
        y = MARGIN
        widest = 0.0
        for w, h in self._sizes:
            self._offsets.append(y)
            y += h * self._zoom + GAP
            widest = max(widest, w * self._zoom)
        self._content_h = y - GAP + MARGIN if count else 0
        self._content_w = widest + 2 * MARGIN
        self._update_scrollbars()
        self._pending.clear()
        self.viewport().update()

    def _update_scrollbars(self) -> None:
        vp = self.viewport().size()
        v, h = self.verticalScrollBar(), self.horizontalScrollBar()
        v.setRange(0, max(0, int(self._content_h - vp.height())))
        v.setPageStep(vp.height())
        v.setSingleStep(48)
        h.setRange(0, max(0, int(self._content_w - vp.width())))
        h.setPageStep(vp.width())
        h.setSingleStep(48)

    def _fit_zoom(self) -> float:
        if not self._sizes:
            return self._zoom
        vp = self.viewport().size()
        avail_w = max(vp.width() - 2 * MARGIN - 4, 50)
        if self._mode is ZoomMode.FIT_WIDTH:
            widest = max(w for w, _ in self._sizes)
            zoom = avail_w / widest
        else:
            w, h = self._sizes[max(self._current, 0)]
            zoom = min(avail_w / w, max(vp.height() - 2 * GAP, 50) / h)
        return max(MIN_ZOOM, min(zoom, MAX_ZOOM))

    def _change_zoom(self, zoom: float, anchor: QPointF | None = None) -> None:
        zoom = max(MIN_ZOOM, min(zoom, MAX_ZOOM))
        if abs(zoom - self._zoom) < 1e-4 and self._offsets:
            return
        anchor = anchor or QPointF(self.viewport().width() / 2, self.viewport().height() / 2)
        # Remember which page point sits under the anchor, then put it back after relayout.
        page, fy, fx = self._page_point_at(anchor)
        self._zoom = zoom
        self._relayout()
        if page is not None:
            w, h = self._sizes[page]
            self.verticalScrollBar().setValue(int(self._offsets[page] + fy * h * zoom - anchor.y()))
            self.horizontalScrollBar().setValue(int(self._page_x(page) + fx * w * zoom
                                                    - anchor.x()))
        self.zoomChanged.emit(zoom)

    def _page_point_at(self, pos: QPointF) -> tuple[int | None, float, float]:
        if not self._offsets:
            return None, 0.0, 0.0
        y = self.verticalScrollBar().value() + pos.y()
        x = self.horizontalScrollBar().value() + pos.x()
        page = max(0, bisect_right(self._offsets, y) - 1)
        w, h = self._sizes[page]
        fy = (y - self._offsets[page]) / (h * self._zoom)
        fx = (x - self._page_x(page)) / (w * self._zoom)
        return page, min(max(fy, 0.0), 1.0), min(max(fx, 0.0), 1.0)

    def _page_x(self, page: int) -> float:
        """Left edge of a page in content coordinates (pages are centred)."""
        width = self._sizes[page][0] * self._zoom
        content = max(self._content_w, self.viewport().width())
        return (content - width) / 2

    def _visible_pages(self) -> range:
        if not self._offsets:
            return range(0)
        top = self.verticalScrollBar().value()
        bottom = top + self.viewport().height()
        first = max(0, bisect_right(self._offsets, top) - 1)
        last = max(first, bisect_right(self._offsets, bottom) - 1)
        return range(first, min(last + 1, len(self._offsets)))

    def _on_scrolled(self, _: int) -> None:
        if self._offsets:
            middle = self.verticalScrollBar().value() + self.viewport().height() / 3
            self._set_current(max(0, bisect_right(self._offsets, middle) - 1))
        self.viewport().update()

    def _set_current(self, index: int, force: bool = False) -> None:
        if index != self._current or force:
            self._current = index
            self.currentPageChanged.emit(index)

    # -- painting ------------------------------------------------------------------------------

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self.viewport())
        if not self._offsets:
            return
        dpr = self.devicePixelRatioF()
        scale = self._zoom * dpr
        sx, sy = self.horizontalScrollBar().value(), self.verticalScrollBar().value()
        shadow = QColor(0, 0, 0, 40)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        for i in self._visible_pages():
            w, h = self._sizes[i]
            rect = QRectF(self._page_x(i) - sx, self._offsets[i] - sy, w * self._zoom,
                          h * self._zoom)
            painter.fillRect(rect.translated(2, 3), shadow)
            image = self._session.cached_page(i, scale)
            if image is None:
                painter.fillRect(rect, Qt.GlobalColor.white)
                fallback = self._any_cached(i)
                if fallback is not None:
                    painter.drawImage(rect, fallback)
                if i not in self._pending:
                    self._pending.append(i)
                    self._render_timer.start()
            else:
                painter.drawImage(rect, image)
            self._paint_matches(painter, i, rect)

    def _paint_matches(self, painter: QPainter, page: int, rect: QRectF) -> None:
        hits = self._matches.get(page)
        if not hits:
            return
        painter.setPen(Qt.PenStyle.NoPen)
        for n, r in enumerate(hits):
            active = self._active_match == (page, n)
            painter.setBrush(QColor(255, 140, 0, 130) if active else QColor(255, 220, 0, 110))
            box = QRectF(rect.x() + r.x0 * self._zoom, rect.y() + r.y0 * self._zoom,
                         r.width * self._zoom, r.height * self._zoom)
            painter.drawRect(box)
            if active:
                painter.setPen(QPen(QColor(230, 100, 0), 1.5))
                painter.drawRect(box)
                painter.setPen(Qt.PenStyle.NoPen)

    def _any_cached(self, index: int) -> QImage | None:
        dpr = self.devicePixelRatioF()
        for zoom in ZOOM_STEPS:
            image = self._session.cached_page(index, zoom * dpr)
            if image is not None:
                return image
        return None

    def _render_next(self) -> None:
        visible = set(self._visible_pages())
        self._pending = [i for i in self._pending if i in visible]
        if not self._pending:
            return
        index = self._pending.pop(0)
        self._session.render_page(index, self._zoom * self.devicePixelRatioF())
        self.viewport().update()
        if self._pending:
            self._render_timer.start()

    # -- input ---------------------------------------------------------------------------------

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._mode is not ZoomMode.CUSTOM and self._offsets:
            self._change_zoom(self._fit_zoom())
        self._update_scrollbars()

    def wheelEvent(self, event: QWheelEvent) -> None:
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            steps = event.angleDelta().y() / 120
            if steps:
                self._mode = ZoomMode.CUSTOM
                self._change_zoom(self._zoom * (1.1 ** steps), event.position())
            event.accept()
            return
        super().wheelEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        bar = self.verticalScrollBar()
        key = event.key()
        if key == Qt.Key.Key_Home:
            self.goto_page(0)
        elif key == Qt.Key.Key_End:
            self.goto_page(len(self._offsets) - 1)
        elif key in (Qt.Key.Key_PageDown, Qt.Key.Key_Space):
            bar.setValue(bar.value() + bar.pageStep() - 40)
        elif key == Qt.Key.Key_PageUp:
            bar.setValue(bar.value() - bar.pageStep() + 40)
        elif key == Qt.Key.Key_Down:
            bar.setValue(bar.value() + bar.singleStep())
        elif key == Qt.Key.Key_Up:
            bar.setValue(bar.value() - bar.singleStep())
        else:
            super().keyPressEvent(event)

    def mousePressEvent(self, event) -> None:
        page, _, _ = self._page_point_at(event.position())
        if page is not None:
            self._set_current(page)
        self.setFocus()
        super().mousePressEvent(event)
