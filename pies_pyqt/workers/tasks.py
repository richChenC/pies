from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from PyQt5.QtCore import QObject, pyqtSignal, pyqtSlot


@dataclass
class TaskResult:
    ok: bool
    payload: Any = None
    error: str = ""


class Worker(QObject):
    started = pyqtSignal(str)
    progress = pyqtSignal(int, int, str)
    finished = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self._fn = fn
        self._args = args
        self._kwargs = kwargs

    @pyqtSlot()
    def run(self):
        try:
            self.started.emit(getattr(self._fn, "__name__", "task"))
            result = self._fn(*self._args, progress_callback=self._emit_progress, **self._kwargs)
            self.finished.emit(TaskResult(ok=True, payload=result))
        except Exception as exc:
            self.failed.emit(str(exc))
            self.finished.emit(TaskResult(ok=False, error=str(exc)))

    def _emit_progress(self, current: int, total: int, message: str):
        self.progress.emit(current, total, message)
