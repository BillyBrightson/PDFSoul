"""Home screen: drop zone, a searchable "Tools" and "Convert" list, and recent files."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from pdfsoul import AUTHOR, DISPLAY_NAME
from pdfsoul.app import icons
from pdfsoul.app.panels import GROUPS, HOME_COLUMNS, TOOLS, Tool
from pdfsoul.app.theme import tokens
from pdfsoul.app.widgets import muted

SUBGROUP_NAMES = {"Convert from PDF": "From PDF", "Convert to PDF": "To PDF"}


class DropZone(QFrame):
    filesDropped = Signal(list)
    browseRequested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("DropZone")
        self.setAcceptDrops(True)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(18)
        self.icon = QLabel()
        self.icon.setFixedSize(52, 52)
        self.icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        text = QVBoxLayout()
        text.setSpacing(3)
        title = QLabel("Drop files here to get started")
        title.setObjectName("DropTitle")
        hint = muted("A PDF opens in the viewer · several PDFs go to Merge · Word, Excel, "
                     "PowerPoint, web pages and images convert to PDF")
        text.addWidget(title)
        text.addWidget(hint)
        button = QPushButton("Open a file…")
        button.setObjectName("Primary")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(self.browseRequested)
        layout.addWidget(self.icon)
        layout.addLayout(text, 1)
        layout.addWidget(button)
        self.refresh_icons()

    def refresh_icons(self) -> None:
        self.icon.setPixmap(icons.chip("upload", tokens().accent, 52))

    def _set_dragging(self, on: bool) -> None:
        self.setProperty("dragging", on)
        self.style().unpolish(self)
        self.style().polish(self)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            self._set_dragging(True)
            event.acceptProposedAction()

    def dragLeaveEvent(self, event) -> None:
        self._set_dragging(False)

    def dropEvent(self, event: QDropEvent) -> None:
        self._set_dragging(False)
        paths = [Path(u.toLocalFile()) for u in event.mimeData().urls() if u.isLocalFile()]
        if paths:
            self.filesDropped.emit(paths)
            event.acceptProposedAction()


class ToolRow(QPushButton):
    """Icon and name, muted until hovered — the look of a clean link list."""

    def __init__(self, tool: Tool, parent: QWidget | None = None) -> None:
        super().__init__(tool.name.replace("&", "&&"), parent)
        self.tool = tool
        self.setObjectName("ToolRow")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setIconSize(QSize(22, 22))
        self.setToolTip(tool.description)
        self.refresh_icon()

    def refresh_icon(self) -> None:
        self.setIcon(self.tool.icon(tokens().muted, size=20))

    def matches(self, words: list[str]) -> bool:
        haystack = f"{self.tool.name} {self.tool.description} {self.tool.keywords} " \
                   f"{self.tool.group}".lower()
        return all(w in haystack for w in words)


class HomePage(QScrollArea):
    toolChosen = Signal(str)
    recentChosen = Signal(Path)
    aboutRequested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Home")
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget(objectName="HomeBody")
        outer = QHBoxLayout(body)
        outer.setContentsMargins(0, 0, 0, 0)
        content = QWidget()
        content.setMaximumWidth(1080)
        outer.addStretch(1)
        outer.addWidget(content, 100)
        outer.addStretch(1)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(40, 34, 40, 34)
        layout.setSpacing(22)

        header = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(4)
        title = QLabel("What would you like to do?")
        title.setObjectName("HomeTitle")
        titles.addWidget(title)
        sub = QLabel("Every PDF job, offline. Your files never leave this computer.")
        sub.setObjectName("HomeSub")
        titles.addWidget(sub)
        header.addLayout(titles, 1)
        self.search = QLineEdit(objectName="HomeSearch")
        self.search.setPlaceholderText("Search tools…")
        self.search.setClearButtonEnabled(True)
        self.search.setFixedWidth(260)
        self._search_icon = self.search.addAction(icons.icon("search", tokens().muted),
                                                  QLineEdit.ActionPosition.LeadingPosition)
        self.search.textChanged.connect(self._filter)
        self.search.returnPressed.connect(self._open_first_match)
        header.addWidget(self.search, alignment=Qt.AlignmentFlag.AlignBottom)
        layout.addLayout(header)

        self.drop_zone = DropZone()
        layout.addWidget(self.drop_zone)

        columns = QHBoxLayout()
        columns.setSpacing(36)
        self.rows: list[ToolRow] = []
        self._subgroups: list[tuple[QLabel, list[ToolRow]]] = []
        for column_title, groups in HOME_COLUMNS:
            column = QVBoxLayout()
            column.setSpacing(2)
            heading = QLabel(column_title)
            heading.setObjectName("ColumnTitle")
            column.addWidget(heading)
            for group in (g for g in GROUPS if g in groups):
                label = QLabel(SUBGROUP_NAMES.get(group, group).upper())
                label.setObjectName("Section")
                label.setContentsMargins(4, 12, 0, 4)
                column.addWidget(label)
                members = []
                for tool in (t for t in TOOLS if t.group == group and t.on_home):
                    row = ToolRow(tool)
                    row.clicked.connect(lambda _=False, t=tool.id: self.toolChosen.emit(t))
                    column.addWidget(row)
                    members.append(row)
                    self.rows.append(row)
                self._subgroups.append((label, members))
            column.addStretch(1)
            columns.addLayout(column, 1)

        recent_col = QVBoxLayout()
        recent_col.setSpacing(2)
        recent_head = QHBoxLayout()
        recent_title = QLabel("Recent")
        recent_title.setObjectName("ColumnTitle")
        recent_head.addWidget(recent_title)
        recent_head.addStretch(1)
        self.clear_recent = QPushButton("Clear")
        self.clear_recent.setObjectName("Link")
        self.clear_recent.setCursor(Qt.CursorShape.PointingHandCursor)
        recent_head.addWidget(self.clear_recent)
        recent_col.addLayout(recent_head)
        recent_col.addSpacing(10)
        self._recent_box = QVBoxLayout()
        self._recent_box.setSpacing(2)
        recent_col.addLayout(self._recent_box)
        self.no_recent = muted("Files you open will appear here.")
        self.no_recent.setContentsMargins(4, 0, 0, 0)
        recent_col.addWidget(self.no_recent)
        recent_col.addStretch(1)
        columns.addLayout(recent_col, 1)
        layout.addLayout(columns)

        self.no_match = QLabel("No tools match your search.")
        self.no_match.setObjectName("NoMatch")
        self.no_match.hide()
        layout.addWidget(self.no_match)
        layout.addStretch(1)

        self.credit = QPushButton(f"Made with love by {AUTHOR}  ·  Free for personal and "
                                  "commercial use", objectName="Credit")
        self.credit.setCursor(Qt.CursorShape.PointingHandCursor)
        self.credit.setIconSize(QSize(14, 14))
        self.credit.setToolTip(f"About {DISPLAY_NAME}")
        self.credit.clicked.connect(self.aboutRequested)
        layout.addWidget(self.credit, alignment=Qt.AlignmentFlag.AlignHCenter)
        self.setWidget(body)
        self._recent_rows: list[QPushButton] = []
        self._recent_paths: list[Path] = []

    # -- recent files --------------------------------------------------------------------------

    def set_recent(self, paths: list[Path]) -> None:
        for row in self._recent_rows:
            row.deleteLater()
        self._recent_rows = []
        self._recent_paths = list(paths)
        for path in paths[:8]:
            row = QPushButton(path.name if path.exists() else f"{path.name}  (missing)")
            row.setObjectName("ToolRow")
            row.setCursor(Qt.CursorShape.PointingHandCursor)
            row.setIconSize(QSize(22, 22))
            row.setToolTip(str(path))
            row.clicked.connect(lambda _=False, p=path: self.recentChosen.emit(p))
            self._recent_box.addWidget(row)
            self._recent_rows.append(row)
        self._paint_recent()
        self.clear_recent.setVisible(bool(paths))
        self.no_recent.setVisible(not paths)

    def _paint_recent(self) -> None:
        for row in self._recent_rows:
            row.setIcon(icons.badge_icon("pdf", 20))

    # -- search --------------------------------------------------------------------------------

    def _filter(self, text: str) -> None:
        words = text.lower().split()
        shown = 0
        for label, members in self._subgroups:
            visible = 0
            for row in members:
                hit = row.matches(words)
                row.setVisible(hit)
                visible += hit
            label.setVisible(visible > 0)
            shown += visible
        self.no_match.setVisible(shown == 0)

    def _open_first_match(self) -> None:
        words = self.search.text().lower().split()
        for row in self.rows:
            if row.matches(words):
                self.toolChosen.emit(row.tool.id)
                return

    def refresh_icons(self) -> None:
        self.drop_zone.refresh_icons()
        for row in self.rows:
            row.refresh_icon()
        self._search_icon.setIcon(icons.icon("search", tokens().muted))
        self.credit.setIcon(icons.icon("heart", "#e5484d"))
        self._paint_recent()
