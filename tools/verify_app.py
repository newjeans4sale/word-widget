r"""앱 레벨 동작 검증 (트레이 메뉴, 마우스 오버 뜻 보기, 크기 조절, 되돌리기).

    .venv\Scripts\python.exe tools\verify_app.py

창/그리기 동작은 verify_gui.py 가 본다. 이쪽은 WidgetApp 을 실제로 띄워서
트레이 항목을 눌렀을 때 끝까지 반응하는지 확인한다.
커서를 잠깐 움직이며, 끝나면 원래 자리로 되돌려 놓는다.
실제 config.json 을 건드리지 않도록 임시 폴더에서 돈다.
"""
from __future__ import annotations

import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from PySide6.QtCore import QTimer                       # noqa: E402
from PySide6.QtGui import QGuiApplication               # noqa: E402
from PySide6.QtWidgets import QApplication              # noqa: E402

import realinput                                        # noqa: E402
from app import WidgetApp                               # noqa: E402

failures: list[str] = []


def check(label: str, ok: bool) -> None:
    print(("  OK    " if ok else "  FAIL  ") + label)
    if not ok:
        failures.append(label)


def make_sandbox() -> Path:
    d = Path(tempfile.mkdtemp(prefix="word-widget-verify-"))
    src = ROOT / "words.txt"
    if src.exists():
        shutil.copy(src, d / "words.txt")
    else:
        (d / "words.txt").write_text("ephemeral, 덧없는\nlaconic, 과묵한\n", encoding="utf-8")
    return d


