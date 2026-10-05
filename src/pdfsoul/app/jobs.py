"""Runs core operations on a QThreadPool so the window never freezes. Every job is cancellable."""

from __future__ import annotations

import logging
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event
from typing import Any

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from pdfsoul.core.types import Cancelled, PdfSoulError, Result

log = logging.getLogger(__name__)


@dataclass
class JobSpec:
    """One call to a core operation: ``fn(inputs, output, opts, progress, cancel)``."""

    title: str
    fn: Callable[..., Result]
    inputs: list[Path]
    output: Path
    opts: Any = None
    on_done: Callable[[Result], None] | None = None
    on_error: Callable[[str], None] | None = None
    extra: dict[str, Any] = field(default_factory=dict)


class _Signals(QObject):
    progress = Signal(float)
    finished = Signal(object)
    failed = Signal(str, str)  # user message, technical details
    cancelled = Signal()


class _Worker(QRunnable):
    def __init__(self, spec: JobSpec) -> None:
        super().__init__()
        self.setAutoDelete(False)
        self.spec = spec
        self.cancel = Event()
        self.signals = _Signals()
        self._last = -1.0

    def _progress(self, fraction: float) -> None:
        if fraction - self._last >= 0.005 or fraction >= 1.0:  # don't flood the UI thread
            self._last = fraction
            self.signals.progress.emit(fraction)

    def run(self) -> None:
        spec = self.spec
        log.info("Job start: %s %s → %s", spec.title, [str(p) for p in spec.inputs], spec.output)
        try:
            result = spec.fn(spec.inputs, spec.output, spec.opts, self._progress, self.cancel)
        except Cancelled:
            log.info("Job cancelled: %s", spec.title)
            self.signals.cancelled.emit()
        except PdfSoulError as exc:
            log.warning("Job failed: %s: %s", spec.title, exc)
            self.signals.failed.emit(str(exc), traceback.format_exc())
        except Exception as exc:  # unexpected: keep the app alive, give the user the details
            log.exception("Job crashed: %s", spec.title)
            self.signals.failed.emit(f"Something went wrong: {exc}", traceback.format_exc())
        else:
            log.info("Job done: %s: %s", spec.title, result.message)
            self.signals.finished.emit(result)


class JobRunner(QObject):
    """Runs one job at a time and reports progress to whoever is listening (the status bar)."""

    started = Signal(str)
    progress = Signal(float)
    finished = Signal(object)  # Result
    failed = Signal(str, str)
    cancelled = Signal()
    idle = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._pool = QThreadPool.globalInstance()
        self._current: _Worker | None = None

    @property
    def busy(self) -> bool:
        return self._current is not None

    def start(self, spec: JobSpec) -> bool:
        if self._current is not None:
            return False
        worker = _Worker(spec)
        worker.signals.progress.connect(self.progress)
        worker.signals.finished.connect(lambda r: self._finish(worker, r))
        worker.signals.failed.connect(lambda m, d: self._fail(worker, m, d))
        worker.signals.cancelled.connect(lambda: self._cancelled(worker))
        self._current = worker
        self.started.emit(spec.title)
        self._pool.start(worker)
        return True

    def cancel(self) -> None:
        if self._current is not None:
            self._current.cancel.set()

    def wait(self, msecs: int = 30_000) -> bool:
        """Block until running jobs finish (used on quit and in tests)."""
        return self._pool.waitForDone(msecs)

    def _finish(self, worker: _Worker, result: Result) -> None:
        self._current = None
        self.finished.emit(result)
        if worker.spec.on_done:
            worker.spec.on_done(result)
        self.idle.emit()

    def _fail(self, worker: _Worker, message: str, details: str) -> None:
        self._current = None
        self.failed.emit(message, details)
        if worker.spec.on_error:
            worker.spec.on_error(message)
        self.idle.emit()

    def _cancelled(self, worker: _Worker) -> None:
        self._current = None
        self.cancelled.emit()
        if worker.spec.on_error:
            worker.spec.on_error("Cancelled.")
        self.idle.emit()
