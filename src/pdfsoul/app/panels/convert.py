"""Images → PDF, PDF → Images, Extract text and images."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QButtonGroup, QComboBox, QHBoxLayout, QRadioButton, QSpinBox, QWidget

from pdfsoul.app.jobs import JobSpec
from pdfsoul.app.panels.base import ToolPanel
from pdfsoul.app.widgets import FileListWidget, OutputPicker, PageRangeEdit, muted
from pdfsoul.core import convert
from pdfsoul.core.types import PdfSoulError, Result

MM = 72 / 25.4


class ImagesToPdfPanel(ToolPanel):
    tool_id = "images_to_pdf"
    title = "Image to PDF"
    blurb = "One page per image, in the order listed. JPG, PNG, HEIC, TIFF, WebP, BMP."
    primary_label = "Create PDF"
    needs_document = False

    def build(self) -> None:
        exts = sorted(convert.IMAGE_EXTENSIONS)
        file_filter = "Images (" + " ".join(f"*{e}" for e in exts) + ")"
        self.files = FileListWidget(convert.IMAGE_EXTENSIONS, file_filter)
        self.files.changed.connect(self._files_changed)
        self.form.addRow(self.files)
        self.size = QComboBox()
        self.size.addItem("Fit each image", convert.PageSize.FIT)
        self.size.addItem("A4", convert.PageSize.A4)
        self.size.addItem("Letter", convert.PageSize.LETTER)
        self.form.addRow("Page size", self.size)
        self.margin = QSpinBox()
        self.margin.setRange(0, 50)
        self.margin.setSuffix(" mm")
        self.form.addRow("Margin", self.margin)
        self.output = OutputPicker("file", self._default_output)
        self.form.addRow("Save to", self.output)

    def add_files(self, paths: list[Path]) -> None:
        self.files.add_paths(paths)

    def _files_changed(self) -> None:
        self.output.refresh()
        self._update_state()

    def _default_output(self) -> Path | None:
        paths = self.files.paths() if hasattr(self, "files") else []
        return self.ctx.settings.output_for(paths[0], "pdf") if paths else None

    def can_run(self) -> bool:
        return hasattr(self, "files") and bool(self.files.paths())

    def make_job(self) -> JobSpec:
        paths = self.files.paths()
        output = self.output.path()
        if not paths or output is None:
            raise PdfSoulError("Add at least one image.")
        return JobSpec(f"Converting {len(paths)} images", convert.images_to_pdf, paths, output,
                       convert.ImagesToPdfOptions(page_size=self.size.currentData(),
                                                  margin_pt=self.margin.value() * MM))

    def on_result(self, result: Result) -> None:
        self.output.reset()


class ToImagesPanel(ToolPanel):
    tool_id = "to_images"
    title = "PDF to Image"
    blurb = "Save each page as a picture, or as a scalable SVG drawing."
    primary_label = "Export images"

    def build(self) -> None:
        self.fmt = QComboBox()
        self.fmt.addItem("PNG · sharp, lossless", convert.ImageFormat.PNG)
        self.fmt.addItem("JPG · small, for photos", convert.ImageFormat.JPG)
        self.fmt.addItem("WebP · small, for the web", convert.ImageFormat.WEBP)
        self.fmt.addItem("TIFF · for print and archiving", convert.ImageFormat.TIFF)
        self.fmt.addItem("SVG · vector, sharp at any size", convert.ImageFormat.SVG)
        self.fmt.currentIndexChanged.connect(lambda _: self.form.setRowVisible(
            self.dpi, self.fmt.currentData() is not convert.ImageFormat.SVG))
        self.form.addRow("Format", self.fmt)
        self.dpi = QSpinBox()
        self.dpi.setRange(72, 600)
        self.dpi.setSingleStep(50)
        self.dpi.setValue(150)
        self.dpi.setSuffix(" dpi")
        self.form.addRow("Resolution", self.dpi)
        self.form.addRow(muted("150 dpi suits screens; 300 dpi suits print."))
        self.pages = PageRangeEdit()
        self.form.addRow("Pages", self.pages)
        self.output = OutputPicker("folder", self._default_output)
        self.form.addRow("Save into", self.output)

    def _default_output(self) -> Path | None:
        path = self.ctx.session.path
        return self.ctx.settings.folder_for(path, "images") if path else None

    def document_changed(self) -> None:
        self.output.reset()

    def make_job(self) -> JobSpec:
        output = self.output.path()
        assert output is not None
        return JobSpec("Exporting images", convert.pdf_to_images, [self.source], output,
                       convert.PdfToImagesOptions(fmt=self.fmt.currentData(),
                                                  dpi=self.dpi.value(),
                                                  pages=self.pages.text(),
                                                  password=self.password))

    def on_result(self, result: Result) -> None:
        self.output.reset()


class ExtractPanel(ToolPanel):
    tool_id = "extract"
    title = "Extract images"
    blurb = "Save every embedded picture in its original format, or pull out the text."
    primary_label = "Extract"

    def build(self) -> None:
        self.kind = QButtonGroup(self)
        self.text_mode = QRadioButton("Text (.txt)")
        self.image_mode = QRadioButton("Images")
        self.image_mode.setChecked(True)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        for n, button in enumerate((self.image_mode, self.text_mode)):
            self.kind.addButton(button, n)
            row.addWidget(button)
        row.addStretch(1)
        holder = QWidget()
        holder.setLayout(row)
        self.form.addRow("Extract", holder)
        self.pages = PageRangeEdit()
        self.form.addRow("Pages", self.pages)
        self.min_size = QSpinBox()
        self.min_size.setRange(0, 2000)
        self.min_size.setValue(32)
        self.min_size.setSuffix(" px")
        self.form.addRow("Skip images under", self.min_size)
        self.text_output = OutputPicker("file", self._default_text,
                                        file_filter="Text files (*.txt)")
        self.image_output = OutputPicker("folder", self._default_images)
        self.form.addRow("Save to", self.text_output)
        self.form.addRow("Save into", self.image_output)
        self.kind.idToggled.connect(lambda *_: self._sync())
        self._sync()

    def _sync(self) -> None:
        images = self.image_mode.isChecked()
        self.form.setRowVisible(self.min_size, images)
        self.form.setRowVisible(self.image_output, images)
        self.form.setRowVisible(self.text_output, not images)

    def _default_text(self) -> Path | None:
        path = self.ctx.session.path
        return self.ctx.settings.output_for(path, "text", ".txt") if path else None

    def _default_images(self) -> Path | None:
        path = self.ctx.session.path
        return self.ctx.settings.folder_for(path, "extracted") if path else None

    def document_changed(self) -> None:
        self.text_output.reset()
        self.image_output.reset()

    def make_job(self) -> JobSpec:
        if self.image_mode.isChecked():
            output = self.image_output.path()
            assert output is not None
            return JobSpec("Extracting images", convert.extract_images, [self.source], output,
                           convert.ExtractImagesOptions(pages=self.pages.text(),
                                                        min_size_px=self.min_size.value(),
                                                        password=self.password))
        output = self.text_output.path()
        assert output is not None
        return JobSpec("Extracting text", convert.extract_text, [self.source], output,
                       convert.ExtractTextOptions(pages=self.pages.text(),
                                                  password=self.password))

    def on_result(self, result: Result) -> None:
        self.text_output.reset()
        self.image_output.reset()
