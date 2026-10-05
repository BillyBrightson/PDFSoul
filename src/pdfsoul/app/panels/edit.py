"""Watermark and page numbers, each with a live preview of the current page."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QImage, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QSlider,
    QSpinBox,
    QWidget,
)

from pdfsoul.app.jobs import JobSpec
from pdfsoul.app.panels.base import ToolPanel
from pdfsoul.app.widgets import ElidedLabel, OutputPicker, PageRangeEdit
from pdfsoul.core import edit
from pdfsoul.core.edit import NumberFormat, Position
from pdfsoul.core.types import PdfSoulError, Result

log = logging.getLogger(__name__)

POSITION_LABELS = {
    Position.TOP_LEFT: "Top left", Position.TOP_CENTER: "Top centre",
    Position.TOP_RIGHT: "Top right", Position.MIDDLE_LEFT: "Middle left",
    Position.CENTER: "Centre", Position.MIDDLE_RIGHT: "Middle right",
    Position.BOTTOM_LEFT: "Bottom left", Position.BOTTOM_CENTER: "Bottom centre",
    Position.BOTTOM_RIGHT: "Bottom right",
}


def position_combo(default: Position) -> QComboBox:
    combo = QComboBox()
    for position, label in POSITION_LABELS.items():
        combo.addItem(label, position)
    combo.setCurrentIndex(combo.findData(default))
    return combo


class ColorButton(QPushButton):
    def __init__(self, color: str) -> None:
        super().__init__()
        self.color = color
        self.setFixedWidth(64)
        self.clicked.connect(self._pick)
        self._paint()

    def _pick(self) -> None:
        chosen = QColorDialog.getColor(QColor(self.color), self, "Colour")
        if chosen.isValid():
            self.color = chosen.name()
            self._paint()
            self.window().setFocus()

    def _paint(self) -> None:
        self.setStyleSheet(f"background: {self.color}; border: 1px solid #888; "
                           "border-radius: 4px; min-height: 22px;")


class StampPanel(ToolPanel):
    """Shared preview machinery: re-render the current page shortly after any change."""

    def setup_preview(self) -> None:
        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumHeight(220)
        self.form.addRow(self.preview)
        self._timer = QTimer(self, singleShot=True, interval=250)
        self._timer.timeout.connect(self._render_preview)

    def watch(self, *widgets: QWidget) -> None:
        for widget in widgets:
            for signal in ("textChanged", "valueChanged", "currentIndexChanged", "toggled",
                           "clicked"):
                if hasattr(widget, signal):
                    getattr(widget, signal).connect(lambda *_: self.schedule_preview())
                    break

    def schedule_preview(self) -> None:
        if self.isVisible():
            self._timer.start()

    def refresh(self) -> None:
        super().refresh()
        self.schedule_preview()

    def document_changed(self) -> None:
        self.schedule_preview()

    def options(self) -> edit.WatermarkOptions | edit.PageNumberOptions:
        raise NotImplementedError

    def _render_preview(self) -> None:
        session = self.ctx.session
        if not session.is_open or session.path is None:
            self.preview.clear()
            return
        ref = session.pages[min(self.ctx.current_page(), len(session.pages) - 1)]
        page = ref.source if ref.source is not None else 0
        try:
            png = edit.preview(session.path, session.password, page, 60, self.options())
        except PdfSoulError as exc:
            self.preview.setText(str(exc))
            return
        except Exception:  # never let a preview problem break the panel
            log.exception("Preview failed")
            self.preview.setText("Preview unavailable")
            return
        image = QImage.fromData(png)
        dpr = self.devicePixelRatioF()
        pixmap = QPixmap.fromImage(image).scaled(
            int(260 * dpr), int(260 * dpr), Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation)
        pixmap.setDevicePixelRatio(dpr)
        self.preview.setPixmap(pixmap)


class WatermarkPanel(StampPanel):
    tool_id = "watermark"
    title = "Watermark"
    blurb = "Stamp text or an image across your pages."
    primary_label = "Add watermark"

    def build(self) -> None:
        self.kind = QButtonGroup(self)
        self.text_mode, self.image_mode = QRadioButton("Text"), QRadioButton("Image")
        self.text_mode.setChecked(True)
        row = QHBoxLayout()
        for n, button in enumerate((self.text_mode, self.image_mode)):
            self.kind.addButton(button, n)
            row.addWidget(button)
        row.addStretch(1)
        holder = QWidget()
        holder.setLayout(row)
        self.form.addRow("Type", holder)

        self.text = QLineEdit("CONFIDENTIAL")
        self.form.addRow("Text", self.text)
        self.font_size = QSpinBox()
        self.font_size.setRange(6, 300)
        self.font_size.setValue(72)
        self.color = ColorButton("#808080")
        style = QHBoxLayout()
        style.addWidget(self.font_size)
        style.addWidget(self.color)
        style.addStretch(1)
        self.style_row = QWidget()
        self.style_row.setLayout(style)
        self.form.addRow("Size, colour", self.style_row)

        self.image_path = ElidedLabel("No image chosen")
        choose = QPushButton("Choose…")
        choose.clicked.connect(self._choose_image)
        image_row = QHBoxLayout()
        image_row.addWidget(self.image_path, 1)
        image_row.addWidget(choose)
        self.image_row = QWidget()
        self.image_row.setLayout(image_row)
        self.form.addRow("Image", self.image_row)
        self._image: Path | None = None
        self.scale = QSpinBox()
        self.scale.setRange(5, 100)
        self.scale.setValue(50)
        self.scale.setSuffix(" % of page width")
        self.form.addRow("Image size", self.scale)

        self.opacity = QSlider(Qt.Orientation.Horizontal)
        self.opacity.setRange(5, 100)
        self.opacity.setValue(45)
        self.form.addRow("Opacity", self.opacity)
        self.angle = QSpinBox()
        self.angle.setRange(-180, 180)
        self.angle.setValue(45)
        self.angle.setSuffix("°")
        self.form.addRow("Angle", self.angle)
        self.position = position_combo(Position.CENTER)
        self.form.addRow("Position", self.position)
        self.behind = QCheckBox("Put it behind the page content")
        self.form.addRow(self.behind)
        self.pages = PageRangeEdit()
        self.form.addRow("Pages", self.pages)
        self.setup_preview()
        self.output = OutputPicker("file", self._default_output)
        self.form.addRow("Save to", self.output)

        self.kind.idToggled.connect(lambda *_: self._sync())
        self.watch(self.text, self.font_size, self.opacity, self.angle, self.position,
                   self.behind, self.scale, self.text_mode)
        self.color.clicked.connect(lambda: QTimer.singleShot(0, self.schedule_preview))
        self._sync()

    def _sync(self) -> None:
        image = self.image_mode.isChecked()
        self.form.setRowVisible(self.text, not image)
        self.form.setRowVisible(self.style_row, not image)
        self.form.setRowVisible(self.image_row, image)
        self.form.setRowVisible(self.scale, image)
        self.schedule_preview()

    def _choose_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Watermark image", "",
                                              "Images (*.png *.jpg *.jpeg *.bmp *.webp)")
        if path:
            self._image = Path(path)
            self.image_path.set_full_text(str(self._image))
            self.schedule_preview()

    def options(self) -> edit.WatermarkOptions:
        image = self._image if self.image_mode.isChecked() else None
        if self.image_mode.isChecked() and image is None:
            raise PdfSoulError("Choose an image.")
        return edit.WatermarkOptions(
            text=self.text.text(), image=image, font_size=self.font_size.value(),
            color=self.color.color, opacity=self.opacity.value() / 100,
            angle=self.angle.value(), position=self.position.currentData(),
            image_scale=self.scale.value() / 100, behind=self.behind.isChecked(),
            pages=self.pages.text(), password=self.password)

    def _default_output(self) -> Path | None:
        path = self.ctx.session.path
        return self.ctx.settings.output_for(path, "watermarked") if path else None

    def document_changed(self) -> None:
        self.output.reset()
        super().document_changed()

    def make_job(self) -> JobSpec:
        output = self.output.path()
        assert output is not None
        return JobSpec("Adding watermark", edit.watermark, [self.source], output, self.options())

    def on_result(self, result: Result) -> None:
        self.output.reset()


class PageNumbersPanel(StampPanel):
    tool_id = "page_numbers"
    title = "Page numbers"
    blurb = "Number your pages. Use {n} for the number and {total} for the page count."
    primary_label = "Add page numbers"

    def build(self) -> None:
        self.fmt = QComboBox()
        self.fmt.setEditable(True)
        for fmt in NumberFormat:
            self.fmt.addItem(fmt.value)
        self.form.addRow("Format", self.fmt)
        self.position = position_combo(Position.BOTTOM_CENTER)
        self.form.addRow("Position", self.position)
        self.start = QSpinBox()
        self.start.setRange(0, 100_000)
        self.start.setValue(1)
        self.form.addRow("Start at", self.start)
        self.font_size = QDoubleSpinBox()
        self.font_size.setRange(5, 72)
        self.font_size.setValue(11)
        self.color = ColorButton("#000000")
        style = QHBoxLayout()
        style.addWidget(self.font_size)
        style.addWidget(self.color)
        style.addStretch(1)
        holder = QWidget()
        holder.setLayout(style)
        self.form.addRow("Size, colour", holder)
        self.pages = PageRangeEdit()
        self.form.addRow("Pages", self.pages)
        self.setup_preview()
        self.output = OutputPicker("file", self._default_output)
        self.form.addRow("Save to", self.output)
        self.watch(self.position, self.start, self.font_size, self.pages)
        self.fmt.currentTextChanged.connect(lambda _: self.schedule_preview())
        self.color.clicked.connect(lambda: QTimer.singleShot(0, self.schedule_preview))

    def options(self) -> edit.PageNumberOptions:
        return edit.PageNumberOptions(
            fmt=self.fmt.currentText() or "{n}", position=self.position.currentData(),
            start=self.start.value(), font_size=self.font_size.value(),
            color=self.color.color, pages=self.pages.text(), password=self.password)

    def _default_output(self) -> Path | None:
        path = self.ctx.session.path
        return self.ctx.settings.output_for(path, "numbered") if path else None

    def document_changed(self) -> None:
        self.output.reset()
        super().document_changed()

    def make_job(self) -> JobSpec:
        output = self.output.path()
        assert output is not None
        return JobSpec("Adding page numbers", edit.page_numbers, [self.source], output,
                       self.options())

    def on_result(self, result: Result) -> None:
        self.output.reset()
