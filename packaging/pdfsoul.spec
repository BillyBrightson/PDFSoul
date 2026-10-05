# PyInstaller spec — one --onedir bundle holding two executables that share the same files:
#   PDFSoul.exe      the desktop app (no console window)
#   pdfsoul-cli.exe  the command line (renamed to pdfsoul.com by build_windows.ps1, so typing
#                    `pdfsoul` in a terminal runs the CLI while Explorer launches the app)
# On macOS the same bundle is wrapped as "dist/PDFSoul By Billy.app" (CLI at
# Contents/MacOS/pdfsoul-cli); build_mac.sh turns that into a .dmg.
#
# Build:  uv run pyinstaller packaging/pdfsoul.spec --noconfirm
# ruff: noqa

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

ROOT = Path(SPECPATH).parent  # noqa: F821 (SPECPATH is defined by PyInstaller)

datas = [(str(ROOT / "packaging" / "pdfsoul.png"), "packaging")]
binaries = []
hiddenimports = ["pillow_heif"]
# docx and pptx load their default templates from package data at runtime.
for package in ("pymupdf", "pikepdf", "pillow_heif", "pdf2docx", "docx", "pptx", "openpyxl",
                "markdown"):
    d, b, h = collect_all(package)
    datas += d
    binaries += b
    hiddenimports += h

# Bundled engines (Ghostscript, later Tesseract) live in bin/ and are found at runtime by
# pdfsoul.core.engines.bundled_bin_dir().
bin_dir = ROOT / "bin"
for path in bin_dir.rglob("*"):
    if path.is_file() and path.name != "README.md":
        datas.append((str(path), str(Path("bin") / path.parent.relative_to(bin_dir))))

# Qt modules PDFSoul never uses — keeps the installer well under the 250 MB budget.
excludes = [
    "PySide6.Qt3DAnimation", "PySide6.Qt3DCore", "PySide6.Qt3DExtras", "PySide6.Qt3DInput",
    "PySide6.Qt3DLogic", "PySide6.Qt3DRender", "PySide6.QtBluetooth", "PySide6.QtCharts",
    "PySide6.QtDataVisualization", "PySide6.QtGraphs", "PySide6.QtLocation",
    "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets", "PySide6.QtNetworkAuth",
    "PySide6.QtNfc", "PySide6.QtPdf", "PySide6.QtPdfWidgets", "PySide6.QtPositioning",
    "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuick3D", "PySide6.QtQuickControls2",
    "PySide6.QtQuickWidgets", "PySide6.QtRemoteObjects", "PySide6.QtScxml",
    "PySide6.QtSensors", "PySide6.QtSerialBus", "PySide6.QtSerialPort", "PySide6.QtSpatialAudio",
    "PySide6.QtSql", "PySide6.QtStateMachine", "PySide6.QtTextToSpeech", "PySide6.QtWebChannel",
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineQuick", "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebSockets", "PySide6.QtWebView", "PySide6.QtHttpServer",
    "pikepdf.pdfa", "tkinter", "unittest", "pytest", "pytestqt", "mypy", "ruff",
]

common = dict(pathex=[str(ROOT / "src")], binaries=binaries, datas=datas,
              hiddenimports=hiddenimports, excludes=excludes, noarchive=False)

gui = Analysis([str(ROOT / "packaging" / "launch_gui.py")], **common)  # noqa: F821
cli = Analysis([str(ROOT / "packaging" / "launch_cli.py")], **common)  # noqa: F821

gui_pyz = PYZ(gui.pure)  # noqa: F821
cli_pyz = PYZ(cli.pure)  # noqa: F821

MACOS = sys.platform == "darwin"
icon = str(ROOT / "packaging" / ("pdfsoul.icns" if MACOS else "pdfsoul.ico"))
version_file = None if MACOS else str(ROOT / "packaging" / "version_info.txt")

gui_exe = EXE(  # noqa: F821
    gui_pyz, gui.scripts, [], exclude_binaries=True, name="PDFSoul", icon=icon,
    console=False, version=version_file, upx=False, argv_emulation=False,
)
cli_exe = EXE(  # noqa: F821
    cli_pyz, cli.scripts, [], exclude_binaries=True, name="pdfsoul-cli", icon=icon,
    console=True, version=version_file, upx=False,
)

bundle = COLLECT(  # noqa: F821
    gui_exe, gui.binaries, gui.datas,
    cli_exe, cli.binaries, cli.datas,
    name="PDFSoul", upx=False,
)

if MACOS:
    import re

    version = re.search(r'^version = "(.+)"', (ROOT / "pyproject.toml").read_text(),
                        re.MULTILINE).group(1)

    def doc_type(name, extensions, rank="Alternate"):
        return {"CFBundleTypeName": name, "CFBundleTypeRole": "Editor",
                "LSHandlerRank": rank, "CFBundleTypeExtensions": extensions}

    BUNDLE(  # noqa: F821
        bundle,
        name="PDFSoul By Billy.app",
        icon=icon,
        bundle_identifier="com.bibrtech.pdfsoul",
        version=version,
        info_plist={
            "CFBundleName": "PDFSoul By Billy",
            "CFBundleDisplayName": "PDFSoul By Billy",
            "CFBundleShortVersionString": version,
            "CFBundleVersion": version,
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "12.0",
            "LSApplicationCategoryType": "public.app-category.productivity",
            "NSHumanReadableCopyright": "© Billy Brightson. Free for personal and commercial use.",
            # "Open with" for PDFs, plus the formats PDFSoul converts to PDF.
            "CFBundleDocumentTypes": [
                doc_type("PDF document", ["pdf"]),
                doc_type("Office document", ["docx", "doc", "xlsx", "xls", "pptx", "ppt",
                                             "odt", "ods", "odp", "rtf", "csv"]),
                doc_type("Web, text or eBook", ["html", "htm", "md", "markdown", "txt",
                                                "epub", "xps", "mobi", "fb2"]),
                doc_type("Image", ["jpg", "jpeg", "png", "heic", "heif", "tif", "tiff",
                                   "webp", "bmp", "gif"]),
            ],
        },
    )
