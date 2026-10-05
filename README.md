# PDFSoul

An offline desktop PDF toolkit for Windows 10/11 that replaces iLovePDF, Smallpdf and Acrobat
for everyday work. Files never leave the PC: PDFSoul makes no network calls.

Built with **Python 3.12 + PySide6 + PyMuPDF**, with pikepdf (qpdf) for encryption and repair
and Ghostscript for compression. The code is cross-platform; Windows is the shipping target.

## What v1 does

| Area | Tools |
| --- | --- |
| Viewer | Open by menu, drag-drop or double-click · continuous scroll · zoom (fit width/page, Ctrl+wheel) · thumbnails · text search with highlights, case toggle, next/previous |
| Organise | Thumbnail grid: multi-select, drag to reorder, rotate, delete, duplicate, insert blank, extract — previewed, undoable (Ctrl+Z/Y), written only on save |
| Merge | Files and folders, drag to reorder, page ranges per file, bookmarks kept |
| Split | Every page · ranges (`1-3,5,8-`) · every N pages · top-level bookmarks |
| Compress | Low / Medium / High → Ghostscript `screen` / `ebook` / `printer` + lossless pikepdf pass; keeps the original if the result isn't smaller |
| Convert from PDF | Word (.docx, layout rebuilt by pdf2docx) · Excel (.xlsx, tables detected, numbers become numbers) · PowerPoint (.pptx, one slide per page, text in notes) · PNG / JPG / WebP / TIFF / SVG · plain text · Markdown (headings, lists, tables) · HTML (reflowing or exact layout) · PDF/A-1b/2b/3b · grayscale · extract images |
| Convert to PDF | Word, Excel, PowerPoint, OpenDocument, RTF via LibreOffice — or, without it, a built-in renderer for DOCX / XLSX / CSV / PPTX · HTML, Markdown, TXT · ePub, MOBI, FB2, XPS, CBZ, SVG · images (JPG, PNG, HEIC, TIFF, WebP, BMP) · several files merge into one PDF with a bookmark each |
| OCR | Tesseract adds an invisible text layer to scanned pages so they're searchable; the page image is untouched; pages that already have text are skipped |
| Secure | AES-256 password, permissions (print / copy / edit), remove a known password |
| Stamp | Text or image watermark (opacity, angle, position, behind/over) · page numbers (`{n}`, `{total}`, position, start) · live preview |

Every operation writes a **new file** (`report_compressed.pdf`) and shows Open / Show in folder.
Originals are only overwritten if you choose that explicitly (Save As onto the same file, or
the "Ctrl+S writes over the open file" setting).

Robustness: outputs go to a temp file and are atomically renamed, so a crash never corrupts
anything; damaged PDFs are repaired automatically with qpdf on open; every job runs on a worker
thread with a Cancel button.

## Run it from source

```bash
uv sync                      # Python 3.12 + dependencies into .venv
uv run pdfsoul-gui           # desktop app (or: uv run pdfsoul-gui file.pdf)
uv run pdfsoul --help        # command line
```

