r"""GUI 동작 검증. 단위 테스트로는 잡을 수 없는 창 동작을 실제로 띄워서 확인한다.

    .venv\Scripts\python.exe tools\verify_gui.py [캡처.png]

Qt 레이어는 pytest 로 테스트할 수 없어서(QApplication 없이 QWidget 을 만들면
프로세스가 죽는다) 이 스크립트가 그 역할을 대신한다.
"""
from __future__ import annotations

import ctypes
import random
import sys
import tempfile
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import Qt, QTimer                       # noqa: E402
from PySide6.QtGui import QGuiApplication                   # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget         # noqa: E402

import config as cfgmod                                     # noqa: E402
import fullscreen                                           # noqa: E402
from overlay import WordOverlay                             # noqa: E402
from wordsource import GUIDE_TEXT, WordSource               # noqa: E402
import realinput                                            # noqa: E402

EX_STYLES = {
    "WS_EX_TRANSPARENT": 0x00000020,
    "WS_EX_LAYERED":     0x00080000,
    "WS_EX_TOOLWINDOW":  0x00000080,
    "WS_EX_NOACTIVATE":  0x08000000,
    "WS_EX_TOPMOST":     0x00000008,
}
GWL_EXSTYLE = -20

_u32 = ctypes.WinDLL("user32", use_last_error=True)
_u32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
_u32.GetWindowLongPtrW.restype = ctypes.c_longlong
_u32.GetForegroundWindow.restype = wintypes.HWND


def ex_style(hwnd: int) -> int:
    return int(_u32.GetWindowLongPtrW(wintypes.HWND(hwnd), GWL_EXSTYLE))


def foreground() -> int:
    return int(_u32.GetForegroundWindow() or 0)


