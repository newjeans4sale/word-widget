"""전경 창이 전체화면인지 감지한다.

계속 켜두는 위젯이라, 유튜브 전체화면이나 발표 화면 위에 단어가 떠 있으면 거슬린다.
"""
from __future__ import annotations

import ctypes
import logging
import sys
from ctypes import wintypes

log = logging.getLogger(__name__)

IS_WINDOWS = sys.platform == "win32"

MONITOR_DEFAULTTONEAREST = 2
# 바탕화면 자체는 항상 화면을 가득 채우므로 전체화면으로 세면 안 된다.
SHELL_CLASSES = {"Progman", "WorkerW", "Shell_TrayWnd", "Button"}


class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD),
                ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT),
                ("dwFlags", wintypes.DWORD)]


_u32 = None


def _init() -> bool:
    global _u32
    if _u32 is not None:
        return True
    if not IS_WINDOWS:
        return False
    _u32 = ctypes.WinDLL("user32", use_last_error=True)
    _u32.GetForegroundWindow.restype = wintypes.HWND
    _u32.GetShellWindow.restype = wintypes.HWND
    _u32.GetDesktopWindow.restype = wintypes.HWND
    _u32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    _u32.GetWindowRect.restype = wintypes.BOOL
    _u32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
    _u32.MonitorFromWindow.restype = wintypes.HANDLE
    _u32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MONITORINFO)]
    _u32.GetMonitorInfoW.restype = wintypes.BOOL
    _u32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    _u32.GetClassNameW.restype = ctypes.c_int
    return True


def _class_name(hwnd) -> str:
    buf = ctypes.create_unicode_buffer(256)
    _u32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def is_foreground_fullscreen() -> bool:
    """전경 창이 자기 모니터를 가득 채우고 있으면 True. macOS 에서는 항상 False."""
    if not _init():
        return False
    try:
        hwnd = _u32.GetForegroundWindow()
        if not hwnd:
            return False
        if hwnd in (_u32.GetShellWindow(), _u32.GetDesktopWindow()):
            return False
        if _class_name(hwnd) in SHELL_CLASSES:
            return False

        rect = wintypes.RECT()
        if not _u32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return False

        monitor = _u32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        if not _u32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            return False

        m = info.rcMonitor
        return (rect.left <= m.left and rect.top <= m.top
                and rect.right >= m.right and rect.bottom >= m.bottom)
    except Exception:
        log.debug("전체화면 감지 실패", exc_info=True)
        return False