def main() -> int:
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    sandbox = make_sandbox()
    wa = WidgetApp(app, sandbox)
    wa.start()
    saved_cursor = realinput.cursor_pos()

    def pump(n: int = 6) -> None:
        for _ in range(n):
            app.processEvents()
            time.sleep(0.05)

    def run() -> None:
        pump(12)
        o, tray = wa.overlay, wa.tray

        print("[1] 단어와 뜻 로딩")
        check("단어가 로드됐다", wa.source.count > 0)
        check("뜻도 로드됐다", wa.source.meaning_count > 0)
        # 뜻이 확실히 있는 단어로 고정한 뒤 호버를 본다.
        word = next(w for w in wa.source.words if wa.source.meaning(w))
        o.set_word(word, wa.source.meaning(word))
        pump(4)
        check("현재 단어에 뜻이 붙어 있다", o.has_meaning)
        print(f"        {word} -> {wa.source.meaning(word)}")

        print("[2] 마우스를 올리면 뜻이 붙는다 (클릭 통과는 유지)")
        narrow = o.geometry()
        cx = narrow.x() + narrow.width() // 2
        cy = narrow.y() + narrow.height() // 2

        # 사람이 실제로 마우스를 쓰고 있으면 우리가 옮겨 놓은 커서가 바로 벗어난다.
        # 그건 테스트 환경 문제이지 기능 실패가 아니므로, 몇 번 시도해 보고
        # 끝내 커서를 잡아둘 수 없으면 실패가 아니라 건너뜀으로 보고한다.
        held = False
        for _ in range(5):
            realinput.restore_cursor((cx, cy))
            for _ in range(14):
                pump(1)
                if o.meaning_visible:
                    held = True
                    break
            if held or realinput.cursor_pos() == (cx, cy):
                break

        if not held and realinput.cursor_pos() != (cx, cy):
            print("        건너뜀: 사용자가 마우스를 움직이고 있어 커서를 고정할 수 없습니다")
            print("        (수동 확인: 단어 위에 커서를 올려 뜻이 뜨는지 보세요)")
        else:
            wide = o.geometry()
            check("뜻이 표시된다", o.meaning_visible)
            check("위젯이 넓어진다", wide.width() > narrow.width())
            check("앵커(우하단)는 고정",
                  wide.x() + wide.width() == narrow.x() + narrow.width())
            check("읽는 동안 단어 회전이 멈춘다", not wa.word_timer.isActive())
            print(f"        {narrow.width()}px -> {wide.width()}px")

            print("[3] 커서를 치우면 원래대로")
            realinput.restore_cursor((cx - 500, cy - 400))
            for _ in range(16):
                pump(1)
                if not o.meaning_visible:
                    break
            check("뜻이 사라진다", not o.meaning_visible)
            check("폭이 돌아온다", o.geometry().width() == narrow.width())
            check("단어 회전 재개", wa.word_timer.isActive())

        print("[4] 손잡이를 끌어 글자 크기 조절")
        cap = int(wa.max_font_pt)
        # 위젯이 화면 가장자리에 있으면 안쪽으로 크게 끌 때 커서가 화면 밖으로
        # 잘려 드래그가 목표에 도달하지 못한다. 검사 동안만 가운데로 옮긴다.
        center = QGuiApplication.primaryScreen().availableGeometry().center()
        wa.cfg.anchor, wa.cfg.anchor_x, wa.cfg.anchor_y = "bottom-right", center.x(), center.y()
        o.apply_config(wa.cfg)
        pump(4)
        tray.act_move.trigger(); pump(8)          # 이동·크기 조정 모드
        check("이동 모드가 켜진다", o._move_mode)

        def grip_center():
            return o.mapToGlobal(o._grip_rect().center())

        def drag_grip(px, start_pt=None):
            """손잡이를 앵커 바깥으로 px 만큼(음수면 안쪽) 한 번에 끈다.

            짧은 드래그를 연타하지 않는다. 합성 입력을 빠르게 반복하면 Windows 가
            묶어버려 중간중간 이벤트가 통째로 사라진다. 한 번에 크게 끄는 쪽이
            사람이 실제로 하는 동작에도 가깝다.
            """
            import math
            if start_pt is not None:
                o.set_font_size_pt(start_pt)
                pump(4)
            before = o.font_size_pt
            c = grip_center()
            ax, ay, _ = o.anchor_state
            vx, vy = c.x() - ax, c.y() - ay
            length = math.hypot(vx, vy) or 1.0
            tx = int(round(c.x() + vx / length * px))
            ty = int(round(c.y() + vy / length * px))
            realinput.drag((c.x(), c.y()), (tx, ty), app.processEvents, steps=10)
            pump(14)
            if realinput.cursor_pos() != (tx, ty):
                return None, before
            return o.font_size_pt, before

        got, before = drag_grip(30, start_pt=12)
        if got is None:
            print("        건너뜀: 커서를 고정할 수 없습니다")
        else:
            check(f"바깥으로 30px 끌면 2~4pt 커진다 ({before} -> {got})", 2 <= got - before <= 4)
            check("설정에 저장된다", wa.cfg.font_size_pt == got)

        got, before = drag_grip(400, start_pt=12)
        if got is not None:
            check(f"크게 끌어도 상한 {cap}pt 에서 멈춘다 ({before} -> {got})", got == cap)

        # 안쪽으로 너무 크게 끌면 커서가 화면 밖으로 나가 잘린다.
        # 손잡이-앵커 거리(약 120px)보다 조금 큰 정도면 하한에 닿는다.
        got, before = drag_grip(-130, start_pt=16)
        if got is not None:
            check(f"안쪽으로 끌면 하한 6pt 에서 멈춘다 ({before} -> {got})", got == 6)

        print("[4b] 끄는 방향이 달라도 고르게 반응한다")
        # PPT 모서리 핸들처럼 어느 방향으로 끌든 크기가 따라와야 한다.
        # 한 축에 투영하는 구현은 그 축과 수직으로 끌 때 아무 반응이 없었다.
        def drag_axis(dx, dy):
            o.set_font_size_pt(12)
            pump(3)
            before = o.font_size_pt
            c = grip_center()
            realinput.drag((c.x(), c.y()), (c.x() + dx, c.y() + dy),
                           app.processEvents, steps=8)
            pump(14)
            if realinput.cursor_pos() != (c.x() + dx, c.y() + dy):
                return None
            return o.font_size_pt - before

        # 이동 모드는 [4] 에서 이미 켜 두었다. 여기서 또 토글하면 꺼져버린다.
        # 앵커가 우하단이면 손잡이는 좌상단이므로 왼쪽/위가 '커지는' 방향이다.
        ax, ay, anchor = o.anchor_state
        sx = -1 if anchor.endswith("right") else 1
        sy = -1 if anchor.startswith("bottom") else 1
        horiz = drag_axis(30 * sx, 0)
        vert = drag_axis(0, 30 * sy)
        if horiz is None or vert is None:
            print("        건너뜀: 커서를 고정할 수 없습니다")
        else:
            print(f"        가로 30px -> {horiz:+d}pt / 세로 30px -> {vert:+d}pt")
            check("가로로만 끌어도 커진다", horiz > 0)
            check("세로로만 끌어도 커진다", vert > 0)
            check("두 방향의 반응 크기가 비슷하다", abs(horiz - vert) <= 1)

        tray.act_move.trigger(); pump(6)
        check("이동 모드가 꺼진다", not o._move_mode)

        print("[5] 기본값으로 되돌리기 (모양·위치)")
        wa.cfg.anchor_x, wa.cfg.anchor_y, wa.cfg.anchor = 300, 300, "top-left"
        o.apply_config(wa.cfg); pump(3)
        tray.act_reset.trigger(); pump(8)
        check("글자 크기 14pt 복귀", wa.cfg.font_size_pt == 14)
        check("간격 5초 복귀", wa.cfg.interval_sec == 5.0)
        check("앵커 우측 하단 복귀", wa.cfg.anchor == "bottom-right")
        avail = QGuiApplication.primaryScreen().availableGeometry()
        g = o.geometry()
        check("실제로 우측 하단에 배치된다",
              g.x() + g.width() > avail.right() - 200 and g.y() > avail.bottom() - 200)
        check("단어 목록 경로는 유지", wa.cfg.words_file == "words.txt")

        print("[6] 트레이 기본 항목")
        before = o._word
        tray.act_next.trigger(); pump(3)
        check("다음 단어", o._word != before)
        tray.act_pause.trigger(); pump(3)
        check("일시정지", not wa.word_timer.isActive())
        tray.act_pause.trigger(); pump(3)
        check("재개", wa.word_timer.isActive())

        realinput.restore_cursor(saved_cursor)
        print()
        if failures:
            print(f"=== 실패 {len(failures)}건 ===")
            for f in failures:
                print("   -", f)
        else:
            print("=== 전부 통과 ===")
        wa.shutdown()
        shutil.rmtree(sandbox, ignore_errors=True)
        app.exit(1 if failures else 0)

    QTimer.singleShot(800, run)
    QTimer.singleShot(90000, lambda: (print("시간 초과"), app.exit(2)))
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
