"""Base class for the right-hand options panel of every tool."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from pdfsoul.app.jobs import JobRunner, JobSpec
from pdfsoul.app.session import DocumentSession
from pdfsoul.app.settings import Settings
from pdfsoul.app.widgets import ResultCard, muted
from pdfsoul.core.types import PdfSoulError, Result


class AppContext(Protocol):
    """What panels may use from the main window."""

    session: DocumentSession
    settings: Settings
    runner: JobRunner

    def run_job(self, spec: JobSpec) -> None: ...
    def open_file(self, path: Path) -> bool: ...
    def choose_and_open(self) -> bool: ...
    def password_for(self, path: Path) -> str | None: ...
    def current_page(self) -> int: ...


class ToolPanel(QWidget):
    tool_id = ""
    title = ""
    blurb = ""
    primary_label = "Run"
    needs_document = True

    def __init__(self, ctx: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        self.body_layout = QVBoxLayout(body)
        self.body_layout.setContentsMargins(20, 20, 20, 12)
        self.body_layout.setSpacing(10)
        header = QHBoxLayout()
        header.setSpacing(12)
        self._glyph = QLabel()
        self._glyph.setFixedSize(40, 40)
        self._glyph.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._glyph.hide()
        heading = QVBoxLayout()
        heading.setSpacing(1)
        self._group = QLabel("")
        self._group.setObjectName("PanelGroup")
        self._group.hide()
        title = QLabel(self.title)
        title.setObjectName("PanelTitle")
        title.setWordWrap(True)
        heading.addWidget(self._group)
        heading.addWidget(title)
        header.addWidget(self._glyph, alignment=Qt.AlignmentFlag.AlignTop)
        header.addLayout(heading, 1)
        self.body_layout.addLayout(header)
        if self.blurb:
            self.body_layout.addWidget(muted(self.blurb))

        self._need_doc = QFrame(objectName="EmptyState")
        need = QVBoxLayout(self._need_doc)
        need.setContentsMargins(16, 22, 16, 22)
        need.setSpacing(10)
        need.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._need_icon = QLabel()
        self._need_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        need.addWidget(self._need_icon)
        need_text = muted("Open a PDF to use this tool.")
        need_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        need.addWidget(need_text)
        open_button = QPushButton("Open PDF…")
        open_button.clicked.connect(ctx.choose_and_open)
        need.addWidget(open_button, alignment=Qt.AlignmentFlag.AlignCenter)
        self.body_layout.addSpacing(4)
        self.body_layout.addWidget(self._need_doc)

        self.form_host = QWidget()
        self.form = QFormLayout(self.form_host)
        self.form.setContentsMargins(0, 6, 0, 0)
        self.form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        self.form.setVerticalSpacing(8)
        self.body_layout.addWidget(self.form_host)
        self._dirty_note = muted("Your unsaved page edits aren't included. Save first (Ctrl+S).")
        self._dirty_note.hide()
        self.body_layout.addWidget(self._dirty_note)
        self.build()
        self.body_layout.addStretch(1)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        footer = QVBoxLayout()
        footer.setContentsMargins(20, 8, 20, 20)
        footer.setSpacing(10)
        self.result = ResultCard()
        self.result.openRequested.connect(self._open_result)
        self.primary = QPushButton(self.primary_label)
        self.primary.setObjectName("Primary")
        self.primary.clicked.connect(self._run)
        footer.addWidget(self.result)
        footer.addWidget(self.primary)
        outer.addLayout(footer)

        ctx.session.opened.connect(self._document_changed)
        ctx.session.closed.connect(self._document_changed)
        ctx.session.planChanged.connect(self._update_state)
        ctx.runner.started.connect(lambda _: self._update_state())
        ctx.runner.idle.connect(self._update_state)
        self._update_state()

    def decorate(self, glyph: QPixmap, group: str, empty_icon: QPixmap) -> None:
        """Show the tool's icon and group in the header (set by the main window)."""
        self._glyph.setPixmap(glyph)
        self._glyph.show()
        self._group.setText(group.upper())
        self._group.show()
        self._need_icon.setPixmap(empty_icon)

    # -- for subclasses ------------------------------------------------------------------------

    def build(self) -> None:
        """Add the tool's options to ``self.form``."""

    def document_changed(self) -> None:
        """A document was opened or closed: reset defaults that depend on it."""

    def make_job(self) -> JobSpec:
        """Validate the options and describe the job. Raise PdfSoulError to show a problem."""
        raise NotImplementedError

    def on_result(self, result: Result) -> None:
        """Called after a successful run (the result card is already shown)."""

    def can_run(self) -> bool:
        return True

    # -- helpers -------------------------------------------------------------------------------

    @property
    def source(self) -> Path:
        if self.ctx.session.path is None:
            raise PdfSoulError("Open a PDF first.")
        return self.ctx.session.path

    @property
    def password(self) -> str | None:
        return self.ctx.session.password

    def refresh(self) -> None:
        """Called when the panel is shown."""
        self._update_state()

    # -- internals -----------------------------------------------------------------------------

    def _document_changed(self) -> None:
        self.result.hide()
        self.document_changed()
        self._update_state()

    def _update_state(self) -> None:
        has_doc = self.ctx.session.is_open
        missing = self.needs_document and not has_doc
        self._need_doc.setVisible(missing)
        self.form_host.setVisible(not missing)
        self._dirty_note.setVisible(self.needs_document and self.ctx.session.dirty
                                    and self.tool_id != "organise")
        self.primary.setEnabled(not missing and not self.ctx.runner.busy and self.can_run())

    def _run(self) -> None:
        try:
            spec = self.make_job()
        except PdfSoulError as exc:
            self.result.show_error(str(exc))
            return
        user_done = spec.on_done

        def done(result: Result) -> None:
            self.result.show_result(result)
            if user_done:
                user_done(result)
            self.on_result(result)

        spec.on_done = done
        spec.on_error = self.result.show_error
        self.result.hide()
        self.ctx.run_job(spec)

    def _open_result(self, path: Path) -> None:
        if path.suffix.lower() == ".pdf":
            self.ctx.open_file(path)
        else:
            from pdfsoul.app.widgets import open_with_system

            open_with_system(path)
