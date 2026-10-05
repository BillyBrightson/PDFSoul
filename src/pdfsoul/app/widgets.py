"""Reusable widgets for the tool panels."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QDragEnterEvent, QDropEvent, QFontMetrics
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from pdfsoul.core.types import Result

PDF_FILTER = "PDF files (*.pdf)"


def show_in_folder(path: Path) -> None:
    path = Path(path)
    if sys.platform == "win32":
        subprocess.Popen(f'explorer /select,"{path}"')
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(path)])
    else:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent if path.is_file() else path)))


def open_with_system(path: Path) -> None:
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


def muted(text: str, wrap: bool = True) -> QLabel:
    label = QLabel(text)
    label.setObjectName("Muted")
    label.setWordWrap(wrap)
    return label


class ElidedLabel(QLabel):
    """Shows a path shortened in the middle, full path in the tooltip."""

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._full = ""
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.set_full_text(text)

    def set_full_text(self, text: str) -> None:
        self._full = text
        self.setToolTip(text)
        self._elide()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._elide()

    def _elide(self) -> None:
        metrics = QFontMetrics(self.font())
        self.setText(metrics.elidedText(self._full, Qt.TextElideMode.ElideMiddle,
                                        max(self.width(), 80)))


class OutputPicker(QWidget):
    """Where the result goes: a sensible default that the user can change."""

    def __init__(self, kind: str, default: Callable[[], Path | None],
                 file_filter: str = PDF_FILTER, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        assert kind in {"file", "folder"}
        self._kind, self._default, self._filter = kind, default, file_filter
        self._override: Path | None = None
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._label = ElidedLabel()
        self._label.setObjectName("Muted")
        change = QPushButton("Change…")
        change.clicked.connect(self._choose)
        layout.addWidget(self._label, 1)
        layout.addWidget(change)
        self.refresh()

    def reset(self) -> None:
        self._override = None
        self.refresh()

    def set_filter(self, file_filter: str) -> None:
        self._filter = file_filter

    def path(self) -> Path | None:
        return self._override or self._default()

    def refresh(self) -> None:
        path = self.path()
        self._label.set_full_text(str(path) if path else "—")

    def _choose(self) -> None:
        current = self.path()
        if self._kind == "file":
            chosen, _ = QFileDialog.getSaveFileName(self, "Save as", str(current or ""),
                                                    self._filter)
        else:
            chosen = QFileDialog.getExistingDirectory(
                self, "Choose folder", str(current.parent if current else ""))
        if chosen:
            self._override = Path(chosen)
            self.refresh()


class ResultCard(QFrame):
    """The outcome of the last run: message, output path, Open and Show in folder."""

    openRequested = Signal(Path)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ResultCard")
        self._outputs: list[Path] = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        self._message = QLabel()
        self._message.setWordWrap(True)
        self._message.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._path = ElidedLabel()
        self._path.setObjectName("Muted")
        buttons = QHBoxLayout()
        self._open = QPushButton("Open")
        self._folder = QPushButton("Show in folder")
        self._open.clicked.connect(lambda: self._outputs and self.openRequested.emit(
            self._outputs[0]))
        self._folder.clicked.connect(lambda: self._outputs and show_in_folder(self._outputs[0]))
        buttons.addWidget(self._open)
        buttons.addWidget(self._folder)
        buttons.addStretch(1)
        layout.addWidget(self._message)
        layout.addWidget(self._path)
        layout.addLayout(buttons)
        self.hide()

    def show_result(self, result: Result) -> None:
        self._outputs = list(result.outputs)
        self.setProperty("error", False)
        self._restyle()
        self._message.setText(f"✓ {result.message}")
        if len(self._outputs) == 1:
            self._path.set_full_text(str(self._outputs[0]))
        elif self._outputs:
            self._path.set_full_text(f"{len(self._outputs)} files in {self._outputs[0].parent}")
        self._path.setVisible(bool(self._outputs))
        self._open.setVisible(len(self._outputs) == 1)
        self._folder.setVisible(bool(self._outputs))
        self.show()

    def show_error(self, message: str) -> None:
        self._outputs = []
        self.setProperty("error", True)
        self._restyle()
        self._message.setText(message)
        for widget in (self._path, self._open, self._folder):
            widget.hide()
        self.show()

    def _restyle(self) -> None:
        self.style().unpolish(self)
        self.style().polish(self)


class FileListWidget(QWidget):
    """Ordered list of input files: add, drag in from Explorer, drag to reorder, remove.

    With ``ranges=True`` each file gets an editable "Pages" cell (blank = all pages).
    """

    changed = Signal()

    def __init__(self, extensions: set[str], file_filter: str, ranges: bool = False,
                 describe: Callable[[Path], str] | None = None,
                 on_add: Callable[[Path], bool] | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._extensions = {e.lower() for e in extensions}
        self._filter = file_filter
        self._ranges = ranges
        self._describe = describe
        self._on_add = on_add
        self.passwords: dict[str, str] = {}

        self.tree = _DropTree(self._accept_urls)
        headers = ["File", "Pages", ""] if ranges else ["File", ""]
        self.tree.setColumnCount(len(headers))
        self.tree.setHeaderLabels(headers)
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.tree.setEditTriggers(QAbstractItemView.EditTrigger.AllEditTriggers)
        self.tree.setMinimumHeight(180)
        header = self.tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in range(1, len(headers)):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.model().rowsMoved.connect(lambda *_: self.changed.emit())
        self.tree.itemChanged.connect(lambda *_: self.changed.emit())

        add = QPushButton("Add files…")
        add.clicked.connect(self._browse)
        folder = QPushButton("Add folder…")
        folder.clicked.connect(self._browse_folder)
        from pdfsoul.app import icons
        from pdfsoul.app.theme import tokens

        remove, up, down = QToolButton(), QToolButton(), QToolButton()
        for button, glyph, tip in ((remove, "trash", "Remove selected"),
                                   (up, "chevron-up", "Move up"),
                                   (down, "chevron-down", "Move down")):
            button.setIcon(icons.icon(glyph, tokens().text))
            button.setToolTip(tip)
        remove.clicked.connect(self._remove_selected)
        up.clicked.connect(lambda: self._move(-1))
        down.clicked.connect(lambda: self._move(1))
        row = QHBoxLayout()
        row.setSpacing(6)
        for b in (add, folder):
            row.addWidget(b)
        row.addStretch(1)
        for b in (remove, up, down):
            row.addWidget(b)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.tree)
        layout.addLayout(row)
        hint = muted("Drag files here, or drag rows to reorder."
                     + (" Pages: e.g. 1-3,7 (blank = all)." if ranges else ""))
        layout.addWidget(hint)

    # -- data ----------------------------------------------------------------------------------

    def paths(self) -> list[Path]:
        return [Path(self.tree.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole))
                for i in range(self.tree.topLevelItemCount())]

    def page_ranges(self) -> list[str]:
        if not self._ranges:
            return []
        return [self.tree.topLevelItem(i).text(1).strip()
                for i in range(self.tree.topLevelItemCount())]

    def add_paths(self, paths: list[Path]) -> None:
        for path in paths:
            path = Path(path)
            if path.is_dir():
                self.add_paths(sorted(p for p in path.iterdir()
                                      if p.suffix.lower() in self._extensions))
                continue
            if path.suffix.lower() not in self._extensions or not path.is_file():
                continue
            if self._on_add and not self._on_add(path):
                continue
            item = QTreeWidgetItem([path.name, "", ""] if self._ranges else [path.name, ""])
            item.setData(0, Qt.ItemDataRole.UserRole, str(path))
            item.setToolTip(0, str(path))
            flags = (Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
                     | Qt.ItemFlag.ItemIsDragEnabled)
            if self._ranges:
                flags |= Qt.ItemFlag.ItemIsEditable
            item.setFlags(flags)
            if self._describe:
                item.setText(self.tree.columnCount() - 1, self._describe(path))
            self.tree.addTopLevelItem(item)
        self.changed.emit()

    def clear(self) -> None:
        self.tree.clear()
        self.passwords.clear()
        self.changed.emit()

    def sizeHint(self) -> QSize:
        return QSize(300, 260)

    # -- actions -------------------------------------------------------------------------------

    def _accept_urls(self, paths: list[Path]) -> None:
        self.add_paths(paths)

    def _browse(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "Add files", "", self._filter)
        self.add_paths([Path(f) for f in files])

    def _browse_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Add folder")
        if folder:
            self.add_paths([Path(folder)])

    def _remove_selected(self) -> None:
        for item in self.tree.selectedItems():
            self.passwords.pop(item.data(0, Qt.ItemDataRole.UserRole), None)
            self.tree.takeTopLevelItem(self.tree.indexOfTopLevelItem(item))
        self.changed.emit()

    def _move(self, delta: int) -> None:
        items = sorted(self.tree.selectedItems(), key=self.tree.indexOfTopLevelItem,
                       reverse=delta > 0)
        for item in items:
            row = self.tree.indexOfTopLevelItem(item)
            target = row + delta
            if 0 <= target < self.tree.topLevelItemCount():
                self.tree.takeTopLevelItem(row)
                self.tree.insertTopLevelItem(target, item)
                item.setSelected(True)
        self.changed.emit()


class _DropTree(QTreeWidget):
    """Tree that reorders internally and also accepts files dragged in from outside."""

    def __init__(self, on_files: Callable[[list[Path]], None]) -> None:
        super().__init__()
        self._on_files = on_files
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        if event.mimeData().hasUrls():
            self._on_files([Path(u.toLocalFile()) for u in event.mimeData().urls()
                            if u.isLocalFile()])
            event.acceptProposedAction()
        else:
            super().dropEvent(event)


class PageRangeEdit(QLineEdit):
    def __init__(self, placeholder: str = "All pages — or e.g. 1-3,5,8-",
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setPlaceholderText(placeholder)
        self.setClearButtonEnabled(True)
