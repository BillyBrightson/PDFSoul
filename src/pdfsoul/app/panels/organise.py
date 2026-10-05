"""Organise pages, Merge, Split, Compress."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QGridLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from pdfsoul.app.jobs import JobSpec
from pdfsoul.app.panels.base import ToolPanel
from pdfsoul.app.widgets import PDF_FILTER, FileListWidget, OutputPicker, muted
from pdfsoul.core import engines, optimise, organise
from pdfsoul.core.document import is_encrypted
from pdfsoul.core.optimise import PRESET_LABELS, CompressPreset, human_size
from pdfsoul.core.types import PdfSoulError, Result


class OrganisePanel(ToolPanel):
    tool_id = "organise"
    title = "Organise pages"
    blurb = ("Drag thumbnails to reorder. Select several with Ctrl or Shift. Changes are "
             "previewed here and only written when you save.")
    primary_label = "Save  (Ctrl+S)"

    # The main window owns the grid selection and saving, so buttons just ask it to act.
    actionRequested = Signal(str)

    def build(self) -> None:
        from pdfsoul.app import icons
        from pdfsoul.app.theme import tokens

        grid = QGridLayout()
        grid.setSpacing(6)
        actions = [
            ("Rotate left", "rotate_left", "rotate-ccw"),
            ("Rotate right", "rotate_right", "rotate-cw"),
            ("Duplicate", "duplicate", "copy"), ("Blank page", "insert_blank", "file-plus"),
            ("Delete", "delete", "trash"), ("Extract…", "extract", "file-out"),
            ("Undo", "undo", "undo"), ("Redo", "redo", "redo"),
        ]
        self.buttons: dict[str, QPushButton] = {}
        t = tokens()
        for n, (label, name, glyph) in enumerate(actions):
            button = QPushButton(icons.icon(glyph, t.text, disabled=t.muted, size=16), label)
            button.clicked.connect(lambda _=False, a=name: self.actionRequested.emit(a))
            grid.addWidget(button, n // 2, n % 2)
            self.buttons[name] = button
        holder = QWidget()
        holder.setLayout(grid)
        self.form.addRow(holder)
        self.status = muted("")
        self.form.addRow(self.status)
        self.save_as = QPushButton("Save as…  (Ctrl+Shift+S)")
        self.save_as.clicked.connect(lambda: self.actionRequested.emit("save_as"))
        self.form.addRow(self.save_as)
        self.form.addRow(muted("Shortcuts: Del deletes, Ctrl+R rotates, Ctrl+Z / Ctrl+Y undo "
                               "and redo, Ctrl+T switches between viewer and grid."))

    def _update_state(self) -> None:
        super()._update_state()
        session = self.ctx.session
        if session.is_open:
            pages = len(session.pages)
            note = " · unsaved changes" if session.dirty else ""
            self.status.setText(f"{pages} page{'s' if pages != 1 else ''}{note}")
        self.buttons["undo"].setEnabled(session.pages.can_undo)
        self.buttons["redo"].setEnabled(session.pages.can_redo)
        self.primary.setEnabled(session.dirty and not self.ctx.runner.busy)

    def make_job(self) -> JobSpec:
        raise PdfSoulError("unused")  # the main window runs saves

    def _run(self) -> None:
        self.actionRequested.emit("save")


class MergePanel(ToolPanel):
    tool_id = "merge"
    title = "Merge PDFs"
    blurb = "Combine files in the order listed. Each file's bookmarks are kept."
    primary_label = "Merge"
    needs_document = False

    def build(self) -> None:
        self.files = FileListWidget({".pdf"}, PDF_FILTER, ranges=True,
                                    describe=_describe_pdf, on_add=self._unlock_if_needed)
        self.files.changed.connect(self._files_changed)
        self.form.addRow(self.files)
        self.add_open = QPushButton("Add the open document")
        self.add_open.clicked.connect(self._add_open_document)
        self.form.addRow(self.add_open)
        self.bookmarks = QCheckBox("Keep bookmarks")
        self.bookmarks.setChecked(True)
        self.form.addRow(self.bookmarks)
        self.output = OutputPicker("file", self._default_output)
        self.form.addRow("Save to", self.output)

    def _default_output(self) -> Path | None:
        paths = self.files.paths() if hasattr(self, "files") else []
        return self.ctx.settings.output_for(paths[0], "merged") if paths else None

    def _files_changed(self) -> None:
        self.output.refresh()
        self._update_state()

    def _unlock_if_needed(self, path: Path) -> bool:
        if not is_encrypted(path):
            return True
        if self.ctx.session.path == path.resolve() and self.ctx.session.password:
            self.files.passwords[str(path)] = self.ctx.session.password
            return True
        password = self.ctx.password_for(path)
        if password is None:
            return False
        self.files.passwords[str(path)] = password
        return True

    def _add_open_document(self) -> None:
        if self.ctx.session.path:
            self.files.add_paths([self.ctx.session.path])

    def add_files(self, paths: list[Path]) -> None:
        self.files.add_paths(paths)

    def can_run(self) -> bool:
        return hasattr(self, "files") and len(self.files.paths()) >= 2

    def _update_state(self) -> None:
        super()._update_state()
        if hasattr(self, "add_open"):
            self.add_open.setVisible(self.ctx.session.is_open)

    def make_job(self) -> JobSpec:
        paths = self.files.paths()
        if len(paths) < 2:
            raise PdfSoulError("Add at least two PDFs.")
        output = self.output.path()
        assert output is not None
        if any(output.resolve() == p.resolve() for p in paths):
            raise PdfSoulError("Choose an output file that isn't one of the inputs.")
        return JobSpec(f"Merging {len(paths)} files", organise.merge, paths, output,
                       organise.MergeOptions(page_ranges=self.files.page_ranges(),
                                             passwords=dict(self.files.passwords),
                                             bookmarks=self.bookmarks.isChecked()))

    def on_result(self, result: Result) -> None:
        self.output.reset()


def _describe_pdf(path: Path) -> str:
    try:
        from pdfsoul.core.document import open_pdf

        with open_pdf(path, repair=False) as doc:
            pages = f"{doc.page_count} p"
    except PdfSoulError:
        pages = "🔒" if is_encrypted(path) else "?"
    except Exception:
        pages = "?"
    return f"{pages} · {human_size(path.stat().st_size)}"


class SplitPanel(ToolPanel):
    tool_id = "split"
    title = "Split PDF"
    blurb = "Break the open PDF into several files."
    primary_label = "Split"

    def build(self) -> None:
        self.modes = QButtonGroup(self)
        box = QVBoxLayout()
        self.each = QRadioButton("Every page into its own file")
        self.ranges_mode = QRadioButton("By page ranges")
        self.every_mode = QRadioButton("Every N pages")
        self.bookmarks_mode = QRadioButton("At each top-level bookmark")
        for n, button in enumerate((self.each, self.ranges_mode, self.every_mode,
                                    self.bookmarks_mode)):
            self.modes.addButton(button, n)
            box.addWidget(button)
        self.each.setChecked(True)
        holder = QWidget()
        holder.setLayout(box)
        self.form.addRow(holder)
        self.ranges = QLineEdit()
        self.ranges.setPlaceholderText("e.g. 1-3,4-6,7- (one file per range)")
        self.form.addRow("Ranges", self.ranges)
        self.every = QSpinBox()
        self.every.setRange(1, 10_000)
        self.every.setValue(2)
        self.form.addRow("Pages per file", self.every)
        self.output = OutputPicker("folder", self._default_output)
        self.form.addRow("Save into", self.output)
        self.modes.idToggled.connect(lambda *_: self._sync())
        self._sync()

    def _sync(self) -> None:
        self.ranges.setEnabled(self.ranges_mode.isChecked())
        self.every.setEnabled(self.every_mode.isChecked())

    def _default_output(self) -> Path | None:
        path = self.ctx.session.path
        return self.ctx.settings.folder_for(path, "split") if path else None

    def document_changed(self) -> None:
        self.output.reset()

    def make_job(self) -> JobSpec:
        mode = [organise.SplitMode.EACH_PAGE, organise.SplitMode.RANGES,
                organise.SplitMode.EVERY_N, organise.SplitMode.BOOKMARKS][self.modes.checkedId()]
        output = self.output.path()
        assert output is not None
        return JobSpec("Splitting", organise.split, [self.source], output,
                       organise.SplitOptions(mode=mode, ranges=self.ranges.text(),
                                             every=self.every.value(), password=self.password))

    def on_result(self, result: Result) -> None:
        self.output.reset()


class CompressPanel(ToolPanel):
    tool_id = "compress"
    title = "Compress PDF"
    blurb = "Make the file smaller. The original is kept if the result isn't smaller."
    primary_label = "Compress"

    def build(self) -> None:
        self.presets = QButtonGroup(self)
        box = QVBoxLayout()
        for n, preset in enumerate(CompressPreset):
            button = QRadioButton(PRESET_LABELS[preset])
            self.presets.addButton(button, n)
            box.addWidget(button)
        holder = QWidget()
        holder.setLayout(box)
        self.form.addRow(holder)
        self.engine_note = muted("")
        self.form.addRow(self.engine_note)
        self.output = OutputPicker("file", self._default_output)
        self.form.addRow("Save to", self.output)
        self.sizes = QLabel()
        self.form.addRow(self.sizes)

    def refresh(self) -> None:
        preset = self.ctx.settings.compress_preset
        self.presets.button(list(CompressPreset).index(preset)).setChecked(True)
        gs = engines.find("gs")
        self.engine_note.setText("Using Ghostscript for best results." if gs else
                                 "Ghostscript not found — using the built-in engine. "
                                 "Install Ghostscript or set its path in Settings for "
                                 "smaller files.")
        self._show_size()
        super().refresh()

    def _show_size(self) -> None:
        path = self.ctx.session.path
        self.sizes.setText(f"Current size: {human_size(path.stat().st_size)}"
                           if path and path.exists() else "")

    def _default_output(self) -> Path | None:
        path = self.ctx.session.path
        return self.ctx.settings.output_for(path, "compressed") if path else None

    def document_changed(self) -> None:
        self.output.reset()
        self._show_size()

    def make_job(self) -> JobSpec:
        preset = list(CompressPreset)[max(self.presets.checkedId(), 0)]
        output = self.output.path()
        assert output is not None
        return JobSpec("Compressing", optimise.compress, [self.source], output,
                       optimise.CompressOptions(preset=preset, password=self.password))

    def on_result(self, result: Result) -> None:
        before, after = result.details.get("before"), result.details.get("after")
        if before and after:
            self.sizes.setText(f"Before: {human_size(before)}   After: {human_size(after)}")
        self.output.reset()

