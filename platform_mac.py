"""macOS 전용 처리.

자동 실행은 ~/Library/LaunchAgents 에 plist 를 둔다. 로그인할 때 launchd 가 읽어서
앱을 띄운다. 지금 바로 launchctl 로 올리지 않는 이유는, 이미 떠 있는 위젯 옆에
하나가 더 뜨려다 단일 실행 검사에 걸려 조용히 꺼지는 일만 생기기 때문이다.
"""
from __future__ import annotations

import logging
import plistlib
import shutil
import sys
from pathlib import Path

log = logging.getLogger(__name__)

IS_MAC = sys.platform == "darwin"

LABEL = "io.github.newjeans4sale.word-widget"
AGENT_PATH = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
DATA_DIR = Path.home() / "Library" / "Application Support" / "word-widget"


# --- 자동 실행 ----------------------------------------------------------

def autostart_command(executable, script=None) -> list[str]:
    """얼린 앱이면 script 를 None 으로 준다. 실행 파일 자체가 앱이다."""
    if script is None:
        return [str(executable)]
    return [str(executable), str(script)]


def is_autostart_enabled() -> bool:
    return AGENT_PATH.exists()


def set_autostart(enabled: bool, command: list[str] | None = None) -> bool:
    try:
        if enabled:
            if not command:
                return False
            AGENT_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(AGENT_PATH, "wb") as f:
                plistlib.dump({
                    "Label": LABEL,
                    "ProgramArguments": list(command),
                    "RunAtLoad": True,
                    "ProcessType": "Interactive",
                }, f)
            log.info("자동 실행 등록: %s", command)
        else:
            AGENT_PATH.unlink(missing_ok=True)
            log.info("자동 실행 해제")
        return True
    except OSError:
        log.warning("자동 실행 설정 실패", exc_info=True)
        return False


# --- 창 처리 ------------------------------------------------------------
#
# Windows 판이 platform_win 으로 하는 일을 macOS 에서 똑같이 한다.
#   - 포커스를 뺏지 않는다 (WS_EX_NOACTIVATE 에 해당)
#   - 클릭 통과를 켜고 끈다 (WS_EX_TRANSPARENT 에 해당)
#   - 다른 항상-위 창에 밀리면 다시 맨 위로 올린다 (HWND_TOPMOST 에 해당)
# 그리고 Windows 에서는 저절로 되는 것 하나를 더 해야 한다:
#   - 데스크탑(스페이스)을 바꿔도, 전체화면 앱 위에서도 같은 창이 보인다.
#     macOS 는 창을 처음 뜬 스페이스에 묶어 두기 때문이다.

NS_NONACTIVATING_PANEL = 1 << 7
NS_JOIN_ALL_SPACES = 1 << 0
NS_MOVE_TO_ACTIVE_SPACE = 1 << 1
NS_STATIONARY = 1 << 4
NS_IGNORES_CYCLE = 1 << 6
NS_FULLSCREEN_AUXILIARY = 1 << 8


def _nswindow(win_id: int):
    """Qt 의 winId() 는 macOS 에서 NSView 포인터다. 그 창을 돌려준다."""
    if not IS_MAC or not win_id:
        return None
    try:
        import objc
        return objc.objc_object(c_void_p=win_id).window()
    except Exception:
        log.debug("NSWindow 를 얻지 못했습니다", exc_info=True)
        return None


