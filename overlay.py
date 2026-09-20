"""화면 위에 단어 하나를 그리는 투명 오버레이 창."""
from __future__ import annotations

import logging
import math
import sys

from PySide6.QtCore import QPoint, QPointF, QRect, Qt, Signal
from PySide6.QtGui import (QColor, QFont, QFontDatabase, QFontMetricsF, QGuiApplication,
                           QPainter, QPainterPath, QPen)
from PySide6.QtWidgets import QWidget

import platform_win

log = logging.getLogger(__name__)

IS_MAC = sys.platform == "darwin"

FLAGS = (Qt.WindowType.FramelessWindowHint
         | Qt.WindowType.WindowStaysOnTopHint
         | Qt.WindowType.Tool
         | Qt.WindowType.WindowDoesNotAcceptFocus
         | Qt.WindowType.NoDropShadowWindowHint
         | Qt.WindowType.WindowTransparentForInput)

SCREEN_MARGIN = 24
MEANING_SEPARATOR = "   ·   "
GRIP_SIZE = 12
# 손잡이가 앵커에서 이만큼 더 멀어질 때마다 1pt 커진다.
RESIZE_PX_PER_PT = 12.0
MIN_VISIBLE = (32, 16)
FALLBACK_FAMILIES = ("Helvetica Neue", "Helvetica") if IS_MAC else ("Segoe UI", "Arial")


def resolve_font_family(requested: str) -> str:
    """QFont 는 없는 글꼴을 조용히 바꿔치기한다. 미리 확인해 로그를 남긴다."""
    families = set(QFontDatabase.families())
    if requested in families:
        return requested
    for candidate in FALLBACK_FAMILIES:
        if candidate in families:
            log.warning("글꼴 '%s' 을 찾을 수 없어 '%s' 로 대체합니다", requested, candidate)
            return candidate
    log.warning("글꼴 '%s' 을 찾을 수 없습니다. 시스템 기본값을 씁니다", requested)
    return QGuiApplication.font().family()


def clamp_to_screens(rect: QRect) -> QRect:
    """화면 밖으로 완전히 벗어난 창만 되돌린다.

    음수 x 는 정상값이다 - 두 번째 모니터가 x = -1920 에 있다.
    0 과 비교하는 검증을 넣으면 그 모니터에서 위젯이 순간이동한다.
    """
    # 창이 MIN_VISIBLE 보다 작을 수 있다(짧은 단어는 폭이 30px 도 안 된다).
    # 요구치를 창 크기로 한 번 깎지 않으면 화면 안에 있어도 '밖'으로 판정된다.
    min_w = min(MIN_VISIBLE[0], rect.width())
    min_h = min(MIN_VISIBLE[1], rect.height())
    for screen in QGuiApplication.screens():
        inter = screen.availableGeometry().intersected(rect)
        if inter.width() >= min_w and inter.height() >= min_h:
            return rect
    avail = QGuiApplication.primaryScreen().availableGeometry()
    log.info("저장된 위치가 화면 밖 - 주 화면 우측 하단으로 복귀")
    return QRect(avail.right() + 1 - rect.width() - SCREEN_MARGIN,
                 avail.bottom() + 1 - rect.height() - SCREEN_MARGIN,
                 rect.width(), rect.height())


