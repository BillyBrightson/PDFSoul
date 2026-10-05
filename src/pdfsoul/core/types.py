"""Shared types for every core operation.

Every operation follows one signature::

    def op(inputs: list[Path], output: Path, opts: Options,
           progress: ProgressFn = no_progress, cancel: Event | None = None) -> Result

``core`` never imports Qt, so the UI, the CLI and the tests all call these the same way.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event
from typing import Any

ProgressFn = Callable[[float], None]


def no_progress(_: float) -> None:
    """Default progress callback that ignores updates."""


class PdfSoulError(Exception):
    """A failure the user can understand and act on. The message is shown as-is."""


class PasswordRequired(PdfSoulError):
    """The input is encrypted and no password was given."""


class WrongPassword(PdfSoulError):
    """The given password does not open the input."""


class Cancelled(PdfSoulError):
    """The user cancelled the job."""

    def __init__(self, message: str = "Cancelled") -> None:
        super().__init__(message)


class EngineMissing(PdfSoulError):
    """An external engine (Ghostscript, Tesseract, LibreOffice) could not be found."""


@dataclass
class Result:
    """What an operation produced: the files written and a one-line summary."""

    outputs: list[Path] = field(default_factory=list)
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)


def check_cancel(cancel: Event | None) -> None:
    """Raise :class:`Cancelled` if the job's cancel event is set."""
    if cancel is not None and cancel.is_set():
        raise Cancelled()


class Progress:
    """Maps sub-steps onto a 0..1 range and checks for cancellation on every tick."""

    def __init__(self, fn: ProgressFn, cancel: Event | None, total: int) -> None:
        self._fn = fn
        self._cancel = cancel
        self._total = max(total, 1)
        self._done = 0

    def step(self, n: int = 1) -> None:
        check_cancel(self._cancel)
        self._done += n
        self._fn(min(self._done / self._total, 1.0))

    def done(self) -> None:
        self._fn(1.0)
