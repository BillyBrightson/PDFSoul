"""Thumbnails: one model shared by the viewer's side strip and the organiser grid.

Thumbnails render lazily — only rows a view actually asks for — a few per event-loop tick.
The organiser grid supports multi-select and drag-to-reorder; edits go through the session's
PageList, so they are previewed and undoable until saved.
"""

from __future__ import annotations

import json
import time

from PySide6.QtCore import (
    QAbstractListModel,
    QByteArray,
    QMimeData,
    QModelIndex,
    QPersistentModelIndex,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QAbstractItemView, QListView, QWidget

from pdfsoul.app.session import DocumentSession

MIME = "application/x-pdfsoul-pages"
THUMB_BOX = QSize(150, 196)  # logical pixels


class ThumbnailModel(QAbstractListModel):
    movedTo = Signal(list)  # new rows of pages moved by drag and drop

    def __init__(self, session: DocumentSession, dpr: float = 1.0) -> None:
        super().__init__()
        self._session = session
        self._dpr = dpr
        self._queue: list[int] = []
        self._placeholder: QPixmap | None = None
        self._timer = QTimer(self, singleShot=True, interval=0)
        self._timer.timeout.connect(self._render_some)
        session.opened.connect(self._reset)
        session.closed.connect(self._reset)
        session.planChanged.connect(self._reset)

    def set_device_pixel_ratio(self, dpr: float) -> None:
        if abs(dpr - self._dpr) > 1e-3:
            self._dpr = dpr
            self._placeholder = None
            self._reset()

    @property
    def _box(self) -> QSize:
        return QSize(int(THUMB_BOX.width() * self._dpr), int(THUMB_BOX.height() * self._dpr))

    def _reset(self) -> None:
        self.beginResetModel()
        self._queue.clear()
        self.endResetModel()

    # -- model ---------------------------------------------------------------------------------

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex | None = None) -> int:
        if (parent is not None and parent.isValid()) or not self._session.is_open:
            return 0
        return len(self._session.pages)

    def data(self, index: QModelIndex | QPersistentModelIndex,
             role: int = Qt.ItemDataRole.DisplayRole) -> object:
        if not index.isValid() or not self._session.is_open:
            return None
        row = index.row()
        if role == Qt.ItemDataRole.DisplayRole:
            return str(row + 1)
        if role == Qt.ItemDataRole.DecorationRole:
            image = self._session.cached_thumbnail(row, self._box)
            if image is None:
                if row not in self._queue:
                    self._queue.append(row)
                    self._timer.start()
                return _untinted(self._placeholder_pixmap())
            return _untinted(self._framed(image))
        if role == Qt.ItemDataRole.ToolTipRole:
            ref = self._session.pages[row]
            if ref.is_blank:
                return "Blank page (inserted)"
            text = f"Original page {(ref.source or 0) + 1}"
            return text + (f", rotated {ref.rotation}°" if ref.rotation else "")
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return Qt.AlignmentFlag.AlignHCenter
        return None

    def flags(self, index: QModelIndex | QPersistentModelIndex) -> Qt.ItemFlag:
        base = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if index.isValid():
            return base | Qt.ItemFlag.ItemIsDragEnabled | Qt.ItemFlag.ItemIsDropEnabled
        return Qt.ItemFlag.ItemIsDropEnabled

    # -- drag and drop -------------------------------------------------------------------------

    def supportedDropActions(self) -> Qt.DropAction:
        return Qt.DropAction.MoveAction

    def supportedDragActions(self) -> Qt.DropAction:
        return Qt.DropAction.MoveAction

    def mimeTypes(self) -> list[str]:
        return [MIME]

    def mimeData(self, indexes: list[QModelIndex]) -> QMimeData:
        mime = QMimeData()
        rows = sorted({i.row() for i in indexes})
        mime.setData(MIME, QByteArray(json.dumps(rows).encode()))
        return mime

    def dropMimeData(self, data: QMimeData, action: Qt.DropAction, row: int, column: int,
                     parent: QModelIndex | QPersistentModelIndex) -> bool:
        if not data.hasFormat(MIME):
            return False
        rows = json.loads(bytes(data.data(MIME).data()).decode())
        if row == -1:
            row = parent.row() if parent.isValid() else self.rowCount()
        moved = self._session.edit(lambda pages: pages.move(rows, row))
        self.movedTo.emit(moved)
        return True

    # -- rendering -----------------------------------------------------------------------------

    def _render_some(self) -> None:
        start = time.perf_counter()
        done: list[int] = []
        while self._queue and time.perf_counter() - start < 0.03:
            row = self._queue.pop(0)
            if row < self.rowCount():
                self._session.thumbnail(row, self._box)
                done.append(row)
        for row in done:
            index = self.index(row)
            self.dataChanged.emit(index, index, [Qt.ItemDataRole.DecorationRole])
        if self._queue:
            self._timer.start()

    def _framed(self, image: QImage) -> QPixmap:
        """Thumbnail on a transparent canvas of fixed size, with a thin border."""
        box = self._box
        canvas = QPixmap(box)
        canvas.fill(Qt.GlobalColor.transparent)
        p = QPainter(canvas)
        x = (box.width() - image.width()) // 2
        y = (box.height() - image.height()) // 2
        p.drawImage(x, y, image)
        p.setPen(QPen(QColor(0, 0, 0, 60), 1))
        p.drawRect(x, y, image.width() - 1, image.height() - 1)
        p.end()
        canvas.setDevicePixelRatio(self._dpr)
        return canvas

    def _placeholder_pixmap(self) -> QPixmap:
        if self._placeholder is None:
            box = self._box
            image = QImage(int(box.height() / 1.414), box.height(), QImage.Format.Format_RGB888)
            image.fill(QColor("white"))
            self._placeholder = self._framed(image)
        return self._placeholder


