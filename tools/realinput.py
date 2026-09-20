"""SendInput 으로 진짜 마우스 입력을 만든다.

Qt 이벤트를 위젯에 직접 주입하는 테스트는 OS 의 클릭 판정과 Qt 의 이벤트 전달을
모두 건너뛴다. 그래서 '점선은 보이는데 드래그가 안 되는' 버그를 통과시켜 버렸다.
창 동작을 믿으려면 실제 입력으로 확인해야 한다.
"""
from __future__ import annotations

import ctypes
import time
from ctypes import wintypes

_u32 = ctypes.WinDLL("user32", use_last_error=True)

MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_VIRTUALDESK = 0x4000
MOUSEEVENTF_ABSOLUTE = 0x8000

SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN = 76, 77
SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN = 78, 79


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]


class INPUT(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [("mi", MOUSEINPUT)]
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _U)]


def _send(flags: int, x: int = 0, y: int = 0) -> None:
    vx = _u32.GetSystemMetrics(SM_XVIRTUALSCREEN)
    vy = _u32.GetSystemMetrics(SM_YVIRTUALSCREEN)
    vw = _u32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
    vh = _u32.GetSystemMetrics(SM_CYVIRTUALSCREEN)
    # 절대 좌표는 가상 데스크톱 전체를 0..65535 로 정규화한 값이다.
    nx = int((x - vx) * 65535 / max(1, vw - 1))
    ny = int((y - vy) * 65535 / max(1, vh - 1))
    inp = INPUT(type=0)
    inp.mi = MOUSEINPUT(nx, ny, 0, flags | MOUSEEVENTF_VIRTUALDESK, 0, None)
    _u32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


def cursor_pos() -> tuple[int, int]:
    pt = wintypes.POINT()
    _u32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


def restore_cursor(pos: tuple[int, int]) -> None:
    _u32.SetCursorPos(pos[0], pos[1])


def move(x: int, y: int) -> None:
    """커서를 옮긴다. SetCursorPos 가 아니라 SendInput 을 쓰는 이유는,
    SetCursorPos 는 마우스 이동 이벤트를 만들지 않아 호버 판정이 안 걸리기 때문이다."""
    _send(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE, x, y)


def drag(start: tuple[int, int], end: tuple[int, int], pump, steps: int = 6) -> None:
    """start 에서 눌러 end 까지 끌고 놓는다. pump 는 매 단계 이벤트 루프를 돌린다."""
    sx, sy = start
    ex, ey = end
    _send(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE, sx, sy)
    time.sleep(0.12)
    pump()
    _send(MOUSEEVENTF_LEFTDOWN)
    time.sleep(0.12)
    pump()
    for i in range(1, steps + 1):
        _send(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE,
              sx + (ex - sx) * i // steps, sy + (ey - sy) * i // steps)
        time.sleep(0.05)
        pump()
    _send(MOUSEEVENTF_LEFTUP)
    time.sleep(0.15)
    pump()


def window_at(x: int, y: int) -> int:
    _u32.WindowFromPoint.argtypes = [wintypes.POINT]
    _u32.WindowFromPoint.restype = wintypes.HWND
    return int(_u32.WindowFromPoint(wintypes.POINT(x, y)) or 0)
