"""Main window: tools on the left, the document in the middle, options on the right."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from threading import Event

from PySide6.QtCore import QByteArray, QEvent, QSize, Qt, QTimer
from PySide6.QtGui import (
    QAction,
    QCloseEvent,
    QColor,
    QDragEnterEvent,
    QDropEvent,
    QKeySequence,
)
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QToolBar,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from pdfsoul import DISPLAY_NAME
from pdfsoul.app import icons
from pdfsoul.app.dialogs import SettingsDialog, ask_password, show_about, show_error
from pdfsoul.app.home import HomePage
from pdfsoul.app.jobs import JobRunner, JobSpec
from pdfsoul.app.logging_setup import log_dir
from pdfsoul.app.panels import GROUPS, TOOLS, TOOLS_BY_ID, Tool
from pdfsoul.app.panels.base import ToolPanel
from pdfsoul.app.panels.convert import ImagesToPdfPanel
from pdfsoul.app.panels.export import ToPdfPanel
from pdfsoul.app.panels.organise import MergePanel, OrganisePanel
from pdfsoul.app.session import DocumentSession
from pdfsoul.app.settings import Settings
from pdfsoul.app.theme import is_dark, tokens
from pdfsoul.app.thumbnails import OrganiserView, ThumbnailModel, ThumbnailStrip
from pdfsoul.app.viewer import ZOOM_STEPS, PageView, ZoomMode
from pdfsoul.app.widgets import PDF_FILTER, open_with_system
from pdfsoul.core import organise, to_pdf
from pdfsoul.core.convert import IMAGE_EXTENSIONS
from pdfsoul.core.document import open_pdf
from pdfsoul.core.organise import PageRef
from pdfsoul.core.types import (
    PasswordRequired,
    PdfSoulError,
    ProgressFn,
    Result,
    WrongPassword,
)

log = logging.getLogger(__name__)

HOME = "home"


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self.settings = settings
        self.session = DocumentSession(self)
        self.runner = JobRunner(self)
        self.thumb_model = ThumbnailModel(self.session, self.devicePixelRatioF())
        self.panels: dict[str, ToolPanel] = {}
        self._tool: str | None = None
        self._showing_home = True
        self._organiser_mode = False

        self.setWindowTitle(DISPLAY_NAME)
        self.setAcceptDrops(True)
        self.resize(1360, 860)
        self.setMinimumSize(QSize(960, 600))

        self._build_actions()
        self._build_ui()
        self._build_menus()
        self._build_status_bar()
        self._refresh_icons()
        self._wire()
        self._restore_state()
        self._update_everything()

    # =========================================================================================
    # UI construction

    def _build_ui(self) -> None:
        self.sidebar = QWidget(objectName="Sidebar")
        side = QVBoxLayout(self.sidebar)
        side.setContentsMargins(12, 16, 12, 12)
        side.setSpacing(8)
        brand_row = QHBoxLayout()
        brand_row.setContentsMargins(6, 0, 0, 6)
        brand_row.setSpacing(10)
        self.brand_mark = QLabel()
        brand_row.addWidget(self.brand_mark)
        brand_text = QVBoxLayout()
        brand_text.setSpacing(0)
        brand = QLabel(DISPLAY_NAME, objectName="Brand")
        brand_text.addWidget(brand)
        brand_text.addWidget(QLabel("Offline PDF toolkit", objectName="BrandSub"))
        brand_row.addLayout(brand_text, 1)
        side.addLayout(brand_row)
        self.tool_list = QTreeWidget(objectName="ToolList")
        self.tool_list.setHeaderHidden(True)
        self.tool_list.setIndentation(0)
        self.tool_list.setRootIsDecorated(False)
        self.tool_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.tool_list.setIconSize(QSize(18, 18))
        self.tool_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        home = QTreeWidgetItem(["Home"])
        home.setData(0, Qt.ItemDataRole.UserRole, HOME)
        self.tool_list.addTopLevelItem(home)
        self._tool_items: dict[str, QTreeWidgetItem] = {HOME: home}
        self._group_items: list[QTreeWidgetItem] = []
        for group in GROUPS:
            header = QTreeWidgetItem([group.upper()])
            header.setFlags(Qt.ItemFlag.ItemIsEnabled)
            font = header.font(0)
            font.setPointSizeF(font.pointSizeF() * 0.8)
            font.setBold(True)
            header.setFont(0, font)
            header.setSizeHint(0, QSize(0, 30))
            header.setTextAlignment(0, Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignLeft)
            self.tool_list.addTopLevelItem(header)
            self._group_items.append(header)
            for tool in (t for t in TOOLS if t.group == group):
                item = QTreeWidgetItem([tool.name])
                item.setData(0, Qt.ItemDataRole.UserRole, tool.id)
                item.setToolTip(0, tool.description)
                header.addChild(item)
                self._tool_items[tool.id] = item
        self.tool_list.expandAll()
        self.tool_list.setItemsExpandable(False)
        side.addWidget(self.tool_list, 1)
        self.settings_button = QPushButton("Settings", objectName="SidebarButton")
        self.settings_button.setIconSize(QSize(18, 18))
        self.settings_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.settings_button.clicked.connect(self.open_settings)
        side.addWidget(self.settings_button)
        self.about_button = QPushButton("About", objectName="SidebarButton")
        self.about_button.setIconSize(QSize(18, 18))
        self.about_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.about_button.clicked.connect(lambda: show_about(self))
        side.addWidget(self.about_button)

        # -- centre
        self.home = HomePage()
        self.viewer = PageView(self.session)
        self.strip = ThumbnailStrip(self.thumb_model)
        self.organiser = OrganiserView(self.thumb_model)
        viewer_page = QWidget()
        vlayout = QVBoxLayout(viewer_page)
        vlayout.setContentsMargins(0, 0, 0, 0)
        vlayout.setSpacing(0)
        vlayout.addWidget(self._build_viewer_bar())
        vlayout.addWidget(self._build_search_bar())
        body = QHBoxLayout()
        body.setSpacing(0)
        body.addWidget(self.strip)
        body.addWidget(self.viewer, 1)
        vlayout.addLayout(body, 1)
        organiser_page = QWidget()
        olayout = QVBoxLayout(organiser_page)
        olayout.setContentsMargins(0, 0, 0, 0)
        olayout.setSpacing(0)
        olayout.addWidget(self._build_organiser_bar())
        olayout.addWidget(self.organiser, 1)
        self.centre = QStackedWidget()
        for widget in (self.home, viewer_page, organiser_page):
            self.centre.addWidget(widget)
        self._viewer_page, self._organiser_page = viewer_page, organiser_page

        # -- options pane
        self.options = QWidget(objectName="OptionsPane")
        olay = QVBoxLayout(self.options)
        olay.setContentsMargins(0, 0, 0, 0)
        self.panel_stack = QStackedWidget()
        olay.addWidget(self.panel_stack)
        for tool in TOOLS:
            panel = tool.panel(self)
            self.panels[tool.id] = panel
            self.panel_stack.addWidget(panel)
        self.options.setMinimumWidth(340)
        self.options.setMaximumWidth(480)

        self.splitter = QSplitter()
        self.splitter.setHandleWidth(1)
        self.splitter.addWidget(self.sidebar)
        self.splitter.addWidget(self.centre)
        self.splitter.addWidget(self.options)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setCollapsible(1, False)
        self.splitter.setSizes([250, 780, 370])
        self.sidebar.setMinimumWidth(220)
        self.setCentralWidget(self.splitter)

    def _tool_button(self, action: QAction) -> QToolButton:
        button = QToolButton()
        button.setDefaultAction(action)
        button.setAutoRaise(True)
        return button

    def _build_viewer_bar(self) -> QWidget:
        bar = QToolBar(objectName="ViewerBar")
        bar.setIconSize(QSize(18, 18))
        bar.setMovable(False)
        bar.addAction(self.act_thumbs)
        self.doc_title = QLabel("", objectName="DocTitle")
        self.doc_title.setMaximumWidth(280)
        self.doc_meta = QLabel("", objectName="DocMeta")
        bar.addWidget(self.doc_title)
        bar.addWidget(self.doc_meta)
        left = QWidget()
        left.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        bar.addWidget(left)
        bar.addAction(self.act_prev_page)
        self.page_spin = QSpinBox()
        self.page_spin.setMinimum(1)
        self.page_spin.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        self.page_spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.page_spin.setFixedWidth(56)
        self.page_spin.setKeyboardTracking(False)
        bar.addWidget(self.page_spin)
        self.page_total = QLabel(" / 0 ")
        bar.addWidget(self.page_total)
        bar.addAction(self.act_next_page)
        bar.addSeparator()
        bar.addAction(self.act_zoom_out)
        self.zoom_combo = QComboBox()
        self.zoom_combo.setEditable(True)
        self.zoom_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.zoom_combo.addItem("Fit width", ZoomMode.FIT_WIDTH)
        self.zoom_combo.addItem("Fit page", ZoomMode.FIT_PAGE)
        for z in ZOOM_STEPS:
            self.zoom_combo.addItem(f"{z * 100:.0f}%", z)
        self.zoom_combo.setFixedWidth(124)
        bar.addWidget(self.zoom_combo)
        bar.addAction(self.act_zoom_in)
        bar.addSeparator()
        bar.addAction(self.act_rotate_left)
        bar.addAction(self.act_rotate_right)
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        bar.addWidget(spacer)
        bar.addAction(self.act_find)
        bar.addAction(self.act_organiser)
        bar.widgetForAction(self.act_organiser).setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        return bar

    def _build_organiser_bar(self) -> QWidget:
        bar = QToolBar()
        bar.setMovable(False)
        bar.setIconSize(QSize(18, 18))
        bar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        for action in (self.act_rotate_left, self.act_rotate_right, self.act_duplicate,
                       self.act_insert_blank, self.act_delete_pages, self.act_extract):
            bar.addAction(action)
        bar.addSeparator()
        bar.addAction(self.act_undo)
        bar.addAction(self.act_redo)
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        bar.addWidget(spacer)
        bar.addAction(self.act_organiser)
        return bar

    def _build_search_bar(self) -> QWidget:
        self.search_bar = QWidget(objectName="SearchBar")
        row = QHBoxLayout(self.search_bar)
        row.setContentsMargins(8, 4, 8, 4)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Find in document")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setMaximumWidth(320)
        self.search_case = QToolButton()
        self.search_case.setText("Aa")
        self.search_case.setCheckable(True)
        self.search_case.setToolTip("Match case")
        prev_button, next_button, close_button = QToolButton(), QToolButton(), QToolButton()
        prev_button.setToolTip("Previous match (Shift+F3)")
        next_button.setToolTip("Next match (F3)")
        close_button.setToolTip("Close (Esc)")
        self._search_buttons = {"chevron-up": prev_button, "chevron-down": next_button,
                                "x": close_button}
        self.search_status = QLabel("")
        self.search_status.setObjectName("Muted")
        for widget in (self.search_edit, self.search_case, prev_button, next_button,
                       self.search_status):
            row.addWidget(widget)
        row.addStretch(1)
        row.addWidget(close_button)
        prev_button.clicked.connect(lambda: self._step_match(-1))
        next_button.clicked.connect(lambda: self._step_match(1))
        close_button.clicked.connect(self._close_search)
        self.search_bar.hide()

        self._search_timer = QTimer(self, singleShot=True, interval=0)
        self._search_timer.timeout.connect(self._search_step)
        self._search_debounce = QTimer(self, singleShot=True, interval=300)
        self._search_debounce.timeout.connect(self._start_search)
        self._reset_search_state()
        return self.search_bar

    def _build_status_bar(self) -> None:
        status = self.statusBar()
        self.page_label = QLabel("")
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setFixedWidth(200)
        self.progress.setFixedHeight(6)
        self.progress.setTextVisible(False)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setFlat(True)
        self.cancel_button.clicked.connect(self.runner.cancel)
        self.job_label = QLabel("")
        status.addPermanentWidget(self.job_label)
        status.addPermanentWidget(self.progress)
        status.addPermanentWidget(self.cancel_button)
        status.addPermanentWidget(self.page_label)
        for widget in (self.progress, self.cancel_button, self.job_label):
            widget.hide()

    def _action(self, text: str, slot, shortcut: QKeySequence | str | list | None = None,
                tip: str = "") -> QAction:
        action = QAction(text, self)
        action.triggered.connect(lambda *_: slot())
        if isinstance(shortcut, list):
            action.setShortcuts(shortcut)
        elif shortcut is not None:
            action.setShortcut(shortcut)
        if tip or shortcut:
            keys = action.shortcut().toString(QKeySequence.SequenceFormat.NativeText)
            action.setToolTip(f"{tip or text.replace('&', '')}" + (f"  ({keys})" if keys else ""))
        self.addAction(action)
        return action

    def _build_actions(self) -> None:
        K = QKeySequence
        self.act_open = self._action("&Open…", self.choose_and_open, K.StandardKey.Open)
        self.act_save = self._action("&Save", lambda: self.save(), K.StandardKey.Save)
        self.act_save_as = self._action("Save &As…", lambda: self.save(save_as=True),
                                        "Ctrl+Shift+S")
        self.act_close = self._action("&Close", self.close_document, K.StandardKey.Close)
        self.act_settings = self._action("Se&ttings…", self.open_settings, "Ctrl+,")
        self.act_quit = self._action("&Quit", self.close, K.StandardKey.Quit)

        self.act_undo = self._action("Undo", self.session.undo, "Ctrl+Z", "Undo page edit")
        self.act_redo = self._action("Redo", self.session.redo, ["Ctrl+Y", "Ctrl+Shift+Z"],
                                     "Redo page edit")
        self.act_rotate_right = self._action("Rotate right", lambda: self.rotate(90), "Ctrl+R")
        self.act_rotate_left = self._action("Rotate left", lambda: self.rotate(-90),
                                            "Ctrl+Shift+R")
        self.act_delete_pages = self._action("Delete", self.delete_pages, K.StandardKey.Delete,
                                             "Delete pages")
        self.act_duplicate = self._action("Duplicate", self.duplicate_pages, "Ctrl+D",
                                          "Duplicate pages")
        self.act_insert_blank = self._action("Blank page", self.insert_blank, "Ctrl+B",
                                             "Insert a blank page after")
        self.act_extract = self._action("Extract…", self.extract_pages, "Ctrl+E",
                                        "Save the selected pages as a new PDF")

        self.act_find = self._action("Find", self.show_search, K.StandardKey.Find,
                                     "Find text")
        self.act_find_next = self._action("Find next", lambda: self._step_match(1), "F3")
        self.act_find_prev = self._action("Find previous", lambda: self._step_match(-1),
                                          "Shift+F3")
        self.act_zoom_in = self._action("Zoom &in", self.viewer_zoom_in, ["Ctrl++", "Ctrl+="],
                                        "Zoom in")
        self.act_zoom_out = self._action("Zoom &out", self.viewer_zoom_out, "Ctrl+-",
                                         "Zoom out")
        self.act_fit_width = self._action("Fit &width", lambda: self.viewer.set_zoom_mode(
            ZoomMode.FIT_WIDTH), "Ctrl+0")
        self.act_fit_page = self._action("Fit &page", lambda: self.viewer.set_zoom_mode(
            ZoomMode.FIT_PAGE), "Ctrl+9")
        self.act_prev_page = self._action("Previous page", lambda: self.viewer.goto_page(
            self.viewer.current_page - 1))
        self.act_next_page = self._action("Next page", lambda: self.viewer.goto_page(
            self.viewer.current_page + 1))
        self.act_organiser = self._action("Organise", self.toggle_organiser, "Ctrl+T",
                                          "Switch between viewer and page grid")
        self.act_organiser.setCheckable(True)
        self.act_thumbs = self._action("Thumbnails", self.toggle_thumbnails, "F4")
        self.act_thumbs.setCheckable(True)
        self.act_about = self._action(f"&About {DISPLAY_NAME}", lambda: show_about(self))
        self.act_logs = self._action("Open &log folder", lambda: open_with_system(log_dir()))
        self._action_icons = {
            self.act_undo: "undo", self.act_redo: "redo", self.act_rotate_right: "rotate-cw",
            self.act_rotate_left: "rotate-ccw", self.act_delete_pages: "trash",
            self.act_duplicate: "copy", self.act_insert_blank: "file-plus",
            self.act_extract: "file-out", self.act_find: "search", self.act_zoom_in: "plus",
            self.act_zoom_out: "minus", self.act_fit_width: "fit-width",
            self.act_prev_page: "chevron-left", self.act_next_page: "chevron-right",
            self.act_organiser: "grid", self.act_thumbs: "sidebar", self.act_open: "folder",
            self.act_settings: "sliders",
        }

    def _refresh_icons(self) -> None:
        """Tint every icon for the current theme (called again when the theme changes)."""
        t = tokens()
        for action, name in self._action_icons.items():
            action.setIcon(icons.icon(name, t.text, t.accent, t.muted))
        for name, button in self._search_buttons.items():
            button.setIcon(icons.icon(name, t.text))
        self.brand_mark.setPixmap(icons.app_mark(30, accent=t.accent))
        self.settings_button.setIcon(icons.icon("sliders", t.muted))
        self.about_button.setIcon(icons.icon("info", t.muted))
        self._tool_items[HOME].setIcon(0, icons.icon("home", t.muted, t.text))
        for tool in TOOLS:
            self._tool_items[tool.id].setIcon(0, tool.icon(t.muted, t.text))
        for header in self._group_items:
            header.setForeground(0, QColor(t.text))
        for tool in TOOLS:
            glyph = icons.badge(tool.glyph, 36) if tool.is_badge else icons.chip(
                tool.glyph, t.accent, 40, is_dark())
            empty = tool.pixmap(t.muted, 34)
            self.panels[tool.id].decorate(glyph, tool.group, empty)
        self.home.refresh_icons()

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.PaletteChange and hasattr(self, "_action_icons"):
            self._refresh_icons()

    def _build_menus(self) -> None:
        bar = self.menuBar()
        file_menu = bar.addMenu("&File")
        file_menu.addAction(self.act_open)
        self.recent_menu = file_menu.addMenu("Open &Recent")
        self.recent_menu.aboutToShow.connect(self._fill_recent_menu)
        file_menu.addSeparator()
        for action in (self.act_save, self.act_save_as, self.act_close):
            file_menu.addAction(action)
        file_menu.addSeparator()
        file_menu.addAction(self.act_settings)
        file_menu.addSeparator()
        file_menu.addAction(self.act_quit)

        edit_menu = bar.addMenu("&Edit")
        for action in (self.act_undo, self.act_redo):
            edit_menu.addAction(action)
        edit_menu.addSeparator()
        for action in (self.act_rotate_right, self.act_rotate_left, self.act_duplicate,
                       self.act_insert_blank, self.act_delete_pages, self.act_extract):
            edit_menu.addAction(action)
        edit_menu.addSeparator()
        for action in (self.act_find, self.act_find_next, self.act_find_prev):
            edit_menu.addAction(action)

        view_menu = bar.addMenu("&View")
        for action in (self.act_zoom_in, self.act_zoom_out, self.act_fit_width,
                       self.act_fit_page):
            view_menu.addAction(action)
        view_menu.addSeparator()
        view_menu.addAction(self.act_thumbs)
        view_menu.addAction(self.act_organiser)

        tools_menu = bar.addMenu("&Tools")
        for group in GROUPS:
            for tool in (t for t in TOOLS if t.group == group):
                action = QAction(tool.name.replace("&", "&&"), self)
                action.triggered.connect(lambda _=False, t=tool.id: self.select_tool(t))
                tools_menu.addAction(action)
            tools_menu.addSeparator()

        help_menu = bar.addMenu("&Help")
        help_menu.addAction(self.act_logs)
        help_menu.addAction(self.act_about)

        self.organiser.setContextMenuPolicy(Qt.ContextMenuPolicy.ActionsContextMenu)
        for action in (self.act_rotate_left, self.act_rotate_right, self.act_duplicate,
                       self.act_insert_blank, self.act_delete_pages, self.act_extract):
            self.organiser.addAction(action)

    def _wire(self) -> None:
        self.tool_list.itemClicked.connect(self._sidebar_clicked)
        self.home.toolChosen.connect(self._home_tool)
        self.home.recentChosen.connect(self._open_recent)
        self.home.aboutRequested.connect(lambda: show_about(self))
        self.home.drop_zone.filesDropped.connect(self.handle_dropped)
        self.home.drop_zone.browseRequested.connect(self.choose_any)
        self.home.clear_recent.clicked.connect(self._clear_recent)

        self.session.opened.connect(self._on_opened)
        self.session.closed.connect(self._update_everything)
        self.session.planChanged.connect(self._on_plan_changed)

        self.viewer.currentPageChanged.connect(self._on_current_page)
        self.viewer.zoomChanged.connect(self._on_zoom_changed)
        self.strip.pageActivated.connect(self.viewer.goto_page)
        self.page_spin.valueChanged.connect(lambda v: self.viewer.goto_page(v - 1))
        self.zoom_combo.activated.connect(self._zoom_combo_chosen)
        self.zoom_combo.lineEdit().returnPressed.connect(self._zoom_typed)
        self.organiser.doubleClicked.connect(self._organiser_open_page)

        self.search_edit.textChanged.connect(lambda _: self._search_debounce.start())
        self.search_edit.returnPressed.connect(self._search_enter)
        self.search_case.toggled.connect(lambda _: self._start_search())

        self.runner.started.connect(self._job_started)
        self.runner.progress.connect(lambda f: self.progress.setValue(int(f * 1000)))
        self.runner.finished.connect(self._job_finished)
        self.runner.failed.connect(self._job_failed)
        self.runner.cancelled.connect(lambda: self._job_ended("Cancelled."))

        organise_panel = self.panels["organise"]
        assert isinstance(organise_panel, OrganisePanel)
        organise_panel.actionRequested.connect(self._organise_action)

    # =========================================================================================
    # AppContext (used by panels)

    def run_job(self, spec: JobSpec) -> None:
        if not self.runner.start(spec):
            self.statusBar().showMessage("Another job is still running.", 4000)

    def choose_and_open(self) -> bool:
        start = str(self.session.path.parent) if self.session.path else ""
        path, _ = QFileDialog.getOpenFileName(self, "Open PDF", start, PDF_FILTER)
        return self.open_file(Path(path)) if path else False

    def choose_any(self) -> None:
        """Open PDFs, or pick documents and images to convert — routed like a drop."""
        exts = sorted({".pdf"} | to_pdf.ALL_EXTENSIONS)
        filters = ";;".join([f"All supported files ({' '.join('*' + e for e in exts)})",
                             PDF_FILTER, to_pdf.file_filter()])
        files, _ = QFileDialog.getOpenFileNames(self, "Open or convert files", "", filters)
        if files:
            self.handle_dropped([Path(f) for f in files])

    def open_file(self, path: Path) -> bool:
        path = Path(path)
        if not self._confirm_discard():
            return False
        password: str | None = None
        while True:
            try:
                started = time.perf_counter()
                self.session.open(path, password)
                log.info("Opened %s in %.2fs", path, time.perf_counter() - started)
                break
            except PasswordRequired:
                password = ask_password(self, path.name)
            except WrongPassword:
                password = ask_password(self, path.name, wrong=True)
            except PdfSoulError as exc:
                show_error(self, str(exc))
                return False
            if password is None:
                return False
        return True

    def password_for(self, path: Path) -> str | None:
        password = ask_password(self, path.name)
        while password is not None:
            try:
                open_pdf(path, password).close()
                return password
            except WrongPassword:
                password = ask_password(self, path.name, wrong=True)
            except PdfSoulError as exc:
                show_error(self, str(exc))
                return None
        return None

    def current_page(self) -> int:
        if self._organiser_mode:
            rows = self.organiser.selected_rows()
            if rows:
                return rows[0]
        return max(self.viewer.current_page, 0)

    # =========================================================================================
    # Navigation between tools and views

    def select_tool(self, tool_id: str) -> None:
        if tool_id == HOME:
            self._tool = None
            self._showing_home = True
        else:
            tool: Tool = TOOLS_BY_ID[tool_id]
            self._tool = tool.id
            self._showing_home = False
            self._organiser_mode = tool.id == "organise"
            panel = self.panels[tool.id]
            self.panel_stack.setCurrentWidget(panel)
            panel.refresh()
        item = self._tool_items[tool_id]
        self.tool_list.setCurrentItem(item)
        self._update_centre()

    def _sidebar_clicked(self, item: QTreeWidgetItem) -> None:
        tool_id = item.data(0, Qt.ItemDataRole.UserRole)
        if tool_id:
            self.select_tool(tool_id)

    def _home_tool(self, tool_id: str) -> None:
        if TOOLS_BY_ID[tool_id].panel.needs_document and not self.session.is_open:
            self.choose_and_open()  # if they cancel, the panel offers "Open PDF…" itself
        self.select_tool(tool_id)

    def toggle_organiser(self) -> None:
        if not self.session.is_open:
            return
        self._organiser_mode = not self._organiser_mode
        self._showing_home = False
        if self._organiser_mode:
            rows = [self.viewer.current_page]
            self.organiser.select_rows(rows)
        self._update_centre()

    def toggle_thumbnails(self) -> None:
        self.strip.setVisible(self.act_thumbs.isChecked())
        self.settings.set_value("view/thumbnails", self.act_thumbs.isChecked())

    def _organiser_open_page(self, index) -> None:
        self._organiser_mode = False
        self._update_centre()
        self.viewer.goto_page(index.row())

    def _update_centre(self) -> None:
        has_doc = self.session.is_open
        if self._showing_home or not has_doc:
            self.centre.setCurrentWidget(self.home)
        elif self._organiser_mode:
            self.centre.setCurrentWidget(self._organiser_page)
            self.organiser.setFocus()
        else:
            self.centre.setCurrentWidget(self._viewer_page)
            self.viewer.setFocus()
        self.options.setVisible(self._tool is not None)
        self.act_organiser.setChecked(self._organiser_mode and has_doc)
        self._update_actions()

    def _update_actions(self) -> None:
        has_doc = self.session.is_open
        busy = self.runner.busy
        editing = has_doc and not self._showing_home
        for action in (self.act_save_as, self.act_close, self.act_find, self.act_find_next,
                       self.act_find_prev, self.act_zoom_in, self.act_zoom_out,
                       self.act_fit_width, self.act_fit_page, self.act_organiser,
                       self.act_prev_page, self.act_next_page):
            action.setEnabled(has_doc)
        for action in (self.act_rotate_left, self.act_rotate_right, self.act_delete_pages,
                       self.act_duplicate, self.act_insert_blank, self.act_extract):
            action.setEnabled(editing and not busy)
        self.act_save.setEnabled(self.session.dirty and not busy)
        self.act_undo.setEnabled(has_doc and self.session.pages.can_undo)
        self.act_redo.setEnabled(has_doc and self.session.pages.can_redo)

    def _update_everything(self) -> None:
        self._update_title()
        self.home.set_recent(self.settings.recent_files)
        if not self.session.is_open:
            self.page_label.setText("")
            self._close_search()
        self._update_centre()

    def _update_title(self) -> None:
        if self.session.path:
            mark = "• " if self.session.dirty else ""
            self.setWindowTitle(f"{mark}{self.session.path.name} — {DISPLAY_NAME}")
            metrics = self.doc_title.fontMetrics()
            self.doc_title.setText(metrics.elidedText(
                f"{mark}{self.session.path.name}", Qt.TextElideMode.ElideMiddle, 270))
            self.doc_title.setToolTip(str(self.session.path))
            pages = len(self.session.pages)
            self.doc_meta.setText(f"{pages} page{'s' if pages != 1 else ''}")
        else:
            self.setWindowTitle(DISPLAY_NAME)
            self.doc_title.setText("")
            self.doc_meta.setText("")

    # =========================================================================================
    # Document events

    def _on_opened(self) -> None:
        path = self.session.path
        assert path is not None
        self.settings.add_recent(path)
        self._showing_home = False
        pages = len(self.session.pages)
        self.page_spin.setMaximum(pages)
        self.page_total.setText(f" / {pages} ")
        note = " (repaired automatically)" if self.session.repaired else ""
        self.statusBar().showMessage(f"Opened {path.name} — {pages} pages{note}", 6000)
        self._update_everything()
        if self.search_bar.isVisible():
            self._start_search()

    def _on_plan_changed(self) -> None:
        pages = len(self.session.pages)
        self.page_spin.setMaximum(max(pages, 1))
        self.page_total.setText(f" / {pages} ")
        self._update_title()
        self._update_actions()
        if self.search_bar.isVisible():
            self._start_search()

    def _on_current_page(self, index: int) -> None:
        if not self.session.is_open:
            return
        self.page_spin.blockSignals(True)
        self.page_spin.setValue(index + 1)
        self.page_spin.blockSignals(False)
        self.strip.set_current_page(index)
        self._update_page_label()

    def _on_zoom_changed(self, zoom: float) -> None:
        mode = self.viewer.zoom_mode
        if mode is ZoomMode.CUSTOM:
            self.zoom_combo.setEditText(f"{zoom * 100:.0f}%")
        else:
            self.zoom_combo.setCurrentIndex(self.zoom_combo.findData(mode))
        self._update_page_label()

    def _update_page_label(self) -> None:
        if self.session.is_open:
            self.page_label.setText(f"Page {self.viewer.current_page + 1} of "
                                    f"{len(self.session.pages)}   ·   "
                                    f"{self.viewer.zoom * 100:.0f}%")

    def _zoom_combo_chosen(self, index: int) -> None:
        data = self.zoom_combo.itemData(index)
        if isinstance(data, ZoomMode):
            self.viewer.set_zoom_mode(data)
        elif data:
            self.viewer.set_zoom(float(data))

    def _zoom_typed(self) -> None:
        text = self.zoom_combo.currentText().strip().rstrip("%")
        try:
            self.viewer.set_zoom(float(text) / 100)
        except ValueError:
            self._on_zoom_changed(self.viewer.zoom)

    def viewer_zoom_in(self) -> None:
        self.viewer.zoom_in()

    def viewer_zoom_out(self) -> None:
        self.viewer.zoom_out()

    # =========================================================================================
    # Page edits (organiser grid or the viewer's current page)

    def _target_rows(self) -> list[int]:
        if not self.session.is_open:
            return []
        if self._organiser_mode:
            return self.organiser.selected_rows()
        return [self.viewer.current_page]

    def _need_selection(self, rows: list[int]) -> bool:
        if not rows:
            self.statusBar().showMessage("Select one or more pages first.", 4000)
            return False
        return True

    def rotate(self, angle: int) -> None:
        rows = self._target_rows()
        if self._need_selection(rows):
            self.session.edit(lambda pages: pages.rotate(rows, angle % 360))
            self._reselect(rows)

    def delete_pages(self) -> None:
        rows = self._target_rows()
        if not self._need_selection(rows):
            return
        if len(rows) >= len(self.session.pages):
            self.statusBar().showMessage("You can't delete every page.", 4000)
            return
        self.session.edit(lambda pages: pages.delete(rows))
        self.statusBar().showMessage(
            f"Deleted {len(rows)} page{'s' if len(rows) > 1 else ''} — Ctrl+Z to undo.", 5000)
        self._reselect([min(rows[0], len(self.session.pages) - 1)])

    def duplicate_pages(self) -> None:
        rows = self._target_rows()
        if self._need_selection(rows):
            self.session.edit(lambda pages: pages.duplicate(rows))
            self._reselect([r + i + 1 for i, r in enumerate(rows)])

    def insert_blank(self) -> None:
        rows = self._target_rows()
        at = (rows[-1] + 1) if rows else len(self.session.pages)
        self.session.edit(lambda pages: pages.insert_blank(at))
        self._reselect([at])

    def _reselect(self, rows: list[int]) -> None:
        if self._organiser_mode:
            self.organiser.select_rows(rows)

    def extract_pages(self) -> None:
        rows = self._target_rows()
        if not self._need_selection(rows) or self.session.path is None:
            return
        default = self.settings.output_for(self.session.path, "extract")
        target, _ = QFileDialog.getSaveFileName(self, "Save selected pages as", str(default),
                                                PDF_FILTER)
        if not target:
            return
        plan = [self.session.pages[r] for r in rows]
        self._run_plan("Extracting pages", plan, Path(target), reopen=False)

    def _organise_action(self, action: str) -> None:
        handlers = {
            "rotate_left": lambda: self.rotate(-90), "rotate_right": lambda: self.rotate(90),
            "duplicate": self.duplicate_pages, "insert_blank": self.insert_blank,
            "delete": self.delete_pages, "extract": self.extract_pages,
            "undo": self.session.undo, "redo": self.session.redo,
            "save": self.save, "save_as": lambda: self.save(save_as=True),
        }
        handlers[action]()

    # =========================================================================================
    # Saving

    def save(self, save_as: bool = False) -> bool:
        session = self.session
        if session.path is None:
            return False
        if not save_as and not session.dirty:
            self.statusBar().showMessage("No changes to save.", 3000)
            return True
        target = self._save_target(save_as)
        if target is None:
            return False
        return self._run_plan("Saving", session.plan, target, reopen=True)

    def _run_plan(self, title: str, plan: list[PageRef], target: Path, reopen: bool) -> bool:
        session = self.session
        assert session.path is not None
        password = session.password
        keep_page = self.viewer.current_page

        def run(inputs: list[Path], output: Path, _opts: object, progress: ProgressFn,
                cancel: Event) -> Result:
            return organise.apply_plan(inputs, output, plan, password, progress, cancel)

        def done(result: Result) -> None:
            panel = self.panels["organise"]
            panel.result.show_result(result)
            if reopen:
                session.pages.mark_saved()  # so reopening doesn't ask to discard
                if self.open_file(target):
                    self.viewer.goto_page(min(keep_page, len(session.pages) - 1))
                if password:
                    self.statusBar().showMessage(
                        f"Saved to {target.name}. Note: the saved file has no password — "
                        "use Protect to add one.", 8000)

        def failed(message: str) -> None:
            if message != "Cancelled.":
                show_error(self, message)

        self.run_job(JobSpec(title, run, [session.path], target, None, on_done=done,
                             on_error=failed))
        return True

    def _save_target(self, save_as: bool) -> Path | None:
        path = self.session.path
        assert path is not None
        if save_as:
            default = self.settings.output_for(path, "edited")
            chosen, _ = QFileDialog.getSaveFileName(self, "Save as", str(default), PDF_FILTER)
            return Path(chosen) if chosen else None
        if self.settings.save_overwrites_original:
            return path
        return self.settings.output_for(path, "edited")

    def _confirm_discard(self) -> bool:
        """Before the document goes away: save (synchronously), discard, or cancel."""
        if not self.session.dirty:
            return True
        name = self.session.path.name if self.session.path else "this document"
        answer = QMessageBox.question(
            self, "Unsaved changes", f"Save your page edits to {name} first?",
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Save)
        if answer == QMessageBox.StandardButton.Cancel:
            return False
        if answer == QMessageBox.StandardButton.Save:
            target = self._save_target(save_as=False)
            assert self.session.path is not None and target is not None
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                result = organise.apply_plan([self.session.path], target, self.session.plan,
                                             self.session.password)
            except PdfSoulError as exc:
                QApplication.restoreOverrideCursor()
                show_error(self, str(exc))
                return False
            QApplication.restoreOverrideCursor()
            self.statusBar().showMessage(f"{result.message} → {target.name}", 6000)
        self.session.pages.mark_saved()
        return True

    def close_document(self) -> None:
        if self._confirm_discard():
            self.session.close()
            self._showing_home = True
            self._update_centre()

    # =========================================================================================
    # Search

    def _reset_search_state(self) -> None:
        self._search_term = ""
        self._search_case = False
        self._search_next_page = 0
        self._search_hits: dict[int, list] = {}
        self._search_list: list[tuple[int, int]] = []
        self._search_cursor = -1

    def show_search(self) -> None:
        if not self.session.is_open:
            return
        if self._organiser_mode:
            self._organiser_mode = False
            self._update_centre()
        self.search_bar.show()
        self.search_edit.setFocus()
        self.search_edit.selectAll()

    def _close_search(self) -> None:
        self._search_timer.stop()
        self.search_bar.hide()
        self.viewer.clear_matches()
        self._reset_search_state()
        if self.session.is_open:
            self.viewer.setFocus()

    def _start_search(self) -> None:
        self._search_timer.stop()
        self._reset_search_state()
        self.viewer.clear_matches()
        self._search_term = self.search_edit.text().strip()
        self._search_case = self.search_case.isChecked()
        if not self._search_term or not self.session.is_open:
            self.search_status.setText("")
            return
        self.search_status.setText("Searching…")
        self._search_timer.start()

    def _search_step(self) -> None:
        if not self.session.is_open:
            return
        start = time.perf_counter()
        total = len(self.session.pages)
        while self._search_next_page < total and time.perf_counter() - start < 0.04:
            page = self._search_next_page
            hits = self.session.search(page, self._search_term, self._search_case)
            if hits:
                self._search_hits[page] = hits
                self._search_list.extend((page, i) for i in range(len(hits)))
            self._search_next_page += 1
        self.viewer.set_matches(self._search_hits)
        finished = self._search_next_page >= total
        if self._search_cursor == -1 and self._search_list:
            here = self.viewer.current_page
            first = next((n for n, (p, _) in enumerate(self._search_list) if p >= here), None)
            if first is not None or finished:
                self._search_cursor = first or 0
                self.viewer.show_match(*self._search_list[self._search_cursor])
        self._update_search_status(finished)
        if not finished:
            self._search_timer.start()

    def _update_search_status(self, finished: bool = True) -> None:
        count = len(self._search_list)
        if not finished:
            self.search_status.setText(f"Searching… {count} found")
        elif count == 0:
            self.search_status.setText("No matches")
        else:
            self.search_status.setText(f"{self._search_cursor + 1} of {count}")

    def _search_enter(self) -> None:
        if self.search_edit.text().strip() != self._search_term:
            self._start_search()
            return
        backwards = QApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier
        self._step_match(-1 if backwards else 1)

    def _step_match(self, delta: int) -> None:
        if not self._search_list:
            if self.search_bar.isHidden():
                self.show_search()
            return
        self._search_cursor = (self._search_cursor + delta) % len(self._search_list)
        self.viewer.show_match(*self._search_list[self._search_cursor])
        self._update_search_status(self._search_next_page >= len(self.session.pages))

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape and self.search_bar.isVisible():
            self._close_search()
            return
        super().keyPressEvent(event)

    # =========================================================================================
    # Jobs

    def _job_started(self, title: str) -> None:
        self.job_label.setText(f"{title}…")
        self.progress.setValue(0)
        for widget in (self.progress, self.cancel_button, self.job_label):
            widget.show()
        self._update_actions()

    def _job_finished(self, result: Result) -> None:
        self._job_ended(result.message)

    def _job_failed(self, message: str, details: str) -> None:
        self._job_ended(message)
        if message.startswith("Something went wrong"):
            show_error(self, message, details)

    def _job_ended(self, message: str) -> None:
        for widget in (self.progress, self.cancel_button, self.job_label):
            widget.hide()
        self.statusBar().showMessage(message, 8000)
        self._update_actions()

    # =========================================================================================
    # Files: drag and drop, recent, settings

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        paths = [Path(u.toLocalFile()) for u in event.mimeData().urls() if u.isLocalFile()]
        if paths:
            event.acceptProposedAction()
            QTimer.singleShot(0, lambda: self.handle_dropped(paths))

    def handle_dropped(self, paths: list[Path]) -> None:
        def having(extensions: set[str]) -> list[Path]:
            return [p for p in paths if p.suffix.lower() in extensions]

        pdfs = having({".pdf"})
        images = having(IMAGE_EXTENSIONS)
        office = having(to_pdf.OFFICE_EXTENSIONS)
        documents = having(to_pdf.WEB_EXTENSIONS | to_pdf.EBOOK_EXTENSIONS)
        folders = [p for p in paths if p.is_dir()]
        convertible = office or documents
        if len(pdfs) == 1 and not images and not folders and not convertible:
            self.open_file(pdfs[0])
        elif pdfs or (folders and not images and not convertible):
            self.select_tool("merge")
            merge = self.panels["merge"]
            assert isinstance(merge, MergePanel)
            merge.add_files(pdfs + folders)
        elif office:
            self._add_to_converter("office_to_pdf", office)
        elif documents:
            self._add_to_converter("docs_to_pdf", documents + images)
        elif images:
            self.select_tool("images_to_pdf")
            panel = self.panels["images_to_pdf"]
            assert isinstance(panel, ImagesToPdfPanel)
            panel.add_files(images)
        else:
            self.statusBar().showMessage(
                f"PDFSoul can't open that. It works with PDFs and converts "
                f"{to_pdf.supported_description()}.", 6000)

    def _add_to_converter(self, tool_id: str, paths: list[Path]) -> None:
        self.select_tool(tool_id)
        panel = self.panels[tool_id]
        assert isinstance(panel, ToPdfPanel)
        panel.add_files(paths)

    def _open_recent(self, path: Path) -> None:
        if not path.exists():
            self.settings.remove_recent(path)
            self.home.set_recent(self.settings.recent_files)
            self.statusBar().showMessage(f"{path.name} no longer exists.", 4000)
            return
        self.open_file(path)

    def _fill_recent_menu(self) -> None:
        self.recent_menu.clear()
        recent = self.settings.recent_files
        for path in recent:
            action = self.recent_menu.addAction(path.name)
            action.setToolTip(str(path))
            action.triggered.connect(lambda _=False, p=path: self._open_recent(p))
        if recent:
            self.recent_menu.addSeparator()
            self.recent_menu.addAction("Clear list", self._clear_recent)
        else:
            self.recent_menu.addAction("No recent files").setEnabled(False)

    def _clear_recent(self) -> None:
        self.settings.clear_recent()
        self.home.set_recent([])

    def open_settings(self) -> None:
        if SettingsDialog(self.settings, self).exec():
            for panel in self.panels.values():
                if panel.isVisible():
                    panel.refresh()
            self.statusBar().showMessage("Settings saved.", 3000)

    # =========================================================================================
    # Window state

    def _restore_state(self) -> None:
        geometry = self.settings.value("window/geometry")
        if isinstance(geometry, QByteArray):
            self.restoreGeometry(geometry)
        splitter = self.settings.value("window/splitter")
        if isinstance(splitter, QByteArray):
            self.splitter.restoreState(splitter)
        thumbs = self.settings.value("view/thumbnails", True)
        show = thumbs not in (False, "false", 0, "0")
        self.act_thumbs.setChecked(show)
        self.strip.setVisible(show)
        self.select_tool(HOME)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.thumb_model.set_device_pixel_ratio(self.devicePixelRatioF())

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.runner.busy:
            answer = QMessageBox.question(self, "Job running",
                                          "A job is still running. Cancel it and quit?")
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self.runner.cancel()
            self.runner.wait()
        if not self._confirm_discard():
            event.ignore()
            return
        self.settings.set_value("window/geometry", self.saveGeometry())
        self.settings.set_value("window/splitter", self.splitter.saveState())
        self.session.close()
        event.accept()
