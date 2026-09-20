"""OS 의 바탕화면 아이콘 라벨 글꼴 크기를 읽는다.

위젯 글자 크기의 상한(= 아이콘 글꼴의 2배)을 정하는 데 쓴다. Qt 를 import 하지 않으므로
QApplication 생성 전에도 호출할 수 있고, config.py 를 순수 모듈로 유지시켜 준다.
"""
from __future__ import annotations

import ctypes
import logging
import sys
from ctypes import wintypes

log = logging.getLogger(__name__)

WINDOWS_DEFAULT_PT = 9.0   # Segoe UI 9pt — Windows 10 기본값
MACOS_DEFAULT_PT = 12.0    # Finder 아이콘 라벨 기본값
OTHER_DEFAULT_PT = 9.0

# 신뢰 구간. 이 밖의 값이 나오면 무언가 잘못된 것이므로 기본값으로 되돌린다.
SANE_RANGE = (6.0, 24.0)

LF_FACESIZE = 32
SPI_GETICONTITLELOGFONT = 0x001F
LOGPIXELSY = 90


class LOGFONTW(ctypes.Structure):
    _fields_ = [
        ("lfHeight", wintypes.LONG), ("lfWidth", wintypes.LONG),
        ("lfEscapement", wintypes.LONG), ("lfOrientation", wintypes.LONG),
        ("lfWeight", wintypes.LONG),
        ("lfItalic", wintypes.BYTE), ("lfUnderline", wintypes.BYTE),
        ("lfStrikeOut", wintypes.BYTE), ("lfCharSet", wintypes.BYTE),
        ("lfOutPrecision", wintypes.BYTE), ("lfClipPrecision", wintypes.BYTE),
        ("lfQuality", wintypes.BYTE), ("lfPitchAndFamily", wintypes.BYTE),
        ("lfFaceName", wintypes.WCHAR * LF_FACESIZE),
    ]


def _windows_icon_font_pt(default: float) -> float:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    user32.SystemParametersInfoW.argtypes = [
        wintypes.UINT, wintypes.UINT, ctypes.c_void_p, wintypes.UINT]
    user32.SystemParametersInfoW.restype = wintypes.BOOL
    gdi32.GetDeviceCaps.argtypes = [wintypes.HDC, ctypes.c_int]
    gdi32.GetDeviceCaps.restype = ctypes.c_int

    lf = LOGFONTW()
    if not user32.SystemParametersInfoW(
            SPI_GETICONTITLELOGFONT, ctypes.sizeof(lf), ctypes.byref(lf), 0):
        return default

    hdc = user32.GetDC(None)
    try:
        dpi_y = gdi32.GetDeviceCaps(hdc, LOGPIXELSY) or 96
    finally:
        # 화면 DC 를 놓치면 재시작마다 GDI 핸들이 샌다.
        user32.ReleaseDC(None, hdc)

    # lfHeight 가 음수면 '문자 높이' 지정이라는 뜻이고, 그게 일반적인 경우다.
    return abs(lf.lfHeight) * 72.0 / float(dpi_y)


def desktop_icon_font_pt() -> float:
    """바탕화면 아이콘 라벨의 글꼴 크기(pt). 어떤 경우에도 예외를 던지지 않는다."""
    if sys.platform == "darwin":
        return MACOS_DEFAULT_PT
    if sys.platform != "win32":
        return OTHER_DEFAULT_PT

    try:
        pt = _windows_icon_font_pt(WINDOWS_DEFAULT_PT)
    except Exception:
        log.warning("아이콘 글꼴 크기를 읽지 못했습니다. 기본값 사용", exc_info=True)
        return WINDOWS_DEFAULT_PT

    lo, hi = SANE_RANGE
    if not (lo <= pt <= hi):
        log.warning("아이콘 글꼴 크기 %.1fpt 가 비정상 범위 → %.1fpt 사용", pt, WINDOWS_DEFAULT_PT)
        return WINDOWS_DEFAULT_PT
    return pt


def max_font_pt() -> float:
    """위젯 글자 크기의 상한. 사용자가 정한 규칙: 아이콘 라벨 글꼴의 2배."""
    return desktop_icon_font_pt() * 2.0


if __name__ == "__main__":
    print(f"아이콘 라벨 글꼴: {desktop_icon_font_pt():.1f}pt")
    print(f"위젯 글자 상한:   {max_font_pt():.1f}pt")