class WordOverlay(QWidget):
    """테두리도 배경도 없이 단어만 떠 있는 창."""

    moved = Signal(int, int, str)       # anchor_x, anchor_y, anchor
    font_size_changed = Signal(int)     # 손잡이 드래그로 크기를 바꾸고 놓았을 때

    def __init__(self, cfg):
        super().__init__(None)
        self._word = ""
        self._meaning = None
        self._meaning_visible = False
        self._meaning_color = QColor("#CFE3FF")
        self._move_mode = False
        self._drag_offset = None
        self._resize_from = None      # (시작 pt, 앵커까지의 시작 거리)
        self._font_pt = 14
        self._font_min = 6
        self._font_max = 18
        self._font = QFont()
        self._outline_w = 2.0
        self._color = QColor("#FFFFFF")
        self._outline_color = QColor("#000000")
        self._pad = 3
        self._anchor = cfg.anchor
        self._anchor_x = cfg.anchor_x
        self._anchor_y = cfg.anchor_y
        self.context_menu = None  # 트레이를 못 쓸 때의 탈출구 (app.py 가 붙인다)

        self.setWindowFlags(FLAGS)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        if IS_MAC:
            # 이걸 켜지 않으면 앱이 최전면이 아닐 때 창이 사라진다 = 거의 항상 안 보인다.
            self.setAttribute(Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setMinimumSize(1, 1)

        self.apply_config(cfg)

    def apply_config(self, cfg) -> None:
        self._font_pt = int(cfg.font_size_pt)
        font = QFont(resolve_font_family(cfg.font_family))
        font.setPointSizeF(float(cfg.font_size_pt))
        # path 렌더링은 힌팅을 무시하므로 측정과 렌더가 어긋나지 않게 맞춘다.
        font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
        self._font = font

        self._outline_w = max(1.5, cfg.font_size_pt * 0.14)
        self._pad = math.ceil(self._outline_w) + 1

        alpha = max(0.0, min(1.0, float(cfg.opacity)))
        # setWindowOpacity 는 쓰지 않는다. 투명 레이어드 창에서 창이 통째로 사라지거나
        # 검게 되는 알려진 상호작용이 있다. 색상 알파로 준다.
        self._color = QColor(cfg.color)
        self._color.setAlphaF(alpha)
        self._outline_color = QColor(cfg.outline_color)
        self._outline_color.setAlphaF(min(1.0, alpha + 0.15))
        # 뜻은 단어보다 조금 흐리고 푸른 기가 돌게 해서 한눈에 구분되게 한다.
        self._meaning_color = QColor("#B9D4F5")
        self._meaning_color.setAlphaF(max(0.35, alpha - 0.1))

        self._anchor = cfg.anchor
        # None 을 그대로 받아들인다. _ensure_anchor 가 기본 위치(우측 하단)를 채운다.
        # '기본값으로 되돌리기' 가 위치까지 되돌리려면 이 대입이 무조건 일어나야 한다.
        self._anchor_x, self._anchor_y = cfg.anchor_x, cfg.anchor_y
        self._relayout()

    def _ensure_anchor(self) -> None:
        if self._anchor_x is not None and self._anchor_y is not None:
            return
        avail = QGuiApplication.primaryScreen().availableGeometry()
        self._anchor = "bottom-right"
        self._anchor_x = avail.right() + 1 - SCREEN_MARGIN
        self._anchor_y = avail.bottom() + 1 - SCREEN_MARGIN

    def set_word(self, word: str, meaning: str | None = None) -> None:
        if word == self._word and meaning == self._meaning:
            return
        self._word = word
        self._meaning = meaning
        self._relayout()
        self.update()

    def set_meaning_visible(self, on: bool) -> None:
        """마우스를 올렸을 때 뜻을 붙여 보여준다. 뜻이 없으면 아무 일도 하지 않는다."""
        on = bool(on) and bool(self._meaning)
        if on == self._meaning_visible:
            return
        self._meaning_visible = on
        self._relayout()
        self.update()

    @property
    def has_meaning(self) -> bool:
        return bool(self._meaning)

    @property
    def meaning_visible(self) -> bool:
        return self._meaning_visible

    def _elide(self, text: str) -> str:
        screen = self.screen() or QGuiApplication.primaryScreen()
        limit = max(120, screen.availableGeometry().width() // 3)
        return QFontMetricsF(self._font).elidedText(
            text, Qt.TextElideMode.ElideRight, limit)

    def _parts(self) -> list:
        """(그릴 문자열, 색) 목록. 단어와 뜻을 다른 색으로 이어 그린다."""
        if not self._word:
            return []
        parts = [(self._elide(self._word), self._color)]
        if self._meaning_visible and self._meaning:
            parts.append((MEANING_SEPARATOR + self._elide(self._meaning),
                          self._meaning_color))
        return parts

    def _display_text(self) -> str:
        return "".join(text for text, _ in self._parts())

    def _relayout(self) -> None:
        self._ensure_anchor()
        fm = QFontMetricsF(self._font)
        text = self._display_text()
        w = max(1, math.ceil(fm.horizontalAdvance(text)) + 2 * self._pad)
        h = max(1, math.ceil(fm.height()) + 2 * self._pad)

        ax, ay = self._anchor_x, self._anchor_y
        nx = ax - w if self._anchor.endswith("right") else ax
        ny = ay - h if self._anchor.startswith("bottom") else ay

        # resize() + move() 두 번이 아니라 setGeometry 한 번. 두 번이면 네이티브 호출이
        # 두 번 나가 레이어드 창에서 한 프레임 튄다.
        self.setGeometry(clamp_to_screens(QRect(nx, ny, w, h)))

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        # 방금 줄어든 레이어드 창에 이전 픽셀이 남을 수 있어 명시적으로 지운다.
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        p.fillRect(self.rect(), Qt.GlobalColor.transparent)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)

        if self._move_mode:
            # 반드시 필요하다. 투명 배경 창(WS_EX_LAYERED)은 Windows 가 픽셀 알파로
            # 클릭 판정을 하므로, 완전 투명한 픽셀은 클릭이 그대로 통과한다.
            # 이 반투명 배경이 없으면 글자 획 위를 정확히 눌러야만 드래그가 되고,
            # 가운데 빈 공간을 잡으면 아무 반응이 없다.
            p.fillRect(self.rect(), QColor(0, 0, 0, 96))

        fm = QFontMetricsF(self._font)
        baseline = self._pad + fm.ascent()
        x = float(self._pad)
        for text, color in self._parts():
            path = QPainterPath()
            # addText 는 좌상단이 아니라 베이스라인 기준이다.
            path.addText(x, baseline, self._font, text)

            pen = QPen(self._outline_color, self._outline_w)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(path)

            # 같은 path 를 채운다. stroke 후 drawText 로 채우면 서브픽셀이 어긋나 번진다.
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(color)
            p.drawPath(path)
            x += fm.horizontalAdvance(text)

        if self._move_mode:
            p.setPen(QPen(QColor(255, 255, 255, 230), 1, Qt.PenStyle.DashLine))
            p.setBrush(Qt.BrushStyle.NoBrush)
            # 오른쪽/아래 1px 을 줄이지 않으면 테두리가 창 밖에 그려져 안 보인다.
            p.drawRect(self.rect().adjusted(0, 0, -1, -1))
            self._paint_grip(p)
        p.end()

    def _paint_grip(self, p) -> None:
        """크기 조정 손잡이. 창 모서리 손잡이처럼 대각선 점 세 개로 그린다."""
        grip = self._grip_rect()
        # 손잡이는 앵커의 대각선 반대편에 있다.
        on_right = self._anchor.endswith("left")
        on_bottom = self._anchor.startswith("top")
        active = self._resize_from is not None

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 26 if not active else 80))
        p.drawRoundedRect(grip, 3, 3)

        p.setBrush(QColor(255, 255, 255, 235 if active else 175))
        for i in (1, 2, 3):
            off = i * 2.9
            gx = (grip.right() + 1 - off) if on_right else (grip.left() + off)
            gy = (grip.bottom() + 1 - off) if on_bottom else (grip.top() + off)
            p.drawEllipse(QPointF(gx, gy), 1.7, 1.7)

    def set_move_mode(self, on: bool) -> None:
        """이동 모드 전환.

        네이티브 WS_EX_TRANSPARENT 만 뒤집으면 안 된다. OS 는 클릭을 이 창으로
        보내지만 Qt 의 windowFlags() 에 WindowTransparentForInput 이 남아 있으면
        Qt 가 그 이벤트를 위젯까지 전달하지 않는다. 즉 점선은 보이는데 드래그가
        안 되는 상태가 된다. 그래서 Qt 플래그를 실제로 바꿔야 한다.

        플래그를 바꾸면 Qt 가 네이티브 창을 파괴하고 다시 만든다. 전환할 때 한 프레임
        깜빡이지만, 이동 모드 전환은 드물고 의도적인 동작이라 감수한다.
        """
        self._move_mode = bool(on)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, not on)
        self.setCursor(Qt.CursorShape.SizeAllCursor if on else Qt.CursorShape.ArrowCursor)

        flags = self.windowFlags()
        if on:
            flags &= ~Qt.WindowType.WindowTransparentForInput
        else:
            flags |= Qt.WindowType.WindowTransparentForInput

        if flags != self.windowFlags():
            geo = self.geometry()
            self.setWindowFlags(flags)  # 이 호출이 창을 숨기고 핸들을 새로 만든다
            self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
            self.setGeometry(geo)
            self.show()
            self.setGeometry(geo)  # 매핑된 뒤에야 반영되는 플랫폼이 있다
            if platform_win.IS_WINDOWS:
                # 핸들이 새로 만들어졌으므로 네이티브 스타일을 다시 건다.
                hwnd = int(self.winId())
                platform_win.set_no_activate(hwnd)
                platform_win.set_click_through(hwnd, not on)
            self.raise_()
        self.update()

    # --- 글자 크기 --------------------------------------------------------

    def set_font_limits(self, min_pt: int, max_pt: int) -> None:
        """상한은 OS 아이콘 라벨 글꼴의 2배다. app.py 가 실행 시점에 알려준다."""
        self._font_min = int(min_pt)
        self._font_max = int(max_pt)

    def set_font_size_pt(self, pt: float) -> None:
        pt = max(self._font_min, min(self._font_max, int(round(pt))))
        if pt == self._font_pt:
            return
        self._font_pt = pt
        self._font.setPointSizeF(float(pt))
        self._outline_w = max(1.5, pt * 0.14)
        self._pad = math.ceil(self._outline_w) + 1
        self._relayout()
        self.update()

    @property
    def font_size_pt(self) -> int:
        return self._font_pt

    @property
    def resizing(self) -> bool:
        return self._resize_from is not None

    def _grip_rect(self) -> QRect:
        """크기 조정 손잡이 영역. 앵커의 대각선 반대쪽 모서리에 둔다.

        앵커 모서리는 고정된 쪽이라 창이 커지고 작아질 때 실제로 움직이는 건
        대각선 반대편이다. 창을 모서리에서 끌어 늘이는 것과 같은 자리가 된다.
        """
        x = 0 if self._anchor.endswith("right") else max(0, self.width() - GRIP_SIZE)
        y = 0 if self._anchor.startswith("bottom") else max(0, self.height() - GRIP_SIZE)
        return QRect(x, y, GRIP_SIZE, GRIP_SIZE)

    def _outward_offsets(self, global_pos) -> tuple[float, float]:
        """앵커 모서리에서 바깥으로 나간 거리 (x, y). 앵커가 어느 모서리든 바깥이 양수다.

        크기 조정은 이 둘의 합으로 정한다. 그래야 PPT 의 모서리 핸들처럼
        **어느 방향으로 끌든** 고르게 반응한다.
        - 한 축에 투영하면 그 축과 수직으로 끌 때 아무 반응이 없다.
        - 앵커까지의 직선 거리를 쓰면 납작한 위젯에서 세로로 끌 때 거의 안 변한다
          (가로 성분이 거리의 대부분을 차지하기 때문이다).
        """
        self._ensure_anchor()
        dx = global_pos.x() - self._anchor_x
        dy = global_pos.y() - self._anchor_y
        if self._anchor.endswith("right"):
            dx = -dx
        if self._anchor.startswith("bottom"):
            dy = -dy
        return dx, dy

    # --- 마우스 ------------------------------------------------------------

    def mousePressEvent(self, event) -> None:
        if not (self._move_mode and event.button() == Qt.MouseButton.LeftButton):
            return
        global_pos = event.globalPosition().toPoint()
        if self._grip_rect().contains(event.position().toPoint()):
            ox, oy = self._outward_offsets(global_pos)
            self._resize_from = (self._font_pt, ox, oy)
            self._drag_offset = None
        else:
            self._resize_from = None
            self._drag_offset = global_pos - self.frameGeometry().topLeft()
        self.update()
        event.accept()

    def mouseDoubleClickEvent(self, event) -> None:
        """두 번째 빠른 누름은 press 가 아니라 더블클릭으로 온다.

        그대로 두면 손잡이를 연달아 잡았을 때 두 번째 드래그가 통째로 먹히고
        아무 반응이 없다. 눌림으로 똑같이 처리한다.
        """
        self.mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if not self._move_mode:
            return
        global_pos = event.globalPosition().toPoint()
        if self._resize_from is not None:
            start_pt, ox0, oy0 = self._resize_from
            ox, oy = self._outward_offsets(global_pos)
            # 앵커에서 멀어지면 커지고 가까워지면 작아진다. 가로로 끌든 세로로 끌든
            # 대각선으로 끌든 반응한다. 비례가 아니라 선형이라 미세 조정이 된다.
            moved = (ox - ox0) + (oy - oy0)
            self.set_font_size_pt(start_pt + moved / RESIZE_PX_PER_PT)
            event.accept()
        elif self._drag_offset is not None:
            self.move(global_pos - self._drag_offset)
            event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if self._resize_from is not None:
            self._resize_from = None
            self._recompute_anchor()
            self.update()
            self.font_size_changed.emit(self._font_pt)
            event.accept()
            return
        if not (self._move_mode and self._drag_offset is not None):
            return
        self._drag_offset = None
        self._recompute_anchor()
        self.moved.emit(self._anchor_x, self._anchor_y, self._anchor)
        event.accept()

    def _recompute_anchor(self) -> None:
        """놓인 자리에서 가장 가까운 화면 모서리를 앵커로 삼는다.

        그래야 단어가 길어질 때 화면 바깥이 아니라 안쪽으로 자란다.
        """
        g = self.geometry()
        screen = QGuiApplication.screenAt(g.center()) or QGuiApplication.primaryScreen()
        avail = screen.availableGeometry()
        horiz = "right" if g.center().x() > avail.center().x() else "left"
        vert = "bottom" if g.center().y() > avail.center().y() else "top"
        self._anchor = vert + "-" + horiz
        self._anchor_x = g.x() + g.width() if horiz == "right" else g.x()
        self._anchor_y = g.y() + g.height() if vert == "bottom" else g.y()

    def contextMenuEvent(self, event) -> None:
        if self.context_menu is not None:
            self.context_menu.exec(event.globalPos())
            event.accept()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        # Qt 6.8 은 WindowDoesNotAcceptFocus 를 WS_EX_NOACTIVATE 로 옮겨주지 않는다.
        # 네이티브 핸들이 생긴 지금 직접 건다. 안 하면 이동 모드 드래그 때 포커스를 뺏는다.
        if platform_win.IS_WINDOWS:
            platform_win.set_no_activate(int(self.winId()))
        handle = self.windowHandle()
        if handle is not None:
            try:
                handle.screenChanged.connect(lambda _s: self._relayout())
            except (RuntimeError, TypeError):
                pass

    def hover_rect(self) -> QRect:
        """마우스가 여기 머물면 뜻을 보여준다.

        마스코트 오버레이와 맞추기 위한 것이다. 텍스트 창은 글자 말고는 아무것도
        없으므로 창 전체가 그대로 판정 영역이다."""
        return self.geometry()

    @property
    def anchor_state(self):
        return self._anchor_x, self._anchor_y, self._anchor
