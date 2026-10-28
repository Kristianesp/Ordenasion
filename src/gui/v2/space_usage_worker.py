"""Worker cooperativo con identificador para descartar señales antiguas."""

from PyQt6.QtCore import QThread, pyqtSignal
from src.core.space_usage import scan_space, SpaceScanCancelled, SpaceScanError


class SpaceScanWorker(QThread):
    progress = pyqtSignal(int, int, int, object, int, str)
    result_ready = pyqtSignal(int, object)
    scan_cancelled = pyqtSignal(int)
    scan_failed = pyqtSignal(int, str)

    def __init__(self, run_id: int, root_path: str, parent=None):
        super().__init__(parent)
        self.run_id = run_id
        self.root_path = root_path

    def run(self):
        try:
            result = scan_space(self.root_path, self.isInterruptionRequested,
                                lambda *values: self.progress.emit(self.run_id, *values))
            if self.isInterruptionRequested():
                raise SpaceScanCancelled()
            self.result_ready.emit(self.run_id, result)
        except SpaceScanCancelled:
            self.scan_cancelled.emit(self.run_id)
        except Exception as error:
            self.scan_failed.emit(self.run_id, str(error))