class Verifier:
    """단계를 인스턴스 속성으로 들고 간다.

    전역 변수로 창을 들고 다니면 global 선언을 하나만 빠뜨려도 슬롯 안에서
    NameError 가 나고, Qt 가 그 예외를 삼켜 프로세스가 영영 멈춘다.
    """

    def __init__(self, app, shot_path: Path | None):
        self.app = app
        self.shot_path = shot_path
        self.failures: list[str] = []
        self.overlay: WordOverlay | None = None
        self.probe: QWidget | None = None
        self.base_geo = None

    def check(self, label: str, ok: bool) -> bool:
        print(("  OK    " if ok else "  FAIL  ") + label)
        if not ok:
            self.failures.append(label)
        return ok

    def section(self, title: str) -> None:
        print(title)

    # --- 1. 창 스타일과 포커스 -------------------------------------------

    def step_window(self) -> None:
        self.section("[1] 창 스타일 - 클릭 통과 상태")
        fg_before = foreground()
        cfg = cfgmod.Config()
        self.overlay = WordOverlay(cfg)
        self.overlay.set_word("vocabulary")
        self.overlay.show()
        self.app.processEvents()

        ex = ex_style(int(self.overlay.winId()))
        self.check("WS_EX_TRANSPARENT - 클릭이 뒤쪽 창으로 통과", bool(ex & EX_STYLES["WS_EX_TRANSPARENT"]))
        self.check("WS_EX_LAYERED     - 투명 배경 동작", bool(ex & EX_STYLES["WS_EX_LAYERED"]))
        self.check("WS_EX_TOOLWINDOW  - 작업표시줄/Alt+Tab 제외", bool(ex & EX_STYLES["WS_EX_TOOLWINDOW"]))
        self.check("WS_EX_NOACTIVATE  - 클릭해도 포커스 안 뺏음", bool(ex & EX_STYLES["WS_EX_NOACTIVATE"]))
        self.check("WS_EX_TOPMOST     - 항상 위", bool(ex & EX_STYLES["WS_EX_TOPMOST"]))
        self.check("show() 후에도 활성 창이 그대로", foreground() == fg_before)

        self.base_geo = self.overlay.geometry()
        g = self.base_geo
        print(f"        geometry = ({g.x()},{g.y()}) {g.width()}x{g.height()}")
        self.check("작은 위젯이다 (40~400 x 10~60)",
                   40 <= g.width() <= 400 and 10 <= g.height() <= 60)

    # --- 2. 이동 모드 -----------------------------------------------------

    def step_move_mode(self) -> None:
        self.section("[2] 이동 모드 - 클릭 통과 토글")
        o = self.overlay
        o.set_move_mode(True)
        self.app.processEvents()
        ex = ex_style(int(o.winId()))
        self.check("ON  -> WS_EX_TRANSPARENT 해제", not (ex & EX_STYLES["WS_EX_TRANSPARENT"]))
        self.check("ON  -> WS_EX_LAYERED 유지 (지우면 검게 변함)",
                   bool(ex & EX_STYLES["WS_EX_LAYERED"]))
        self.check("ON  -> 위치 불변", o.geometry() == self.base_geo)

        o.set_move_mode(False)
        self.app.processEvents()
        ex = ex_style(int(o.winId()))
        self.check("OFF -> WS_EX_TRANSPARENT 복귀", bool(ex & EX_STYLES["WS_EX_TRANSPARENT"]))
        self.check("OFF -> 위치 불변", o.geometry() == self.base_geo)

    # --- 3. 앵커 ----------------------------------------------------------

    def step_anchor(self) -> None:
        self.section("[3] 앵커 - 단어 길이가 변해도 우하단이 고정되는가")
        o = self.overlay
        anchor_x, anchor_y, _ = o.anchor_state
        drift = []
        for word in ["cumulative", "an", "I", "internationalization", "ok"]:
            o.set_word(word)
            self.app.processEvents()
            g = o.geometry()
            right, bottom = g.x() + g.width(), g.y() + g.height()
            if (right, bottom) != (anchor_x, anchor_y):
                drift.append(f"{word}({right},{bottom})")
        # 폭 12px 짜리 단어가 MIN_VISIBLE 판정에 걸려 튕겨나가던 버그의 회귀 테스트다.
        self.check("짧은 단어에도 앵커가 고정된다", not drift)
        if drift:
            print("        어긋남:", ", ".join(drift))

    # --- 3b. 실제 마우스 드래그 ---------------------------------------------

    def step_real_drag(self) -> None:
        """진짜 마우스 입력으로 확인한다.

        Qt 이벤트를 위젯에 직접 주입하는 방식은 OS 클릭 판정과 Qt 의 이벤트 전달을
        둘 다 건너뛴다. 실제로 '점선은 보이는데 드래그가 안 되는' 버그를 그 방식이
        통과시킨 적이 있다(원인: Qt windowFlags 의 WindowTransparentForInput 이
        네이티브 스타일만 바꿨을 때 그대로 남아 있었다). 반드시 실제 입력으로 본다.
        """
        self.section("[3b] 실제 마우스 드래그 (커서가 잠시 움직입니다)")
        o = self.overlay
        saved = realinput.cursor_pos()
        try:
            o.set_word("dragtest")
            self.app.processEvents()

            # 글자 획이 아니라 일부러 여백을 잡는다. 투명 픽셀에서도 잡혀야 한다.
            def grab_point():
                g = o.geometry()
                return g.x() + 5, g.y() + 4

            self.check("이동 모드 OFF 에서 클릭은 창을 잡지 않는다",
                       self._drag_moves(grab_point, (-120, -80)) is False)

            o.set_move_mode(True)
            self.app.processEvents()
            g = o.geometry()
            hwnd_at = realinput.window_at(g.x() + 5, g.y() + 4)
            self.check("OS 가 그 지점을 위젯으로 판정한다", hwnd_at == int(o.winId()))
            self.check("이동 모드 ON 에서 여백을 잡고 드래그하면 움직인다",
                       self._drag_moves(grab_point, (-200, -120)) is True)

            o.set_move_mode(False)
            self.app.processEvents()
            self.check("이동 모드 OFF 로 돌아오면 다시 안 움직인다",
                       self._drag_moves(grab_point, (-120, -80)) is False)
            ex = ex_style(int(o.winId()))
            self.check("OFF 복귀 후 WS_EX_TRANSPARENT 재적용",
                       bool(ex & EX_STYLES["WS_EX_TRANSPARENT"]))
            self.check("OFF 복귀 후 WS_EX_NOACTIVATE 유지 (핸들 재생성돼도)",
                       bool(ex & EX_STYLES["WS_EX_NOACTIVATE"]))
        finally:
            realinput.restore_cursor(saved)
        self.base_geo = self.overlay.geometry()

    def _drag_moves(self, grab_point, delta) -> bool:
        o = self.overlay
        before = o.geometry()
        sx, sy = grab_point()
        realinput.drag((sx, sy), (sx + delta[0], sy + delta[1]), self.app.processEvents)
        return o.geometry().topLeft() != before.topLeft()

    # --- 4. 다중 모니터 ----------------------------------------------------

    def step_monitors(self) -> None:
        self.section("[4] 모니터 배치")
        screens = QGuiApplication.screens()
        for s in screens:
            g = s.geometry()
            print(f"        {s.name()}  ({g.x()},{g.y()}) {g.width()}x{g.height()}")
        leftmost = min(screens, key=lambda s: s.geometry().x())
        if leftmost.geometry().x() >= 0:
            print("        (음수 좌표 모니터가 없어 건너뜀)")
            return

        avail = leftmost.availableGeometry()
        cfg = cfgmod.Config()
        cfg.anchor_x = avail.right() + 1 - 24
        cfg.anchor_y = avail.bottom() + 1 - 24
        probe = WordOverlay(cfg)
        probe.set_word("cumulative")
        probe.show()
        self.app.processEvents()
        g = probe.geometry()
        print(f"        저장 앵커 ({cfg.anchor_x},{cfg.anchor_y}) -> 실제 ({g.x()},{g.y()})")
        # x = max(0, x) 같은 검증을 넣으면 여기서 위젯이 주 모니터로 순간이동한다.
        self.check("음수 x 모니터에 그대로 배치된다", g.x() < 0)
        self.check("우하단 앵커 유지", g.x() + g.width() == cfg.anchor_x)
        probe.close()

    # --- 5. 단어 목록 예외 --------------------------------------------------

    def step_wordlist(self) -> None:
        self.section("[5] 비거나 없는 단어 목록")
        d = Path(tempfile.mkdtemp())
        empty = d / "words.txt"
        empty.write_text("", encoding="utf-8")
        self.check("빈 파일 -> 안내 문구, 죽지 않음",
                   WordSource.from_file(empty, rng=random.Random(0)).next() == GUIDE_TEXT)
        self.check("없는 파일 -> 안내 문구, 죽지 않음",
                   WordSource.from_file(d / "nope.txt", rng=random.Random(0)).next() == GUIDE_TEXT)

    # --- 6. 전체화면 --------------------------------------------------------

    def step_fullscreen_start(self) -> None:
        self.section("[6] 전체화면 감지")
        self.check("평상시에는 전체화면 아님", fullscreen.is_foreground_fullscreen() is False)
        self.probe = QWidget()
        self.probe.setWindowTitle("maximized probe")
        self.probe.showMaximized()
        self.probe.raise_()
        self.probe.activateWindow()
        self._await_foreground(int(self.probe.winId()), self._after_maximized)

    def _after_maximized(self, became_foreground: bool) -> None:
        if became_foreground:
            # 최대화를 전체화면으로 오판하면 창을 키울 때마다 위젯이 사라진다.
            self.check("최대화 창은 전체화면이 아니다",
                       fullscreen.is_foreground_fullscreen() is False)
        else:
            print("        (최대화 창이 전경이 되지 않아 건너뜀)")
        self.probe.close()
        self.probe = QWidget()
        self.probe.setWindowTitle("fullscreen probe")
        self.probe.showFullScreen()
        self.probe.raise_()
        self.probe.activateWindow()
        self._await_foreground(int(self.probe.winId()), self._after_fullscreen)

    def _after_fullscreen(self, became_foreground: bool) -> None:
        if became_foreground:
            self.check("전체화면 창을 감지한다", fullscreen.is_foreground_fullscreen() is True)
        else:
            self.check("전체화면 창이 전경이 되었다 (판정 전제)", False)
        self.probe.close()
        self.probe = None
        QTimer.singleShot(600, self.step_capture)

    def _await_foreground(self, hwnd: int, done, tries: int = 0) -> None:
        """전경 전환은 OS 가 지연시킨다. 실제로 전경이 될 때까지 기다린 뒤 판정한다."""
        self.app.processEvents()
        if foreground() == hwnd:
            done(True)
        elif tries >= 15:
            done(False)
        else:
            QTimer.singleShot(200, lambda: self._await_foreground(hwnd, done, tries + 1))

    # --- 7. 렌더링 캡처 -----------------------------------------------------

    def step_capture(self) -> None:
        self.section("[7] 렌더링")
        o = self.overlay
        o.set_word("vocabulary")
        o.show()
        self.app.processEvents()
        QTimer.singleShot(500, self._grab)

    def _grab(self) -> None:
        if self.shot_path is None:
            print("        (캡처 경로가 없어 건너뜀)")
            return self.finish()
        o = self.overlay
        g = o.geometry()
        screen = QGuiApplication.screenAt(g.center()) or QGuiApplication.primaryScreen()
        origin = screen.geometry()
        m = 20
        shot = screen.grabWindow(0, g.x() - origin.x() - m, g.y() - origin.y() - m,
                                 g.width() + 2 * m, g.height() + 2 * m)
        scaled = shot.scaled(shot.width() * 3, shot.height() * 3,
                             Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
        self.check(f"화면 캡처 저장 -> {self.shot_path}", scaled.save(str(self.shot_path)))
        self.finish()

    # --- 진행 --------------------------------------------------------------

    def run(self) -> None:
        self.step_window()
        self.step_move_mode()
        self.step_anchor()
        self.step_real_drag()
        self.step_monitors()
        self.step_wordlist()
        self.step_fullscreen_start()   # 비동기로 이어진다

    def finish(self) -> None:
        print()
        if self.failures:
            print(f"=== 실패 {len(self.failures)}건 ===")
            for f in self.failures:
                print("   -", f)
        else:
            print("=== 전부 통과 ===")
        self.app.exit(1 if self.failures else 0)


def main() -> int:
    shot = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    verifier = Verifier(app, shot)
    QTimer.singleShot(400, verifier.run)
    # 어떤 단계가 멈춰도 프로세스가 영영 남지 않게 한다.
    QTimer.singleShot(60000, lambda: (print("시간 초과"), app.exit(2)))
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
