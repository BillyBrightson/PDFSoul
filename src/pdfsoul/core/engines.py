"""Locate and run external engines: Ghostscript, Tesseract, LibreOffice.

Lookup order: a path the user set in Settings → the app's bundled ``bin/`` folder →
``PATH`` → the usual install folders for the platform.
"""

from __future__ import annotations

import glob
import os
import queue
import shutil
import subprocess
import sys
import threading
from collections.abc import Callable
from pathlib import Path
from threading import Event

from pdfsoul.core.types import Cancelled, EngineMissing, PdfSoulError

WINDOWS = sys.platform == "win32"

_NAMES: dict[str, list[str]] = {
    "gs": ["gswin64c", "gswin32c", "gs"] if WINDOWS else ["gs"],
    "tesseract": ["tesseract"],
    "soffice": ["soffice", "libreoffice"],
}

_KNOWN_LOCATIONS: dict[str, list[str]] = {
    "gs": [
        r"C:\Program Files\gs\gs*\bin\gswin64c.exe",
        r"C:\Program Files (x86)\gs\gs*\bin\gswin32c.exe",
        "/opt/homebrew/bin/gs",
        "/usr/local/bin/gs",
        "/usr/bin/gs",
    ],
    "tesseract": [
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        "/opt/homebrew/bin/tesseract",
        "/usr/local/bin/tesseract",
        "/usr/bin/tesseract",
    ],
    "soffice": [
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
        "/Applications/LibreOffice.app/Contents/MacOS/soffice",
        "/usr/bin/soffice",
        "/usr/bin/libreoffice",
    ],
}

LABELS = {"gs": "Ghostscript", "tesseract": "Tesseract OCR", "soffice": "LibreOffice"}

_overrides: dict[str, str] = {}
_cache: dict[str, Path | None] = {}


def bundled_bin_dir() -> Path:
    """``bin/`` beside the frozen app, or at the repo root when running from source."""
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        return base / "bin"
    return Path(__file__).resolve().parents[3] / "bin"


def set_override(name: str, path: str | None) -> None:
    """Use ``path`` for engine ``name`` (from Settings); ``None`` or blank restores auto-detect."""
    if path:
        _overrides[name] = path
    else:
        _overrides.pop(name, None)
    _cache.pop(name, None)


def find(name: str) -> Path | None:
    """Return the engine's executable, or ``None`` if it isn't installed."""
    if name not in _cache:
        _cache[name] = _locate(name)
    return _cache[name]


def require(name: str) -> Path:
    path = find(name)
    if path is None:
        raise EngineMissing(
            f"{LABELS.get(name, name)} was not found. Install it, or set its path in Settings."
        )
    return path


def _locate(name: str) -> Path | None:
    override = _overrides.get(name)
    if override and Path(override).is_file():
        return Path(override)
    exe = ".exe" if WINDOWS else ""
    for folder in (bundled_bin_dir(), bundled_bin_dir() / name):
        for candidate in _NAMES[name]:
            path = folder / f"{candidate}{exe}"
            if path.is_file():
                return path
    for candidate in _NAMES[name]:
        found = shutil.which(candidate)
        if found:
            return Path(found)
    for pattern in _KNOWN_LOCATIONS[name]:
        matches = sorted(glob.glob(pattern), reverse=True)  # newest version folder first
        if matches:
            return Path(matches[0])
    return None


def run(
    cmd: list[str],
    *,
    cancel: Event | None = None,
    on_line: Callable[[str], None] | None = None,
    timeout: float | None = None,
) -> str:
    """Run an engine, streaming its output lines to ``on_line``. Kills it if ``cancel`` is set.

    Returns combined stdout/stderr. Raises :class:`PdfSoulError` on a non-zero exit.
    """
    flags: int = getattr(subprocess, "CREATE_NO_WINDOW", 0) if WINDOWS else 0
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        text=True,
        errors="replace",
        creationflags=flags,
        env={**os.environ, "OMP_THREAD_LIMIT": "1"},
    )
    lines: queue.Queue[str | None] = queue.Queue()

    def pump() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            lines.put(line)
        lines.put(None)

    threading.Thread(target=pump, daemon=True).start()
    captured: list[str] = []
    waited = 0.0
    while True:
        if cancel is not None and cancel.is_set():
            proc.kill()
            proc.wait()
            raise Cancelled()
        try:
            line = lines.get(timeout=0.1)
        except queue.Empty:
            waited += 0.1
            if timeout is not None and waited > timeout:
                proc.kill()
                raise PdfSoulError(f"{Path(cmd[0]).name} timed out.") from None
            continue
        if line is None:
            break
        captured.append(line)
        if on_line:
            on_line(line.rstrip())
    code = proc.wait()
    output = "".join(captured)
    if code != 0:
        tail = "\n".join(output.strip().splitlines()[-5:])
        raise PdfSoulError(f"{Path(cmd[0]).name} failed (exit code {code}).\n{tail}")
    return output
