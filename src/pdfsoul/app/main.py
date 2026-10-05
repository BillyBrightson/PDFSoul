"""Desktop entry point: ``pdfsoul-gui [file.pdf]`` (or double-click a PDF once associated)."""

from __future__ import annotations

import logging
import sys
import traceback
from pathlib import Path

from PySide6.QtCore import QEvent, QTimer
from PySide6.QtGui import QFileOpenEvent, QIcon
from PySide6.QtWidgets import QApplication

from pdfsoul import APP_NAME, DISPLAY_NAME, __version__
from pdfsoul.app.dialogs import show_error
from pdfsoul.app.logging_setup import setup_logging
from pdfsoul.app.main_window import MainWindow
from pdfsoul.app.panels import TOOLS_BY_ID
from pdfsoul.app.settings import Settings
from pdfsoul.app.theme import follow_system_theme

log = logging.getLogger("pdfsoul")


class PdfSoulApp(QApplication):
    """Handles macOS 'open with' events, which arrive as QFileOpenEvent, not argv."""

    def __init__(self, argv: list[str]) -> None:
        super().__init__(argv)
        self.window: MainWindow | None = None
        self.pending: list[Path] = []

    def event(self, event: QEvent) -> bool:
        if event.type() == QEvent.Type.FileOpen and isinstance(event, QFileOpenEvent):
            path = Path(event.file())
            if self.window is not None:
                self.window.handle_dropped([path])
            else:
                self.pending.append(path)
            return True
        return super().event(event)


def _icon() -> QIcon:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[3]))
    for candidate in (base / "packaging" / "pdfsoul.png", base / "pdfsoul.png"):
        if candidate.exists():
            return QIcon(str(candidate))
    return QIcon()


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    folder = setup_logging()
    log.info("%s %s starting (logs in %s)", APP_NAME, __version__, folder)

    app = PdfSoulApp(argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(DISPLAY_NAME)
    app.setOrganizationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setWindowIcon(_icon())
    settings = Settings()
    follow_system_theme(app, settings.theme)

    window = MainWindow(settings)
    app.window = window

    def excepthook(kind, value, tb) -> None:
        details = "".join(traceback.format_exception(kind, value, tb))
        log.error("Unhandled exception:\n%s", details)
        show_error(window, f"Something went wrong: {value}", details)

    sys.excepthook = excepthook
    window.show()

    args = argv[1:]
    tool = None
    if "--tool" in args:  # e.g. Explorer's "Compress with PDFSoul": --tool compress file.pdf
        at = args.index("--tool")
        tool = args[at + 1] if at + 1 < len(args) else None
        del args[at:at + 2]
    files = [Path(a) for a in args if not a.startswith("-")] + app.pending

    def start() -> None:
        if files:
            window.handle_dropped(files)
        if tool in TOOLS_BY_ID:
            window.select_tool(tool)

    QTimer.singleShot(0, start)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
