"""트레이 아이콘과 메뉴.

아이콘 파일을 배포하지 않는다. 실행 시점에 QPixmap 에 직접 그린다.
"""
from __future__ import annotations

import logging
import sys

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import (QAction, QColor, QFont, QFontMetricsF, QIcon, QPainter,
                           QPainterPath, QPixmap)
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

log = logging.getLogger(__name__)

IS_MAC = sys.platform == "darwin"
IS_WINDOWS = sys.platform == "win32"

BADGE_COLOR = QColor(38, 92, 168)
ICON_SIZES = (16, 20, 24, 32, 48, 64)

RETRY_INTERVAL_MS = 5000
RETRY_LIMIT = 12  # 5초 x 12 = 60초


def _render_icon(size: int, letter: str) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(QColor(0, 0, 0, 0))
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    if IS_MAC:
        # 메뉴 막대는 setIsMask 로 시스템이 색을 다시 칠한다. 단색 글리프만 그린다.
        p.setPen(QColor(0, 0, 0))
        fg = QColor(0, 0, 0)
    else:
        # 밝은 작업표시줄에서도 어두운 작업표시줄에서도 읽히도록 둥근 배지를 깐다.
        p.setPen(QColor(0, 0, 0, 0))
        p.setBrush(BADGE_COLOR)
        radius = size * 0.18
        p.drawRoundedRect(0, 0, size, size, radius, radius)
        fg = QColor(255, 255, 255)

    font = QFont("Helvetica Neue" if IS_MAC else "Segoe UI")
    font.setPointSizeF(size * 0.62)
    font.setBold(True)

    # drawText 는 서브픽셀 안티에일리어싱을 써서 글자 가장자리에 빨강/파랑 색을 남긴다.
    # 작은 아이콘에서는 렌더링 결함처럼 보인다. QFont.NoSubpixelAntialias 로는 막히지
    # 않으므로 오버레이와 같이 벡터 path 로 채운다.
    fm = QFontMetricsF(font)
    path = QPainterPath()
    x = (size - fm.horizontalAdvance(letter)) / 2.0
    y = (size - fm.height()) / 2.0 + fm.ascent()
    path.addText(x, y, font, letter)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(fg)
    p.drawPath(path)
    # 파이썬은 QPainter 소멸 시점이 비결정적이다. end() 를 빠뜨리면 빈 아이콘이 나온다.
    p.end()
    return pm


def make_tray_icon(letter: str = "W") -> QIcon:
    """QApplication 생성 후에 호출해야 한다. QPixmap 은 그전에 만들 수 없다."""
    icon = QIcon()
    for size in ICON_SIZES:
        # 64를 16으로 축소하면 뭉개진다. 각 크기를 따로 그린다.
        icon.addPixmap(_render_icon(size, letter))
    if IS_MAC:
        icon.setIsMask(True)
    return icon


class TrayController(QObject):
    """트레이 아이콘의 수명과 메뉴를 소유한다.

    QSystemTrayIcon 과 QMenu 를 인스턴스 속성으로 붙들고 있어야 한다.
    지역 변수로 두면 GC 되어 아이콘이 조용히 사라지거나 메뉴 열 때 죽는다.
    """

    pause_toggled = Signal(bool)
    move_mode_toggled = Signal(bool)
    autostart_toggled = Signal(bool)
    next_word = Signal()
    reset_requested = Signal()
    reload_requested = Signal()
    open_words = Signal()
    open_config = Signal()
    quit_requested = Signal()
    became_available = Signal()

    def __init__(self, parent=None, show_autostart: bool = IS_WINDOWS):
        super().__init__(parent)
        self._icon = make_tray_icon()
        self.menu = QMenu()
        self.tray: QSystemTrayIcon | None = None
        self._retries = 0
        self._retry_timer: QTimer | None = None

        self.act_pause = self._add_check("일시정지", self.pause_toggled)
        self.act_next = self._add_action("다음 단어", self.next_word)
        self.menu.addSeparator()
        self.act_move = self._add_check("이동 · 크기 조정", self.move_mode_toggled)
        self.menu.addSeparator()
        self.act_reload = self._add_action("다시 불러오기 (단어+설정)", self.reload_requested)
        self.act_open_words = self._add_action("단어 목록 열기", self.open_words)
        self.act_open_config = self._add_action("설정 열기", self.open_config)
        self.act_reset = self._add_action("기본값으로 되돌리기 (모양·위치)", self.reset_requested)
        self.act_autostart = None
        if show_autostart:
            self.menu.addSeparator()
            self.act_autostart = self._add_check("Windows 시작 시 실행", self.autostart_toggled)
        self.menu.addSeparator()
        self.act_quit = self._add_action("종료", self.quit_requested)

    # --- 메뉴 구성 -----------------------------------------------------

    def _add_action(self, text: str, signal) -> QAction:
        action = QAction(text, self)  # parent 를 줘야 GC 되지 않는다
        action.triggered.connect(lambda: signal.emit())
        self.menu.addAction(action)
        return action

    def _add_check(self, text: str, signal) -> QAction:
        action = QAction(text, self)
        action.setCheckable(True)
        action.toggled.connect(signal.emit)
        self.menu.addAction(action)
        return action

    # --- 수명 ----------------------------------------------------------

    def install(self) -> bool:
        """트레이 아이콘을 띄운다. 아직 못 쓰면 60초 동안 재시도한다."""
        if not QSystemTrayIcon.isSystemTrayAvailable():
            self._schedule_retry()
            return False
        self.tray = QSystemTrayIcon(self._icon, self)
        self.tray.setToolTip("영단어 위젯")
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self._on_activated)
        self.tray.show()
        log.info("트레이 아이콘 등록 완료")
        return True

    def _schedule_retry(self) -> None:
        if self._retries >= RETRY_LIMIT:
            log.warning("트레이를 쓸 수 없습니다. 위젯 우클릭 메뉴로 대체합니다.")
            return
        if self._retry_timer is None:
            self._retry_timer = QTimer(self)
            self._retry_timer.timeout.connect(self._retry)
        self._retries += 1
        self._retry_timer.start(RETRY_INTERVAL_MS)
        log.info("트레이 사용 불가. %d초 후 재시도 (%d/%d)",
                 RETRY_INTERVAL_MS // 1000, self._retries, RETRY_LIMIT)

    def _retry(self) -> None:
        if QSystemTrayIcon.isSystemTrayAvailable():
            self._retry_timer.stop()
            if self.install():
                self.became_available.emit()
        else:
            self._schedule_retry()

    def _on_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.next_word.emit()

    @property
    def available(self) -> bool:
        return self.tray is not None

    def notify(self, title: str, message: str) -> None:
        if self.tray is not None:
            self.tray.showMessage(title, message, self._icon, 5000)
        else:
            log.info("[알림] %s: %s", title, message)

    def shutdown(self) -> None:
        # 숨기지 않고 종료하면 마우스를 올릴 때까지 유령 아이콘이 남는다.
        if self.tray is not None:
            self.tray.hide()
            self.tray = None
