"""Worker cooperativo con identificador para descartar señales antiguas."""

from PyQt6.QtCore import QThread, pyqtSignal
from src.core.space_usage import rescan_subtree, scan_space, SpaceScanCancelled


class SpaceScanWorker(QThread):
    progress = pyqtSignal(int, int, int, object, int, str)
    result_ready = pyqtSignal(int, object)
    scan_cancelled = pyqtSignal(int)
    scan_failed = pyqtSignal(int, str)

    def __init__(self, run_id: int, root_path: str, parent=None, base_result=None, node_id=None,
                 measure_disk: bool = True, dedupe_hardlinks: bool = True):
        super().__init__(parent)
        self.run_id = run_id
        self.root_path = root_path
        self.base_result = base_result
        self.node_id = node_id
        self.measure_disk = measure_disk
        self.dedupe_hardlinks = dedupe_hardlinks

    def run(self):
        report = lambda *values: self.progress.emit(self.run_id, *values)  # noqa: E731
        try:
            if self.base_result is not None and self.node_id is not None:
                # Reanálisis incremental: sólo la subcarpeta, totales recalculados.
                result = rescan_subtree(self.base_result, self.node_id, self.isInterruptionRequested, report,
                                        dedupe_hardlinks=self.dedupe_hardlinks)
            else:
                # Sólo se pasan las opciones que difieren de los valores por defecto.
                options = {key: value for key, value in (("measure_disk", self.measure_disk),
                                                         ("dedupe_hardlinks", self.dedupe_hardlinks)) if not value}
                result = scan_space(self.root_path, self.isInterruptionRequested, report, **options)
            if self.isInterruptionRequested():
                raise SpaceScanCancelled()
            self.result_ready.emit(self.run_id, result)
        except SpaceScanCancelled:
            self.scan_cancelled.emit(self.run_id)
        except Exception as error:
            self.scan_failed.emit(self.run_id, str(error))