def setup_overlay(win_id: int) -> bool:
    """네이티브 창이 생길 때마다 부른다. Qt 가 창을 다시 만들면 설정도 사라진다."""
    w = _nswindow(win_id)
    if w is None:
        return False
    try:
        # Qt 는 '지금 보는 스페이스로 따라오기'를 켜 두는데, '모든 스페이스'와 함께 켜면
        # AppKit 이 예외를 던진다. 그것을 끄고 건다.
        behavior = w.collectionBehavior() & ~NS_MOVE_TO_ACTIVE_SPACE
        w.setCollectionBehavior_(behavior | NS_JOIN_ALL_SPACES | NS_STATIONARY
                                 | NS_IGNORES_CYCLE | NS_FULLSCREEN_AUXILIARY)
        w.setHidesOnDeactivate_(False)
        # 눌러도 앱이 앞으로 나오지 않게 한다. 그래야 편집기의 타이핑이 끊기지 않는다.
        # 패널을 만든 뒤에 이 비트를 켜면 창 서버에 전달되지 않는 AppKit 버그가 있어
        # 같은 일을 하는 내부 메서드도 함께 부른다.
        w.setStyleMask_(w.styleMask() | NS_NONACTIVATING_PANEL)
        if w.respondsToSelector_(b"_setPreventsActivation:"):
            w._setPreventsActivation_(True)
        return True
    except Exception:
        log.warning("창 설정 실패", exc_info=True)
        return False


def set_click_through(win_id: int, enabled: bool) -> bool:
    w = _nswindow(win_id)
    if w is None:
        return False
    w.setIgnoresMouseEvents_(bool(enabled))
    return True


def raise_topmost(win_id: int) -> bool:
    w = _nswindow(win_id)
    if w is None:
        return False
    w.orderFrontRegardless()
    return True


def is_foreground_fullscreen() -> bool:
    """맨 앞 앱의 창이 화면 하나를 가득 채우고 있으면 True.

    Windows 판과 같은 판정이다. 바탕화면은 일반 창 층(0)에 있지 않으므로 빠진다.
    """
    if not IS_MAC:
        return False
    try:
        import os

        import Quartz
        from AppKit import NSScreen, NSWorkspace

        front = NSWorkspace.sharedWorkspace().frontmostApplication()
        if front is None or front.processIdentifier() == os.getpid():
            return False
        pid = front.processIdentifier()

        # NSScreen 은 왼쪽 아래가 원점이고 창 목록은 왼쪽 위가 원점이다. 맞춰 준다.
        screens = NSScreen.screens()
        primary_h = screens[0].frame().size.height
        rects = []
        for s in screens:
            f = s.frame()
            top = primary_h - (f.origin.y + f.size.height)
            rects.append((f.origin.x, top, f.origin.x + f.size.width, top + f.size.height))

        windows = Quartz.CGWindowListCopyWindowInfo(
            Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements,
            Quartz.kCGNullWindowID) or []
        for w in windows:
            if w.get("kCGWindowOwnerPID") != pid or w.get("kCGWindowLayer") != 0:
                continue
            b = w.get("kCGWindowBounds") or {}
            left, top = b.get("X", 0), b.get("Y", 0)
            right, bottom = left + b.get("Width", 0), top + b.get("Height", 0)
            for sl, st, sr, sb in rects:
                if left <= sl and top <= st and right >= sr and bottom >= sb:
                    return True
        return False
    except Exception:
        log.debug("전체화면 감지 실패", exc_info=True)
        return False


# --- 앱 데이터 폴더 -------------------------------------------------------

def prepare_data_dir(seed: Path) -> Path:
    """얼린 .app 이 쓸 폴더를 만들고 처음 한 번 기본 파일을 채운다.

    .app 안에 설정을 쓰면 서명이 깨지고, 앱을 새로 깔 때 단어장이 날아간다.
    그래서 단어장, 설정, 캐릭터를 사용자 폴더로 꺼내 두고 거기서 읽는다.
    이미 있는 파일은 건드리지 않는다 - 사용자가 고친 것이다.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    for name in ("words.txt", "config.json", "README.md"):
        src, dst = seed / name, DATA_DIR / name
        if src.exists() and not dst.exists():
            shutil.copy2(src, dst)
    sprites = seed / "sprites"
    if sprites.is_dir():
        (DATA_DIR / "sprites").mkdir(exist_ok=True)
        for char in sprites.iterdir():
            dst = DATA_DIR / "sprites" / char.name
            if char.is_dir() and not dst.exists():
                shutil.copytree(char, dst)
    return DATA_DIR
