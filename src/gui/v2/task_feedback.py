"""Aviso de tareas largas: insignia en la navegación, InfoBar, bandeja y
progreso en la barra de tareas de Windows.

- Insignia con el número de tareas activas sobre «Actividad».
- InfoBar al terminar o fallar una tarea (las instantáneas no avisan).
- Notificación de bandeja (QSystemTrayIcon.showMessage) si una tarea larga
  termina con la ventana en segundo plano.
- Windows: progreso indeterminado en el botón de la barra de tareas mientras
  hay tareas (ITaskbarList3 por COM con ctypes, sin comtypes ni pywin32).
"""

from __future__ import annotations

import ctypes
import sys
from datetime import datetime

from PyQt6.QtCore import QObject
from PyQt6.QtWidgets import QSystemTrayIcon
from qfluentwidgets import InfoBadge, InfoBadgePosition, InfoBar, InfoBarPosition

from src.gui.task_center import BackgroundTaskRegistry
from src.utils.logger import debug

INFOBAR_MIN_SECONDS = 1.0   # Tareas más cortas no muestran InfoBar si salen bien
TRAY_MIN_SECONDS = 10.0     # Solo las tareas largas avisan desde la bandeja
SUCCESS_STATUSES = {"Completada"}
WARNING_STATUSES = {"Cancelada", "Completada con errores", "Con errores"}


