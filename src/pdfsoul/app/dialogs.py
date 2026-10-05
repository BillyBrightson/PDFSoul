"""Password prompt, error dialog with "Copy details", settings, and about."""

from __future__ import annotations

import random
from datetime import date
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QGuiApplication, QMouseEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from pdfsoul import AUTHOR, DISPLAY_NAME, __version__
from pdfsoul.app.logging_setup import log_dir
from pdfsoul.app.settings import ENGINE_NAMES, Settings
from pdfsoul.app.widgets import muted, open_with_system
from pdfsoul.core import engines
from pdfsoul.core.optimise import PRESET_LABELS, CompressPreset


def ask_password(parent: QWidget | None, name: str, wrong: bool = False) -> str | None:
    prompt = (f"Wrong password for {name}. Try again:" if wrong
              else f"{name} is password protected. Enter its password:")
    text, ok = QInputDialog.getText(parent, "Password required", prompt,
                                    QLineEdit.EchoMode.Password)
    return text if ok and text else None


class ErrorDialog(QDialog):
    """A short, human message; the technical details one click away (and copyable)."""

    def __init__(self, parent: QWidget | None, message: str, details: str = "") -> None:
        super().__init__(parent)
        self.setWindowTitle(f"{DISPLAY_NAME} — something went wrong")
        self.setMinimumWidth(440)
        layout = QVBoxLayout(self)
        label = QLabel(message)
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(label)
        self._details = QPlainTextEdit(details)
        self._details.setReadOnly(True)
        self._details.setMinimumHeight(160)
        self._details.hide()
        layout.addWidget(self._details)
        buttons = QHBoxLayout()
        if details:
            toggle = QPushButton("Show details")
            toggle.setCheckable(True)
            toggle.toggled.connect(self._details.setVisible)
            toggle.toggled.connect(lambda on: toggle.setText("Hide details" if on
                                                             else "Show details"))
            copy = QPushButton("Copy details")
            copy.clicked.connect(lambda: self._copy(message, details, copy))
            buttons.addWidget(toggle)
            buttons.addWidget(copy)
        buttons.addStretch(1)
        close = QPushButton("Close")
        close.setDefault(True)
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        layout.addLayout(buttons)

    @staticmethod
    def _copy(message: str, details: str, button: QPushButton) -> None:
        QGuiApplication.clipboard().setText(f"{DISPLAY_NAME} {__version__}\n{message}\n\n{details}")
        button.setText("Copied")


def show_error(parent: QWidget | None, message: str, details: str = "") -> None:
    ErrorDialog(parent, message, details).exec()


class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(560)
        self._settings = settings
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 16)
        layout.setSpacing(10)

        look = QGroupBox("Appearance")
        look_form = QFormLayout(look)
        self._theme = QComboBox()
        for label, value in (("Match the system", "system"), ("Light", "light"),
                             ("Dark", "dark")):
            self._theme.addItem(label, value)
        self._theme.setCurrentIndex(max(self._theme.findData(settings.theme), 0))
        look_form.addRow("Theme", self._theme)
        layout.addWidget(look)

        output = QGroupBox("Saving")
        form = QFormLayout(output)
        self._folder = QLineEdit(settings.output_folder)
        self._folder.setPlaceholderText("Same folder as the original")
        browse = QPushButton("Browse…")
        browse.clicked.connect(lambda: self._pick_folder(self._folder))
        row = QHBoxLayout()
        row.addWidget(self._folder, 1)
        row.addWidget(browse)
        form.addRow("Default output folder", row)
        self._rename = QRadioButton("Add a number: report_compressed (2).pdf")
        self._replace = QRadioButton("Replace the existing file")
        (self._replace if settings.replace_existing else self._rename).setChecked(True)
        exists = QVBoxLayout()
        exists.addWidget(self._rename)
        exists.addWidget(self._replace)
        form.addRow("If the output name is taken", exists)
        self._overwrite = QCheckBox("Ctrl+S writes over the open file (otherwise it saves a copy)")
        self._overwrite.setChecked(settings.save_overwrites_original)
        form.addRow("Organiser", self._overwrite)
        self._preset = QComboBox()
        for preset in CompressPreset:
            self._preset.addItem(PRESET_LABELS[preset], preset.value)
        self._preset.setCurrentIndex(self._preset.findData(settings.compress_preset.value))
        form.addRow("Default compression", self._preset)
        layout.addWidget(output)

        engine_box = QGroupBox("External engines (detected automatically)")
        eform = QFormLayout(engine_box)
        self._engines: dict[str, QLineEdit] = {}
        for name in ENGINE_NAMES:
            edit = QLineEdit(settings.engine_path(name))
            detected = engines.find(name)
            edit.setPlaceholderText(str(detected) if detected else "Not found")
            pick = QPushButton("Browse…")
            pick.clicked.connect(lambda _=False, e=edit: self._pick_file(e))
            row = QHBoxLayout()
            row.addWidget(edit, 1)
            row.addWidget(pick)
            eform.addRow(engines.LABELS[name], row)
            self._engines[name] = edit
        eform.addRow(muted("Ghostscript: best compression, PDF/A and grayscale. Tesseract: OCR. "
                           "LibreOffice: exact-layout Office → PDF."))
        layout.addWidget(engine_box)

        logs = QPushButton("Open log folder")
        logs.clicked.connect(lambda: open_with_system(log_dir()))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        bottom = QHBoxLayout()
        bottom.addWidget(logs)
        bottom.addStretch(1)
        bottom.addWidget(buttons)
        layout.addLayout(bottom)

    def _pick_folder(self, edit: QLineEdit) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Choose folder", edit.text())
        if folder:
            edit.setText(folder)

    def _pick_file(self, edit: QLineEdit) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose program", edit.text())
        if path:
            edit.setText(path)

    def _save(self) -> None:
        folder = self._folder.text().strip()
        if folder and not Path(folder).is_dir():
            QMessageBox.warning(self, "Settings", f"Folder not found:\n{folder}")
            return
        s = self._settings
        s.output_folder = folder
        s.replace_existing = self._replace.isChecked()
        s.save_overwrites_original = self._overwrite.isChecked()
        s.compress_preset = CompressPreset(self._preset.currentData())
        for name, edit in self._engines.items():
            s.set_engine_path(name, edit.text().strip())
        if self._theme.currentData() != s.theme:
            from PySide6.QtWidgets import QApplication

            from pdfsoul.app.theme import apply_theme

            s.theme = self._theme.currentData()
            app = QApplication.instance()
            if isinstance(app, QApplication):
                apply_theme(app, s.theme)
        self.accept()