def _untinted(pixmap: QPixmap) -> QIcon:
    """Selected pages keep their true colours; the selection shows as the cell background."""
    icon = QIcon(pixmap)
    icon.addPixmap(pixmap, QIcon.Mode.Selected)
    return icon


def _base_list(view: QListView, model: ThumbnailModel) -> None:
    view.setModel(model)
    view.setUniformItemSizes(True)
    view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    view.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)


class ThumbnailStrip(QListView):
    """Narrow vertical strip beside the viewer; click a page to jump to it."""

    pageActivated = Signal(int)

    def __init__(self, model: ThumbnailModel, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ThumbStrip")
        _base_list(self, model)
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setFlow(QListView.Flow.TopToBottom)
        self.setWrapping(False)
        self.setMovement(QListView.Movement.Static)
        self.setIconSize(QSize(92, 120))
        self.setGridSize(QSize(120, 158))
        self.setSpacing(4)
        self.setFixedWidth(140)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.clicked.connect(lambda index: self.pageActivated.emit(index.row()))

    def set_current_page(self, row: int) -> None:
        index = self.model().index(row, 0)
        if index.isValid():
            self.blockSignals(True)
            self.setCurrentIndex(index)
            self.blockSignals(False)
            self.scrollTo(index)


class OrganiserView(QListView):
    """Thumbnail grid: multi-select, drag to reorder, Delete key removes pages."""

    def __init__(self, model: ThumbnailModel, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Organiser")
        _base_list(self, model)
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setIconSize(THUMB_BOX)
        self.setGridSize(QSize(THUMB_BOX.width() + 34, THUMB_BOX.height() + 40))
        self.setSpacing(6)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        # Static movement + model-driven drops = reorder, not free positioning.
        self.setMovement(QListView.Movement.Static)
        self.setDragEnabled(True)
        self.viewport().setAcceptDrops(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setDragDropOverwriteMode(False)
        model.movedTo.connect(self.select_rows)

    def selected_rows(self) -> list[int]:
        return sorted(i.row() for i in self.selectionModel().selectedIndexes())

    def select_rows(self, rows: list[int]) -> None:
        selection = self.selectionModel()
        selection.clearSelection()
        for row in rows:
            index = self.model().index(row, 0)
            if index.isValid():
                selection.select(index, selection.SelectionFlag.Select)
        if rows:
            self.scrollTo(self.model().index(rows[0], 0))