class WindowsTaskbarProgress:
    """ITaskbarList3 mínimo vía ctypes (SetProgressState sobre el HWND).

    En otros sistemas, o si COM no está disponible, no hace nada.
    """

    TBPF_NOPROGRESS = 0x0
    TBPF_INDETERMINATE = 0x1
    TBPF_NORMAL = 0x2
    TBPF_ERROR = 0x4
    # Índices en la vtable: IUnknown (0-2), ITaskbarList (3-7),
    # ITaskbarList2 (8), ITaskbarList3: SetProgressValue (9), SetProgressState (10)
    _HR_INIT = 3
    _SET_PROGRESS_VALUE = 9
    _SET_PROGRESS_STATE = 10

    def __init__(self):
        self._taskbar = None
        self._state = None
        if sys.platform != "win32":
            return
        try:
            self._taskbar = self._create()
        except (OSError, AttributeError, ValueError) as exc:
            debug(f"Barra de tareas sin progreso: {exc}")
            self._taskbar = None

    @staticmethod
    def _guid(text: str):
        class GUID(ctypes.Structure):
            _fields_ = [("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort),
                        ("Data3", ctypes.c_ushort), ("Data4", ctypes.c_ubyte * 8)]
        guid = GUID()
        ctypes.oledll.ole32.CLSIDFromString(ctypes.c_wchar_p(text), ctypes.byref(guid))
        return guid

    def _create(self):
        ole32 = ctypes.oledll.ole32
        ole32.CoInitialize(None)  # Qt ya lo inicializó (STA): devuelve S_FALSE
        clsid = self._guid("{56FDF344-FD6D-11d0-958A-006097C9A090}")  # CLSID_TaskbarList
        iid = self._guid("{EA1AFB91-9E28-4B86-90E9-9E9F8A5EEFAF}")    # IID_ITaskbarList3
        pointer = ctypes.c_void_p()
        ole32.CoCreateInstance(ctypes.byref(clsid), None, 1, ctypes.byref(iid), ctypes.byref(pointer))
        self._pointer = pointer
        self._call(self._HR_INIT, ctypes.HRESULT)
        return pointer

    def _call(self, index: int, restype, *args, argtypes=()):
        vtable = ctypes.cast(self._pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        prototype = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)
        return prototype(vtable[index])(self._pointer, *args)

    @property
    def available(self) -> bool:
        return self._taskbar is not None

    def set_state(self, hwnd: int, state: int) -> None:
        if self._taskbar is None or not hwnd or state == self._state:
            return
        try:
            self._call(self._SET_PROGRESS_STATE, ctypes.HRESULT, ctypes.c_void_p(hwnd), ctypes.c_int(state),
                       argtypes=(ctypes.c_void_p, ctypes.c_int))
            self._state = state
        except OSError as exc:
            debug(f"No se pudo actualizar la barra de tareas: {exc}")


class TaskFeedback(QObject):
    """Conecta el registro de tareas con la ventana."""

    def __init__(self, window, registry: BackgroundTaskRegistry, nav_route: str = "activity", parent=None):
        super().__init__(parent or window)
        self.window = window
        self.registry = registry
        self.nav_route = nav_route
        self.badge = None
        self.tray = None
        self.taskbar = WindowsTaskbarProgress()
        self.last_notification: tuple[str, str] | None = None
        registry.tasks_updated.connect(self.refresh)
        registry.task_finished.connect(self.on_task_finished)
        self.refresh()

    # -------------------------------------------------------- insignia
    def _nav_item(self):
        try:
            return self.window.navigationInterface.widget(self.nav_route)
        except (AttributeError, KeyError):
            return None

    def refresh(self) -> None:
        count = self.registry.active_count()
        item = self._nav_item()
        if item is not None:
            if self.badge is None and count:
                self.badge = InfoBadge.attension(str(count), parent=item.parent(), target=item,
                                                 position=InfoBadgePosition.NAVIGATION_ITEM)
                self.badge.setAccessibleName("Tareas activas")
            if self.badge is not None:
                self.badge.setText(str(count))
                self.badge.setVisible(bool(count))
                self.badge.adjustSize()
        if item is not None:
            item.setToolTip(f"Actividad · {count} {'tarea activa' if count == 1 else 'tareas activas'}"
                            if count else "Actividad")
        hwnd = int(self.window.winId()) if self.taskbar.available else 0
        self.taskbar.set_state(hwnd, WindowsTaskbarProgress.TBPF_INDETERMINATE if count
                               else WindowsTaskbarProgress.TBPF_NOPROGRESS)

    @property
    def active_count(self) -> int:
        return self.registry.active_count()

    # ---------------------------------------------------------- avisos
    def on_task_finished(self, task_id: str, title: str, status: str) -> None:
        task = self.registry.get_task(task_id) or {}
        started = task.get("started_at")
        ended = task.get("ended_at") or datetime.now()
        seconds = (ended - started).total_seconds() if started else 0.0
        ok = status in SUCCESS_STATUSES
        if ok and seconds < INFOBAR_MIN_SECONDS:
            return
        message = self._message(title, status, task.get("last_message", ""))
        if self.window.isActiveWindow() or seconds < TRAY_MIN_SECONDS:
            self._infobar(title, status, message)
        else:
            self._tray(title, status, message)

    @staticmethod
    def _message(title: str, status: str, last_message: str) -> str:
        if status in SUCCESS_STATUSES:
            return last_message or f"{title}: completada."
        if status in WARNING_STATUSES:
            return f"{title}: {status.lower()}. Revisa Actividad para ver los detalles."
        return f"{title}: terminó con errores. Revisa Actividad."

    def _infobar(self, title: str, status: str, message: str) -> None:
        self.last_notification = ("infobar", status)
        if status in SUCCESS_STATUSES:
            factory = InfoBar.success
        elif status in WARNING_STATUSES:
            factory = InfoBar.warning
        else:
            factory = InfoBar.error
        factory(f"{title} · {status}", message, duration=5000,
                position=InfoBarPosition.TOP_RIGHT, parent=self.window)

    def _tray(self, title: str, status: str, message: str) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            self._infobar(title, status, message)
            return
        if self.tray is None:
            self.tray = QSystemTrayIcon(self.window.windowIcon(), self)
            self.tray.setToolTip(self.window.windowTitle())
            self.tray.messageClicked.connect(self._raise_window)
            self.tray.activated.connect(lambda _reason: self._raise_window())
        self.tray.show()
        icon = (QSystemTrayIcon.MessageIcon.Information if status in SUCCESS_STATUSES
                else QSystemTrayIcon.MessageIcon.Warning)
        self.last_notification = ("tray", status)
        self.tray.showMessage(f"{title} · {status}", message, icon, 8000)

    def _raise_window(self) -> None:
        self.window.showNormal() if self.window.isMinimized() else self.window.show()
        self.window.raise_()
        self.window.activateWindow()
        switch = getattr(self.window, "_switch_route", None)
        if callable(switch):
            switch(self.nav_route)

    def shutdown(self) -> None:
        if self.tray is not None:
            self.tray.hide()
        hwnd = int(self.window.winId()) if self.taskbar.available else 0
        self.taskbar.set_state(hwnd, WindowsTaskbarProgress.TBPF_NOPROGRESS)
