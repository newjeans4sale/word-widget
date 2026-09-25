"""Windows 전용 네이티브 글루 (ctypes).

클릭 통과를 Qt 플래그로 토글하면 창이 숨었다 다시 떠서 깜빡이고 위치와 z-order 가
흔들린다. 살아 있는 HWND 의 확장 스타일만 뒤집으면 깜빡임이 전혀 없다.
"""
from __future__ import annotations

import ctypes
import logging
import sys
from ctypes import wintypes

log = logging.getLogger(__name__)

IS_WINDOWS = sys.platform == "win32"

GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x00000020
WS_EX_LAYERED = 0x00080000

SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020

_user32 = None
_get_long = None
_set_long = None


def _init() -> bool:
    """user32 함수들을 argtypes 와 함께 준비한다.

    argtypes 를 지정하지 않으면 ctypes 가 HWND 를 C int 로 넘겨 64비트에서 잘라먹는다.
    그러면 엉뚱한 창 핸들의 스타일을 조용히 건드리게 된다.
    """
    global _user32, _get_long, _set_long
    if _user32 is not None:
        return True
    if not IS_WINDOWS:
        return False

    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    long_ptr = ctypes.c_longlong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_long

    # 32비트 Windows 에서는 ...PtrW 가 매크로라 export 되지 않는다.
    _get_long = getattr(_user32, "GetWindowLongPtrW", None) or _user32.GetWindowLongW
    _set_long = getattr(_user32, "SetWindowLongPtrW", None) or _user32.SetWindowLongW

    _get_long.argtypes = [wintypes.HWND, ctypes.c_int]
    _get_long.restype = long_ptr
    _set_long.argtypes = [wintypes.HWND, ctypes.c_int, long_ptr]
    _set_long.restype = long_ptr

    _user32.SetWindowPos.argtypes = [
        wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
        ctypes.c_int, ctypes.c_int, wintypes.UINT]
    _user32.SetWindowPos.restype = wintypes.BOOL
    return True


def set_click_through(hwnd: int, enabled: bool) -> bool:
    """클릭 통과를 켜고 끈다. 성공하면 True.

    hwnd 는 매번 새로 읽은 int(widget.winId()) 여야 한다. Qt 는 플래그 변경이나
    reparent 때 네이티브 핸들을 파괴하고 다시 만들므로 캐시하면 안 된다.
    """
    if not _init():
        return False
    try:
        handle = wintypes.HWND(hwnd)
        ex = _get_long(handle, GWL_EXSTYLE)
        if enabled:
            new = ex | WS_EX_LAYERED | WS_EX_TRANSPARENT
        else:
            # WS_EX_LAYERED 는 절대 지우지 않는다. 투명 배경이 이것에 의존하므로
            # 지우면 위젯이 검게 변하거나 사라진다.
            new = ex & ~WS_EX_TRANSPARENT
        if new == ex:
            return True

        # SetWindowLongPtrW 의 반환 0 은 '이전 스타일이 0' 과 구분되지 않는다.
        # GetLastError 를 0 으로 밀어두고 나서 판정해야 한다.
        ctypes.set_last_error(0)
        if _set_long(handle, GWL_EXSTYLE, new) == 0 and ctypes.get_last_error() != 0:
            log.warning("SetWindowLong 실패 (err=%d)", ctypes.get_last_error())
            return False

        _user32.SetWindowPos(
            handle, None, 0, 0, 0, 0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED)
        return True
    except Exception:
        log.warning("클릭 통과 전환 실패", exc_info=True)
        return False


HWND_TOPMOST = -1


def raise_topmost(hwnd: int) -> bool:
    """항상-위 창들 사이에서 맨 앞으로 다시 올린다. 포커스는 건드리지 않는다.

    WS_EX_TOPMOST 는 '항상 위 창 무리'에 넣어 줄 뿐이다. 그 무리 안의 순서는 마지막으로
    활성화된 쪽이 앞이라, 작업표시줄을 누르거나 알림·다른 항상-위 앱이 뜨면 위젯이
    그 뒤로 밀리고 스스로는 돌아오지 않는다. 주기적으로 불러 되찾는다.
    """
    if not _init():
        return False
    try:
        return bool(_user32.SetWindowPos(
            wintypes.HWND(hwnd), wintypes.HWND(HWND_TOPMOST), 0, 0, 0, 0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE))
    except Exception:
        log.debug("맨 앞으로 올리기 실패", exc_info=True)
        return False


def get_ex_style(hwnd: int) -> int | None:
    """진단용. 현재 확장 스타일 비트를 돌려준다."""
    if not _init():
        return None
    try:
        return int(_get_long(wintypes.HWND(hwnd), GWL_EXSTYLE))
    except Exception:
        return None


WS_EX_NOACTIVATE = 0x08000000


def set_no_activate(hwnd: int, enabled: bool = True) -> bool:
    """WS_EX_NOACTIVATE 를 직접 건다.

    Qt 6.8 은 Qt.WindowDoesNotAcceptFocus 를 windowFlags() 에 보관만 하고
    Windows 의 WS_EX_NOACTIVATE 로 옮겨주지 않는다(확인함: exStyle=0x800a8).
    이게 없으면 이동 모드에서 위젯을 클릭해 드래그할 때 편집기가 포커스를 잃는다.
    """
    if not _init():
        return False
    try:
        handle = wintypes.HWND(hwnd)
        ex = _get_long(handle, GWL_EXSTYLE)
        new = (ex | WS_EX_NOACTIVATE) if enabled else (ex & ~WS_EX_NOACTIVATE)
        if new == ex:
            return True
        ctypes.set_last_error(0)
        if _set_long(handle, GWL_EXSTYLE, new) == 0 and ctypes.get_last_error() != 0:
            log.warning("WS_EX_NOACTIVATE 설정 실패 (err=%d)", ctypes.get_last_error())
            return False
        return True
    except Exception:
        log.warning("WS_EX_NOACTIVATE 설정 실패", exc_info=True)
        return False


# --- 자동 실행 ----------------------------------------------------------

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "WordWidget"


def _quoted(path) -> str:
    return '"' + str(path) + '"'


def autostart_command(pythonw: str, script: str | None = None) -> str:
    """콘솔 없는 pythonw.exe 로 실행한다. python.exe 를 쓰면 콘솔 창이 계속 떠 있다.

    PyInstaller 로 얼린 실행 파일이면 script 를 None 으로 준다. 그때 main.py 를
    뒤에 붙이면 실행 파일이 그걸 인자로 받아 argparse 가 죽는다.
    """
    if script is None:
        return _quoted(pythonw)
    return _quoted(pythonw) + " " + _quoted(script)


def is_autostart_enabled() -> bool:
    if not IS_WINDOWS:
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, RUN_VALUE)
        return True
    except FileNotFoundError:
        return False
    except OSError:
        log.warning("자동 실행 상태를 읽지 못했습니다", exc_info=True)
        return False


def set_autostart(enabled: bool, command: str | None = None) -> bool:
    if not IS_WINDOWS:
        return False
    import winreg
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            if enabled:
                if not command:
                    return False
                winreg.SetValueEx(key, RUN_VALUE, 0, winreg.REG_SZ, command)
                log.info("자동 실행 등록: %s", command)
            else:
                try:
                    winreg.DeleteValue(key, RUN_VALUE)
                    log.info("자동 실행 해제")
                except FileNotFoundError:
                    pass
        return True
    except OSError:
        log.warning("자동 실행 설정 실패", exc_info=True)
        return False
