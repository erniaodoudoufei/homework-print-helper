from __future__ import annotations

import traceback
from threading import Event

from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from .processing import Cancelled


class JobSignals(QObject):
    result = Signal(object)
    progress = Signal(int, str)
    failed = Signal(str, str)
    cancelled = Signal()
    finished = Signal()


class Job(QRunnable):
    def __init__(self, function):
        super().__init__()
        self.function = function
        self.signals = JobSignals()
        self.cancel_event = Event()

    @Slot()
    def run(self):
        try:
            value = self.function(self.signals.progress.emit, self.cancel_event)
            if self.cancel_event.is_set():
                raise Cancelled()
            self.signals.result.emit(value)
        except Cancelled:
            self.signals.cancelled.emit()
        except Exception as exc:
            self.signals.failed.emit(str(exc), traceback.format_exc())
        finally:
            self.signals.finished.emit()

    def cancel(self):
        self.cancel_event.set()
