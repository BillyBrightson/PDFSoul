"""Crash-safe output: write to a temp file beside the target, then atomically rename.

A crash or cancel mid-write never leaves a half-written file, and never touches the original.
"""

from __future__ import annotations

import contextlib
import os
import re
import tempfile
from collections.abc import Iterator
from pathlib import Path

_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')


@contextlib.contextmanager
def atomic_output(target: Path) -> Iterator[Path]:
    """Yield a temp path in the target's folder; on success move it over ``target``."""
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{target.stem[:40]}.", suffix=f".tmp{target.suffix}", dir=target.parent
    )
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        yield tmp
        os.replace(tmp, target)
    finally:
        with contextlib.suppress(FileNotFoundError):
            tmp.unlink()


def derive_output(source: Path, tag: str, ext: str = ".pdf", folder: Path | None = None) -> Path:
    """``report.pdf`` + ``compressed`` → ``report_compressed.pdf`` (in ``folder`` if given)."""
    source = Path(source)
    return (folder or source.parent) / f"{source.stem}_{tag}{ext}"


def unique_path(path: Path) -> Path:
    """Return ``path``, or ``name (2).pdf``, ``name (3).pdf``… if it already exists."""
    path = Path(path)
    if not path.exists():
        return path
    n = 2
    while True:
        candidate = path.with_name(f"{path.stem} ({n}){path.suffix}")
        if not candidate.exists():
            return candidate
        n += 1


def safe_filename(name: str, fallback: str = "untitled", max_len: int = 80) -> str:
    """Make a string safe to use as a file name on Windows, macOS and Linux."""
    cleaned = _UNSAFE.sub("_", name).strip(" ._")
    return cleaned[:max_len].rstrip(" ._") or fallback


def same_file(a: Path, b: Path) -> bool:
    """True if two paths point at the same file (the target may not exist yet)."""
    try:
        return Path(a).resolve() == Path(b).resolve()
    except OSError:
        return False
