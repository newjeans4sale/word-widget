"""컨트롤러. 설정, 단어 공급, 오버레이, 트레이, 타이머를 엮는다."""
from __future__ import annotations

import logging
import random
import sys
from pathlib import Path

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QCursor, QDesktopServices

import config as config_mod
import fullscreen
import mascot_overlay
import osfont
import platform_win
from overlay import WordOverlay
from tray import TrayController
from wordsource import WordSource

log = logging.getLogger(__name__)

FULLSCREEN_POLL_MS = 1500
HOVER_POLL_MS = 120
# 커서가 지나가기만 해도 뜻이 번쩍이지 않도록 잠깐 머무를 것을 요구한다.
HOVER_DWELL_TICKS = 2


class WidgetApp:
    def __init__(self, qapp, base_dir: Path):
        self.qapp = qapp
        self.base_dir = Path(base_dir)
        self.config_path = self.base_dir / "config.json"

        self.max_font_pt = osfont.max_font_pt()
        log.info("아이콘 라벨 글꼴 %.1fpt -> 글자 크기 상한 %.1fpt",
                 osfont.desktop_icon_font_pt(), self.max_font_pt)

        self.cfg, warnings = config_mod.load(self.config_path, self.max_font_pt)
        for w in warnings:
            log.warning("설정: %s", w)
        self._pending_warnings = list(warnings)

        log.info("적용 설정: 글자 %dpt / 간격 %.1fs / 글꼴 %s",
                 self.cfg.font_size_pt, self.cfg.interval_sec, self.cfg.font_family)

        self.words_path = self._resolve_words_path()
        self.source = WordSource.from_file(self.words_path, rng=random.Random())
        if self.source.error:
            log.warning("단어 목록: %s", self.source.error)

        self.sprites_dir = self.base_dir / "sprites"
        self.overlay = self._make_overlay()
        self.tray = TrayController()

        self._paused = bool(self.cfg.paused)
        self._move_mode = False
        self._hidden_by_fullscreen = False

        self.word_timer = QTimer(qapp)
        self.word_timer.timeout.connect(self.next_word)
        self.fullscreen_timer = QTimer(qapp)
        self.fullscreen_timer.timeout.connect(self._check_fullscreen)
        # 클릭을 가로채지 않고 뜻을 보여주기 위해, 클릭이 아니라 커서 위치만 지켜본다.
        # 이렇게 하면 위젯은 계속 클릭 통과 상태로 남는다.
        self.hover_timer = QTimer(qapp)
        self.hover_timer.timeout.connect(self._check_hover)
        self._hover_ticks = 0

        self._wire()

    def _resolve_words_path(self) -> Path:
        p = Path(self.cfg.words_file)
        return p if p.is_absolute() else self.base_dir / p

    # --- 연결 ----------------------------------------------------------

    def _wire(self) -> None:
        t = self.tray
        t.pause_toggled.connect(self._on_pause)
        t.move_mode_toggled.connect(self._on_move_mode)
        t.next_word.connect(self.next_word)
        t.reset_requested.connect(self._on_reset)
        t.reload_requested.connect(self._on_reload)
        t.open_words.connect(self._open_words)
        t.open_config.connect(self._open_config)
        t.autostart_toggled.connect(self._on_autostart)
        t.quit_requested.connect(self.quit)
        t.became_available.connect(self._on_tray_available)
        t.mascot_mode_toggled.connect(self._on_mascot_mode)
        t.wander_toggled.connect(self._on_wander)
        t.character_selected.connect(self._on_character)
        self._wire_overlay()

    # --- 오버레이 만들기 / 갈아끼우기 --------------------------------------

    @property
    def mascot_mode(self) -> bool:
        """설정값이 아니라 지금 실제로 떠 있는 창을 본다.

        캐릭터가 없어 마스코트를 못 만들면 설정이 'mascot' 이어도 텍스트가 떠 있다."""
        return isinstance(self.overlay, mascot_overlay.MascotOverlay)

    def _make_overlay(self):
        """모드에 맞는 오버레이. 마스코트를 만들 수 없으면 텍스트로 물러난다."""
        if self.cfg.mode == "mascot":
            if mascot_overlay.available(self.sprites_dir):
                overlay = mascot_overlay.MascotOverlay(self.cfg, self.sprites_dir)
                self._pending_warnings.extend(overlay.warnings)
                return overlay
            warning = ("캐릭터가 없어 텍스트 모드로 시작합니다.\n"
                       "tools/fetch_sprites.py 를 한 번 실행해 주세요")
            log.warning("%s (%s)", warning, self.sprites_dir)
            self._pending_warnings.append(warning)
            self.cfg.mode = "text"
        overlay = WordOverlay(self.cfg)
        overlay.set_font_limits(config_mod.MIN_FONT_PT, int(self.max_font_pt))
        return overlay

    def _wire_overlay(self) -> None:
        """오버레이는 갈아끼워지므로 트레이 배선과 분리해 둔다."""
        o = self.overlay
        if self.mascot_mode:
            o.moved.connect(self._on_mascot_moved)
            o.clicked.connect(self.next_word)
        else:
            o.moved.connect(self._on_moved)
            o.font_size_changed.connect(self._on_font_resized)

    def _rebuild_overlay(self) -> None:
        old = self.overlay
        self.overlay = self._make_overlay()
        if old is not None:
            old.hide()
            old.deleteLater()
        self._move_mode = False
        self._wire_overlay()
        if not self.tray.available:
            self.overlay.context_menu = self.tray.menu
        if not self._hidden_by_fullscreen:
            self.overlay.show()
        self.next_word()
        self._sync_tray_mode()
        self._flush_warnings()

    def _sync_tray_mode(self) -> None:
        self.tray.set_mode(self.mascot_mode)
        self.tray.set_characters(
            mascot_overlay.available(self.sprites_dir),
            self.overlay.character if self.mascot_mode else None)
        self.tray.act_wander.blockSignals(True)
        self.tray.act_wander.setChecked(bool(self.cfg.mascot_wander))
        self.tray.act_wander.blockSignals(False)

    # --- 기동 / 종료 ----------------------------------------------------

    def start(self) -> None:
        self.tray.install()
        self.tray.act_pause.setChecked(self._paused)
        if self.tray.act_autostart is not None:
            self.tray.act_autostart.blockSignals(True)
            self.tray.act_autostart.setChecked(platform_win.is_autostart_enabled())
            self.tray.act_autostart.blockSignals(False)

        self._sync_tray_mode()
        self.next_word()
        self.overlay.show()

        self._apply_timer()
        self.fullscreen_timer.start(FULLSCREEN_POLL_MS)
        self.hover_timer.start(HOVER_POLL_MS)

        if not self.tray.available:
            self._enable_no_tray_fallback()

        # 사용자가 폴더를 열었을 때 고칠 파일이 바로 보이도록 첫 실행에 만들어 둔다.
        # (config.load() 자체는 파일을 만들지 않는다 - 읽기 함수의 부작용은 곤란하다)
        if not self.config_path.exists():
            self._save_config()

        self._flush_warnings()
        if self.source.error:
            self.tray.notify("단어 목록을 읽지 못했습니다",
                             self.source.error + "\n" + str(self.words_path))

    def shutdown(self) -> None:
        self.word_timer.stop()
        self.fullscreen_timer.stop()
        self.hover_timer.stop()
        self._save_config()
        self.tray.shutdown()

    def quit(self) -> None:
        self.shutdown()
        self.qapp.quit()

    # --- 타이머 ---------------------------------------------------------

    def _apply_timer(self) -> None:
        """일시정지와 이동 모드를 한 곳에서 판정한다.

        이동 모드에서 단어가 바뀌면 드래그 중인 커서 밑에서 창 크기가 변한다.
        그래서 이동 중에는 회전을 멈춘다.
        """
        # 뜻을 읽는 중에 단어가 바뀌면 곤란하므로 호버 중에도 멈춘다.
        if self._paused or self._move_mode or self.overlay.meaning_visible:
            self.word_timer.stop()
        else:
            self.word_timer.start(max(1, int(self.cfg.interval_sec * 1000)))

    def next_word(self) -> None:
        """일시정지 중이어도 한 번은 넘긴다 (트레이 '다음 단어')."""
        word = self.source.next()
        self.overlay.set_word(word, self.source.meaning(word))

    # --- 트레이 동작 ----------------------------------------------------

    def _on_pause(self, paused: bool) -> None:
        self._paused = bool(paused)
        self.cfg.paused = self._paused
        self._apply_timer()
        self._save_config()

    def _on_move_mode(self, on: bool) -> None:
        self._move_mode = bool(on)
        self.overlay.set_move_mode(self._move_mode)
        self._apply_timer()

    def _on_mascot_mode(self, on: bool) -> None:
        want = "mascot" if on else "text"
        if want == self.cfg.mode and bool(on) == self.mascot_mode:
            return
        self.cfg.mode = want
        self._rebuild_overlay()   # 만들지 못하면 _make_overlay 가 text 로 되돌린다
        self._apply_timer()
        self._save_config()

    def _on_wander(self, on: bool) -> None:
        self.cfg.mascot_wander = bool(on)
        if self.mascot_mode:
            self.overlay.set_wander(on)
        self._save_config()

    def _on_character(self, name: str) -> None:
        if not self.mascot_mode:
            return
        if self.overlay.set_character(name):
            self.cfg.character = self.overlay.character
            self._save_config()
        else:
            self.tray.notify("캐릭터를 바꾸지 못했습니다", name)

    def _on_mascot_moved(self, x: int, y: int) -> None:
        self.cfg.mascot_x, self.cfg.mascot_y = x, y
        self._save_config()

    def _on_moved(self, x: int, y: int, anchor: str) -> None:
        self.cfg.anchor_x, self.cfg.anchor_y, self.cfg.anchor = x, y, anchor
        self._save_config()

    def _on_reload(self) -> None:
        cfg, warnings = config_mod.load(self.config_path, self.max_font_pt)
        mode_changed = (cfg.mode == "mascot") != self.mascot_mode
        self.cfg = cfg
        self.words_path = self._resolve_words_path()
        words_ok = self.source.reload_from_file(self.words_path)

        if mode_changed:
            # 모드가 바뀌면 창 종류가 다르다. 설정만 다시 먹일 수는 없다.
            self._rebuild_overlay()
        else:
            self.overlay.apply_config(cfg)
            self._sync_tray_mode()
        self._paused = bool(cfg.paused)
        self.tray.act_pause.setChecked(self._paused)
        self._apply_timer()
        self.next_word()

        for w in warnings:
            log.warning("설정: %s", w)
        if words_ok:
            self.tray.notify("다시 불러왔습니다", f"단어 {self.source.count}개")
        else:
            # 편집기가 저장 중 파일을 비운 순간일 수 있다. 기존 목록은 살아 있다.
            self.tray.notify("단어 목록을 갱신하지 못했습니다",
                             (self.source.error or "파일을 읽을 수 없습니다")
                             + "\n기존 목록을 유지합니다")

    def _on_autostart(self, enabled: bool) -> None:
        pythonw = Path(sys.executable).with_name("pythonw.exe")
        if not pythonw.exists():
            pythonw = Path(sys.executable)
        command = platform_win.autostart_command(pythonw, self.base_dir / "main.py")
        if platform_win.set_autostart(enabled, command):
            self.tray.notify("자동 실행",
                             "켜짐 - 부팅 시 자동으로 뜹니다" if enabled else "꺼짐")
        else:
            self.tray.notify("자동 실행 설정 실패", "로그를 확인해 주세요")
            if self.tray.act_autostart is not None:
                self.tray.act_autostart.blockSignals(True)
                self.tray.act_autostart.setChecked(not enabled)
                self.tray.act_autostart.blockSignals(False)

    def _open_words(self) -> None:
        # 없는 파일을 열면 아무 일도 안 일어난다. 그럴 땐 폴더를 연다.
        target = self.words_path if self.words_path.exists() else self.words_path.parent
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))

    def _open_config(self) -> None:
        if not self.config_path.exists():
            self._save_config()
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.config_path)))

    # --- 전체화면 -------------------------------------------------------

    def _check_fullscreen(self) -> None:
        if not self.cfg.hide_on_fullscreen:
            if self._hidden_by_fullscreen:
                self.overlay.show()
                self._hidden_by_fullscreen = False
            return

        if fullscreen.is_foreground_fullscreen():
            if not self._hidden_by_fullscreen:
                self.overlay.hide()
                self._hidden_by_fullscreen = True
        elif self._hidden_by_fullscreen:
            self.overlay.show()
            self._hidden_by_fullscreen = False

    # --- 트레이 없음 폴백 ------------------------------------------------

    def _enable_no_tray_fallback(self) -> None:
        """트레이를 못 쓰면 종료할 방법이 사라진다. 위젯 우클릭에 같은 메뉴를 붙인다."""
        log.warning("트레이 사용 불가 - 위젯 우클릭 메뉴로 대체합니다")
        self.overlay.context_menu = self.tray.menu
        self._move_mode = True
        self.overlay.set_move_mode(True)  # 클릭 통과를 꺼야 우클릭이 먹는다
        self.tray.act_move.setChecked(True)
        self._apply_timer()

    def _on_tray_available(self) -> None:
        log.info("트레이가 복구되었습니다")
        self.overlay.context_menu = None

    # --- 저장 -----------------------------------------------------------

    def _flush_warnings(self, title: str = "설정을 일부 되돌렸습니다") -> None:
        for w in self._pending_warnings:
            self.tray.notify(title, w)
        self._pending_warnings.clear()

    def _save_config(self) -> None:
        # 마스코트는 계속 걸어다니므로 저장 직전의 자리를 그대로 담는다.
        # (apply_config 가 먼저 도는 '되돌리기' 경로에서는 기본 위치가 담긴다)
        if self.mascot_mode:
            self.cfg.mascot_x, self.cfg.mascot_y = self.overlay.position
        try:
            config_mod.save(self.config_path, self.cfg)
        except OSError:
            log.warning("설정 저장 실패", exc_info=True)

    # --- 뜻 보기 (마우스 오버) ---------------------------------------------

    def _check_hover(self) -> None:
        """커서가 위젯 위에 머물면 뜻을 붙여 보여준다.

        클릭을 받는 대신 커서 위치만 지켜본다. 그래야 위젯이 계속 클릭 통과
        상태로 남아 작업을 가로막지 않는다.
        """
        if self._move_mode or not self.overlay.isVisible():
            self._clear_hover()
            return
        if not self.overlay.has_meaning:
            self._hover_ticks = 0
            return

        if self.overlay.hover_rect().contains(QCursor.pos()):
            self._hover_ticks += 1
            if self._hover_ticks >= HOVER_DWELL_TICKS and not self.overlay.meaning_visible:
                self.overlay.set_meaning_visible(True)
                self._apply_timer()   # 읽는 동안 단어가 바뀌지 않게 멈춘다
        else:
            self._clear_hover()

    def _clear_hover(self) -> None:
        self._hover_ticks = 0
        if self.overlay.meaning_visible:
            self.overlay.set_meaning_visible(False)
            self._apply_timer()

    # --- 글자 크기 / 기본값 -------------------------------------------------

    def _on_font_resized(self, pt: int) -> None:
        """손잡이 드래그가 끝났을 때 최종 크기를 저장한다.

        드래그 중에는 오버레이가 스스로 다시 그리기만 하고, 파일 쓰기는 놓을 때
        한 번만 한다. 움직일 때마다 저장하면 디스크를 계속 두드리게 된다.

        여기서 트레이 알림을 띄우면 안 된다. 알림 풍선도 위젯도 둘 다 우측 하단에
        나타나서 풍선이 위젯을 덮어버린다. 그러면 크기를 조절한 직후 다시 손잡이를
        잡으려 해도 클릭이 풍선으로 가서 아무 반응이 없다. 크기 변화는 글자로
        바로 보이므로 알림이 필요하지도 않다.
        """
        if pt == self.cfg.font_size_pt:
            return
        self.cfg.font_size_pt = int(pt)
        self._save_config()
        log.debug("글자 크기 %dpt 로 저장", pt)

    def _on_reset(self) -> None:
        """모양과 위치만 기본값으로. 단어 목록 경로는 건드리지 않는다.

        사용자가 words_file 을 자기 파일로 바꿔 뒀는데 그것까지 되돌리면
        갑자기 다른 단어가 뜨게 된다. 되돌리기가 그렇게까지 할 일은 아니다.
        """
        words_file = self.cfg.words_file
        paused = self.cfg.paused
        mode, character = self.cfg.mode, self.cfg.character
        wander = self.cfg.mascot_wander
        self.cfg = config_mod.Config()
        self.cfg.words_file = words_file
        self.cfg.paused = paused
        # 모드와 캐릭터는 '무엇을 보여줄지'이지 '모양·위치'가 아니다.
        self.cfg.mode, self.cfg.character = mode, character
        self.cfg.mascot_wander = wander
        self.cfg.font_size_pt = min(self.cfg.font_size_pt, int(self.max_font_pt))

        self.overlay.apply_config(self.cfg)
        self._apply_timer()
        self._save_config()
        self.tray.notify(
            "기본값으로 되돌렸습니다",
            "글자 %dpt / 간격 %.0f초 / 우측 하단\n단어 목록 경로는 그대로입니다"
            % (self.cfg.font_size_pt, self.cfg.interval_sec))