Install [Ghostscript](https://ghostscript.com/releases/gsdnld.html) for the best compression
(`brew install ghostscript` on macOS). Without it PDFSoul falls back to MuPDF's image
rewriting. Ghostscript is also needed for PDF/A. Two more engines are optional:
[Tesseract](https://github.com/tesseract-ocr/tesseract) for OCR (`brew install tesseract`) and
[LibreOffice](https://www.libreoffice.org) for exact-layout Office → PDF and for legacy
formats such as `.doc` and `.ppt`. Settings lets you point at a specific copy of each, and
choose a light, dark or system theme.

## Command line

The CLI calls the same core functions as the app. Exit code is 0 on success, 1 when an
operation fails, 2 for bad usage, 130 when cancelled.

```bash
pdfsoul merge a.pdf b.pdf:1-3 c.pdf -o out.pdf
pdfsoul split report.pdf --mode bookmarks
pdfsoul compress scan.pdf --preset low
pdfsoul rotate report.pdf --pages 2-4 --angle 90
pdfsoul to-images report.pdf --format jpg --dpi 300 --pages 1
pdfsoul images-to-pdf *.jpg -o photos.pdf --page-size a4
pdfsoul watermark report.pdf --text DRAFT --opacity 0.3
pdfsoul number report.pdf --format "Page {n} of {total}" --position bottom-right
pdfsoul convert report.pdf --to docx  # also xlsx pptx html md txt pdfa gray png jpg webp tiff svg
pdfsoul to-pdf letter.docx notes.md photo.heic -o bundle.pdf
pdfsoul ocr scan.pdf --lang eng+fra
pdfsoul protect report.pdf            # prompts for the password
pdfsoul info report.pdf
```

Without `-o`, output goes next to the input as `name_<tool>.pdf` and never replaces an existing
file. Encrypted inputs take `--password` (or prompt when run interactively).

## Architecture

The one rule: **`core/` never imports Qt.** Every operation is a plain function with one
signature, called the same way by the UI, the CLI and the tests:

```python
def compress(inputs: list[Path], output: Path, opts: CompressOptions,
             progress: Callable[[float], None], cancel: Event) -> Result: ...
```

```text
src/pdfsoul/
  core/                  pure functions, no Qt
    organise.py          merge, split, rotate, reorder, delete, duplicate, insert blank, extract
    pagelist.py          the organiser's editable page plan with undo/redo
    convert.py           images ↔ PDF, extract text and images
    edit.py              watermarks and page numbers
    secure.py            encrypt, decrypt, permissions
    optimise.py          compress, repair
    render.py            page geometry, rendering, search hits (rotation-aware)
    engines.py           locate and run Ghostscript / Tesseract / LibreOffice
    document.py          open (passwords, auto-repair), save safely
    safe_io.py           temp file + atomic rename, output naming
    ranges.py            "1-3,5,8-" parsing
  app/                   PySide6 UI
    main_window.py       3-pane layout, menus, shortcuts, search, saving
    viewer.py            continuous-scroll viewer, lazy rendering
    thumbnails.py        thumbnail model, side strip, organiser grid
    panels/              one options panel per tool
    jobs.py              QThreadPool worker: progress, cancel, errors
    session.py           the open document, its page plan and render caches
  cli/main.py            Typer commands
tests/                   pytest (core, CLI, robustness sweep) + pytest-qt smoke tests
packaging/               PyInstaller spec, Inno Setup script, Windows and macOS build scripts, icons
bin/                     bundled engines (filled by the Windows build)
```

## Develop

```bash
uv run pytest                 # 240 tests; app tests run offscreen
uv run ruff check src tests
uv run mypy                   # type-checks core/
```

`tests/conftest.py` generates the awkward fixtures the PRD asks for: scanned, encrypted, form,
1,000-page, corrupted, non-Latin and rotated PDFs. Every core operation runs against every one
of them in `tests/test_robustness.py`. Drop real-world PDFs into `tests/fixtures/` and they join
the sweep automatically.

Logs: `%APPDATA%\PDFSoul\logs` on Windows (`~/Library/Logs/PDFSoul` on macOS). Error dialogs
show a short message with "Copy details".

## Build the Windows installer

On Windows with [uv](https://docs.astral.sh/uv/), Ghostscript and Inno Setup 6 installed
(`choco install ghostscript innosetup`):

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1
```

This bundles Ghostscript into `bin\`, freezes the app with PyInstaller (`--onedir`), and
produces `dist\PDFSoul-By-Billy-Setup-<version>.exe`. The bundle holds `PDFSoul.exe` (the app) and
`pdfsoul.com` (the CLI — Windows runs `.com` before `.exe`, so typing `pdfsoul` in a terminal
gets the CLI). The installer adds a Start Menu shortcut, the PDF "Open with" entry, optional
"Compress / Split with PDFSoul" right-click entries, and optionally `pdfsoul` on PATH.

## Build the macOS app

On a Mac with uv:

```bash
packaging/build_mac.sh
```

This produces `dist/PDFSoul-By-Billy-<version>-macOS-<arch>.dmg` for the Mac's own architecture
(`arm64` on Apple silicon, `x86_64` on Intel). The disk image holds `PDFSoul By Billy.app`, an
Applications shortcut, and a "Read me first" note. The app registers as an "Open with"
option for PDFs, Office files, web/eBook files and images; the CLI is at
`PDFSoul By Billy.app/Contents/MacOS/pdfsoul-cli`. Ghostscript, Tesseract and LibreOffice aren't
bundled on macOS: PDFSoul finds Homebrew installs automatically and falls back without them.

Without an Apple Developer ID the app is ad-hoc signed, so recipients open it once with
right-click → Open (or System Settings → Privacy & Security → Open Anyway). With a Developer
ID, `SIGN_IDENTITY="Developer ID Application: …" NOTARY_PROFILE=<notarytool profile>
packaging/build_mac.sh` signs, notarizes and staples the image so it opens without warnings.

## CI

GitHub Actions (`.github/workflows/build.yml`) builds everything on each push: the Windows
installer on `windows-latest`, plus an Apple silicon disk image on `macos-15` (pikepdf
no longer ships Intel macOS wheels). Download them from the run's Artifacts; for each `v*` tag they are also
attached to the release.

## Licensing

PyMuPDF and Ghostscript are AGPL-licensed. That is fine for your own use. If PDFSoul is ever
distributed or sold, either release it under the AGPL or buy the Artifex commercial licences —
or swap the core to pypdfium2 + pikepdf. PySide6 is LGPL; pikepdf is MPL 2.0.

## Roadmap

- **v2 — editing:** annotate, sign, fill/flatten forms, redact, simple text edit, metadata
  and bookmark editors.
- **v3 — power tools:** batch queue and saved chains, watch folder, compare two PDFs, Explorer
  multi-file Merge (needs single-instance IPC).