QUOTES = [
    "Every PDF has a soul. This app just helps it find its best shape.",
    "Your files stay home. They like it there.",
    "No cloud was harmed in the making of your PDF.",
    "Compressed, converted and cared for — right here on your machine.",
]
SECRET = "You found the soul of PDFSoul. Billy says hi! 👋"


class _Mark(QLabel):
    """The logo; click it five times for a little surprise."""

    clicked = Signal()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        self.clicked.emit()
        super().mousePressEvent(event)


class AboutDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        from pdfsoul.app import icons
        from pdfsoul.app.panels import TOOLS
        from pdfsoul.app.theme import tokens

        super().__init__(parent)
        self.setObjectName("About")
        self.setWindowTitle(f"About {DISPLAY_NAME}")
        self.setFixedWidth(480)
        t = tokens()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 30, 32, 24)
        layout.setSpacing(0)
        center = Qt.AlignmentFlag.AlignHCenter

        self._mark = _Mark()
        self._mark.setPixmap(icons.app_mark(76, accent=t.accent))
        self._mark.setCursor(Qt.CursorShape.PointingHandCursor)
        self._mark.clicked.connect(self._poke)
        self._pokes = 0
        layout.addWidget(self._mark, alignment=center)
        layout.addSpacing(14)
        layout.addWidget(QLabel(DISPLAY_NAME, objectName="AboutName"), alignment=center)
        layout.addSpacing(2)
        layout.addWidget(QLabel(f"Version {__version__}  ·  Offline PDF toolkit",
                                objectName="AboutMuted"), alignment=center)
        layout.addSpacing(16)

        love = QHBoxLayout()
        love.setSpacing(7)
        love.addStretch(1)
        love.addWidget(QLabel("Developed with", objectName="AboutLove"))
        heart = QLabel()
        heart.setPixmap(icons.pixmap("heart", "#e5484d", 18))
        love.addWidget(heart)
        love.addWidget(QLabel(f"by <b>{AUTHOR}</b>", objectName="AboutLove"))
        love.addStretch(1)
        layout.addLayout(love)
        layout.addSpacing(10)
        layout.addWidget(QLabel("FREE FOR PERSONAL AND COMMERCIAL USE", objectName="AboutPill"),
                         alignment=center)
        layout.addSpacing(22)

        stats = QHBoxLayout()
        stats.setSpacing(10)
        for value, label in ((f"{len(TOOLS)}", "PDF tools"), ("0 bytes", "ever uploaded"),
                             ("100%", "offline")):
            tile = QFrame(objectName="AboutTile")
            box = QVBoxLayout(tile)
            box.setContentsMargins(8, 12, 8, 12)
            box.setSpacing(2)
            box.addWidget(QLabel(value, objectName="AboutStat"), alignment=center)
            box.addWidget(QLabel(label, objectName="AboutMuted"), alignment=center)
            stats.addWidget(tile, 1)
        layout.addLayout(stats)
        layout.addSpacing(18)

        for line in ("No accounts, no sign-ups, no subscriptions",
                     "No watermarks, no page limits, no file-size caps",
                     "Works without internet — on a plane, in a cabin, anywhere",
                     "Your documents never leave this computer"):
            row = QHBoxLayout()
            row.setSpacing(10)
            check = QLabel()
            check.setPixmap(icons.pixmap("check-circle", t.accent, 16))
            row.addWidget(check)
            row.addWidget(QLabel(line), 1)
            layout.addLayout(row)
            layout.addSpacing(7)
        layout.addSpacing(12)

        self._quote = QLabel(f"“{random.choice(QUOTES)}”", objectName="AboutQuote")
        self._quote.setWordWrap(True)
        self._quote.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._quote)
        layout.addSpacing(18)

        credits = QLabel("Standing on the shoulders of open-source giants: Qt (PySide6), "
                         "PyMuPDF, Ghostscript, pikepdf, Pillow, Tesseract and pdf2docx.",
                         objectName="AboutSmall")
        credits.setWordWrap(True)
        credits.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(credits)
        layout.addSpacing(4)
        layout.addWidget(QLabel(f"© {date.today().year} {AUTHOR}", objectName="AboutSmall"),
                         alignment=center)
        layout.addSpacing(18)

        close = QPushButton("Close", objectName="Primary")
        close.setDefault(True)
        close.clicked.connect(self.accept)
        layout.addWidget(close)

    def _poke(self) -> None:
        self._pokes += 1
        if self._pokes == 5:
            self._quote.setText(SECRET)


def show_about(parent: QWidget | None) -> None:
    AboutDialog(parent).exec()
