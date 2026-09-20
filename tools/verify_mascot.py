r"""마스코트 오버레이 검증. 실제로 창을 띄워 눈과 OS 로 확인한다.

    .venv\Scripts\python.exe tools\verify_mascot.py [캡처.png]

여기서 보는 것은 단위 테스트가 닿지 못하는 것들이다 — 네이티브 창 스타일,
**투명한 여백에서 클릭이 정말 통과하는지**, 실제 마우스로 캐릭터를 잡을 수 있는지,
놓으면 작업표시줄 위에 정확히 서는지.

클릭 판정은 Qt 이벤트를 주입해서 확인하면 안 된다. OS 의 판정과 Qt 의 전달을
둘 다 건너뛰기 때문이다 (verify_gui.py 의 [3b] 에 같은 이야기가 있다).
"""
from __future__ import annotations

import ctypes
import shutil
import sys
import tempfile
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from PySide6.QtCore import QPoint, Qt, QTimer                 # noqa: E402
from PySide6.QtGui import QGuiApplication                     # noqa: E402
from PySide6.QtWidgets import QApplication                    # noqa: E402

import config as cfgmod                                       # noqa: E402
import mascot_overlay                                         # noqa: E402
import realinput                                              # noqa: E402
from mascot_overlay import MascotOverlay                       # noqa: E402

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
    def __init__(self, app, shot_path: Path | None):
        self.app = app
        self.shot_path = shot_path
        self.failures: list[str] = []
        self.overlay: MascotOverlay | None = None

    def check(self, label: str, ok: bool) -> bool:
        print(("  OK    " if ok else "  FAIL  ") + label)
        if not ok:
            self.failures.append(label)
        return ok

    def pump(self, ms: int = 0) -> None:
        """이벤트를 돌린다. ms 를 주면 그동안 애니메이션 타이머가 돌게 둔다."""
        if ms <= 0:
            self.app.processEvents()
            return
        loop = QTimer()
        loop.setSingleShot(True)
        done = []
        loop.timeout.connect(lambda: done.append(True))
        loop.start(ms)
        while not done:
            self.app.processEvents()

    # --- 1. 캐릭터가 준비되어 있는가 --------------------------------------

    def step_characters(self) -> None:
        print("[1] 캐릭터")
        names = mascot_overlay.available(ROOT / "sprites")
        print("        " + (", ".join(names) or "(없음)"))
        if not self.check("쓸 수 있는 캐릭터가 하나 이상 있다", bool(names)):
            return self.finish()

        cfg = cfgmod.Config()
        self.overlay = MascotOverlay(cfg, ROOT / "sprites")
        self.overlay.set_word("ephemeral", "덧없는, 단명하는")
        fg_before = foreground()
        self.overlay.show()
        self.pump(300)
        self.check("show() 후에도 활성 창이 그대로", foreground() == fg_before)

    # --- 2. 창 스타일 -----------------------------------------------------

    def step_window(self) -> None:
        print("[2] 창 스타일")
        o = self.overlay
        ex = ex_style(int(o.winId()))
        self.check("WS_EX_LAYERED     - 투명 배경 + 픽셀 알파 클릭 판정",
                   bool(ex & EX_STYLES["WS_EX_LAYERED"]))
        self.check("WS_EX_TOOLWINDOW  - 작업표시줄/Alt+Tab 제외",
                   bool(ex & EX_STYLES["WS_EX_TOOLWINDOW"]))
        self.check("WS_EX_NOACTIVATE  - 잡아도 포커스 안 뺏음",
                   bool(ex & EX_STYLES["WS_EX_NOACTIVATE"]))
        self.check("WS_EX_TOPMOST     - 항상 위", bool(ex & EX_STYLES["WS_EX_TOPMOST"]))
        # 텍스트 모드와 정반대다. 몸통은 클릭을 받아야 잡을 수 있다.
        self.check("WS_EX_TRANSPARENT 없음 - 몸통이 클릭을 받는다",
                   not (ex & EX_STYLES["WS_EX_TRANSPARENT"]))

        g = o.geometry()
        print(f"        geometry = ({g.x()},{g.y()}) {g.width()}x{g.height()}")
        print(f"        body     = {o._body.width()}x{o._body.height()}")

    # --- 3. 투명 여백이 정말 통과하는가 ------------------------------------

    def step_hit_test(self) -> None:
        """setMask() 를 쓰지 않는 근거를 실제로 확인한다.

        투명 배경 창은 Windows 가 픽셀 알파로 판정하므로 캐릭터가 없는 구석은
        통과해야 한다. 이게 깨지면 마스크를 다시 도입해야 한다.
        """
        print("[3] 클릭 판정 (알파 기반)")
        o = self.overlay
        o.set_wander(False)         # 판정하는 동안 걸어나가지 않게
        self.pump(120)

        hwnd = int(o.winId())
        body = o._body
        center = o.mapToGlobal(body.center())
        self.check("몸통 중앙은 이 창으로 판정된다",
                   realinput.window_at(center.x(), center.y()) == hwnd)

        # 말풍선과 몸통 사이의 빈 구석. 창 안이지만 그려진 것이 없다.
        g = o.geometry()
        corner = QPoint(g.x() + 1, g.y() + g.height() - 1)
        at_corner = realinput.window_at(corner.x(), corner.y())
        self.check("투명한 구석은 통과한다 (다른 창이 잡힌다)", at_corner != hwnd)
        if at_corner == hwnd:
            print("        -> 알파 판정이 안 먹는다. setMask() 도입을 검토할 것")

    # --- 4. 실제 마우스로 잡아 끌기 ----------------------------------------

    def step_drag(self) -> None:
        print("[4] 실제 마우스 드래그 (커서가 잠시 움직입니다)")
        o = self.overlay
        saved = realinput.cursor_pos()
        try:
            before = o.position
            center = o.mapToGlobal(o._body.center())
            target = (center.x() - 220, center.y() - 160)
            print(f"        잡는 지점 ({center.x()},{center.y()})  ->  {target}")
            realinput.drag((center.x(), center.y()), target, self.app.processEvents)
            self.pump(120)
            after = o.position
            print(f"        발밑 {before} -> {after}  (동작 {self.mascot_action(o)})")
            self.check("몸통을 잡고 끌면 따라온다", abs(after[0] - before[0]) > 100)

            floor = self._floor_for(o)
            self.check("놓으면 떨어진다 (FALL 상태)", o.mascot.action in ("fall", "idle"))
            self.pump(1500)
            self.check(f"작업표시줄 위에 선다 (y == {floor})", o.position[1] == floor)
        finally:
            realinput.restore_cursor(saved)

    @staticmethod
    def mascot_action(o) -> str:
        return o.mascot.action

    def _floor_for(self, o) -> int:
        probe = QPoint(int(o.position[0]), int(o.position[1]) - 1)
        screen = QGuiApplication.screenAt(probe) or QGuiApplication.primaryScreen()
        return screen.availableGeometry().bottom() + 1

    # --- 5. 걷기 ----------------------------------------------------------

    def step_walk(self) -> None:
        print("[5] 걷기")
        o = self.overlay
        o.set_wander(True)
        o.mascot._begin("walk")
        start = o.position[0]
        self.pump(1500)
        self.check("산책을 켜면 가로로 움직인다", abs(o.position[0] - start) > 10)

        o.set_wander(False)
        self.pump(200)
        held = o.position[0]
        self.pump(1500)
        self.check("산책을 끄면 그 자리에 선다", o.position[0] == held)

    # --- 6. 캐릭터 교체 -----------------------------------------------------

    def step_switch(self) -> None:
        print("[6] 캐릭터 교체")
        o = self.overlay
        names = mascot_overlay.available(ROOT / "sprites")
        if len(names) < 2:
            print("        (캐릭터가 하나뿐이라 건너뜀)")
            return
        first = o.character
        other = next(n for n in names if n != first)
        self.check(f"{first} -> {other}", o.set_character(other) and o.character == other)
        self.pump(200)
        self.check("바꾼 뒤에도 바닥에 서 있다", o.position[1] == self._floor_for(o))
        o.set_character(first)
        self.pump(200)

    # --- 7. 캡처 ------------------------------------------------------------

    def step_capture(self) -> None:
        print("[7] 렌더링")
        o = self.overlay
        o.set_word("ephemeral", "덧없는, 단명하는")
        o.set_meaning_visible(True)
        self.pump(400)
        if self.shot_path is None:
            print("        (캡처 경로가 없어 건너뜀)")
            return
        g = o.geometry()
        screen = QGuiApplication.screenAt(g.center()) or QGuiApplication.primaryScreen()
        origin = screen.geometry()
        m = 16
        shot = screen.grabWindow(0, g.x() - origin.x() - m, g.y() - origin.y() - m,
                                 g.width() + 2 * m, g.height() + 2 * m)
        scaled = shot.scaled(shot.width() * 2, shot.height() * 2,
                             Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
        self.check(f"화면 캡처 저장 -> {self.shot_path}", scaled.save(str(self.shot_path)))

    # --- 8. 모드 전환 (앱 전체) ----------------------------------------------

    def step_mode_switch(self) -> None:
        """WidgetApp 을 통째로 띄워 텍스트 <-> 마스코트 왕복을 본다.

        실제 config.json 을 건드리지 않도록 임시 폴더에서 돈다.
        """
        print("[8] 모드 전환")
        self.overlay.hide()
        self.overlay = None

        from app import WidgetApp
        from mascot_overlay import MascotOverlay
        from overlay import WordOverlay

        sandbox = Path(tempfile.mkdtemp(prefix="mascot-verify-"))
        shutil.copy(ROOT / "words.txt", sandbox / "words.txt")
        shutil.copytree(ROOT / "sprites", sandbox / "sprites")

        wa = WidgetApp(self.app, sandbox)
        wa.start()
        self.pump(400)
        try:
            self.check("기본은 텍스트 모드", isinstance(wa.overlay, WordOverlay))
            self.check("텍스트 모드에서 '이동 · 크기 조정'이 보인다",
                       wa.tray.act_move.isVisible())

            wa.tray.mascot_mode_toggled.emit(True)
            self.pump(400)
            self.check("마스코트로 전환된다", isinstance(wa.overlay, MascotOverlay))
            self.check("전환 후 창이 떠 있다", wa.overlay.isVisible())
            self.check("전환 후 단어가 들어 있다", bool(wa.overlay._word))
            self.check("마스코트 모드에서 '이동 · 크기 조정'이 숨는다",
                       not wa.tray.act_move.isVisible())
            self.check("캐릭터 메뉴가 채워졌다",
                       len(wa.tray.character_menu.actions()) > 0)
            self.check("설정에 mascot 이 저장됐다",
                       '"mode": "mascot"' in (sandbox / "config.json").read_text(
                           encoding="utf-8"))

            wa.tray.mascot_mode_toggled.emit(False)
            self.pump(400)
            self.check("텍스트로 되돌아온다", isinstance(wa.overlay, WordOverlay))
            self.check("되돌아온 창도 떠 있다", wa.overlay.isVisible())

            wa.tray.mascot_mode_toggled.emit(True)
            self.pump(400)
            self.check("다시 마스코트로 (왕복해도 멀쩡)",
                       isinstance(wa.overlay, MascotOverlay) and wa.overlay.isVisible())
        finally:
            wa.shutdown()
            self.pump(200)
            shutil.rmtree(sandbox, ignore_errors=True)

    # --- 9. 캐릭터가 없을 때 --------------------------------------------------

    def step_no_sprites(self) -> None:
        """sprites 폴더가 비어 있는데 설정이 mascot 이면 텍스트로 물러나야 한다."""
        print("[9] 캐릭터가 없을 때")
        from app import WidgetApp
        from overlay import WordOverlay

        sandbox = Path(tempfile.mkdtemp(prefix="mascot-empty-"))
        shutil.copy(ROOT / "words.txt", sandbox / "words.txt")
        (sandbox / "config.json").write_text('{"mode": "mascot"}', encoding="utf-8")

        wa = WidgetApp(self.app, sandbox)
        wa.start()
        self.pump(300)
        try:
            self.check("텍스트 모드로 물러난다", isinstance(wa.overlay, WordOverlay))
            self.check("죽지 않고 단어를 띄운다", wa.overlay.isVisible())
        finally:
            wa.shutdown()
            self.pump(200)
            shutil.rmtree(sandbox, ignore_errors=True)

    # --- 진행 ----------------------------------------------------------------

    def run(self) -> None:
        try:
            self.step_characters()
            if self.overlay is None:
                return
            self.step_window()
            self.step_hit_test()
            self.step_drag()
            self.step_walk()
            self.step_switch()
            self.step_capture()
            self.step_mode_switch()
            self.step_no_sprites()
        finally:
            self.finish()

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
    QTimer.singleShot(90000, lambda: (print("시간 초과"), app.exit(2)))
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
