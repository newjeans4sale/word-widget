"""마스코트를 그리는 투명 오버레이 창.

`mascot.Mascot` 이 계산한 위치와 동작을 `sprites.SpriteSet` 의 그림으로 그린다.
이 파일은 그리기와 마우스만 다룬다 — 걷기 규칙은 mascot.py 에, 그림 규격은
sprites.py 에 있다.

**클릭 통과에 대해:** 별도의 마스크를 걸지 않는다. 투명 배경 창(WS_EX_LAYERED)은
Windows 가 픽셀 알파로 클릭 판정을 하므로, 캐릭터가 없는 여백은 그냥 통과한다
(overlay.py 의 이동 모드가 반투명 배경을 깔아야 잡히는 것도 같은 이유다).
setMask() 로 창 모양을 깎을 수도 있지만 그러면 그리기까지 1비트로 잘려서
애니메 캐릭터처럼 가장자리가 부드러운 그림이 톱니처럼 된다.
"""
from __future__ import annotations

import logging
import math

from PySide6.QtCore import QElapsedTimer, QPoint, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (QColor, QCursor, QFont, QFontMetricsF, QGuiApplication,
                           QPainter, QPainterPath, QPen)
from PySide6.QtWidgets import QWidget

import platform_win
import sprites as sprites_mod
from mascot import Mascot
from overlay import IS_MAC, clamp_to_screens, resolve_font_family

log = logging.getLogger(__name__)

# WindowTransparentForInput 이 없다 — 몸통은 클릭을 받아야 한다.
FLAGS = (Qt.WindowType.FramelessWindowHint
         | Qt.WindowType.WindowStaysOnTopHint
         | Qt.WindowType.Tool
         | Qt.WindowType.WindowDoesNotAcceptFocus
         | Qt.WindowType.NoDropShadowWindowHint)

TICK_MS = 62                 # 약 16fps. 더 올려도 도트 그림에서는 티가 안 난다
BUBBLE_GAP = 5               # 머리와 말풍선 사이
BUBBLE_TAIL = 7              # 꼬리 높이
BUBBLE_PAD_X = 9
BUBBLE_PAD_Y = 5
BUBBLE_RADIUS = 7
BUBBLE_MAX_W = 520           # 한 줄이 이보다 길면 말줄임
BUBBLE_LINE_GAP = 1          # 단어 줄과 뜻 줄 사이
ARROW_W = 22                 # 이전/다음 화살표 단추의 지름
ARROW_SIZE = 4               # 갈매기표 반쪽 크기
# 몸통이 이보다 좁으면 단추 둘이 캐릭터를 다 덮어버린다. 그럴 땐 안 그린다.
ARROW_MIN_BODY = ARROW_W * 3
# 몸통 높이의 어느 지점에 놓을지. 한가운데면 얼굴을 가려서 조금 내렸다.
ARROW_Y_RATIO = 0.62
CLICK_SLOP = 4               # 이만큼 안 움직였으면 드래그가 아니라 클릭


def available(sprites_dir) -> list[str]:
    """쓸 수 있는 캐릭터 이름. 비어 있으면 마스코트 모드를 켤 수 없다."""
    return sprites_mod.list_characters(sprites_dir)


class MascotOverlay(QWidget):
    """화면 바닥을 걸어다니며 단어를 말풍선으로 들고 다니는 창."""

    moved = Signal(int, int)          # 발밑 x, y — 사용자가 옮겨 놓았을 때만
    clicked = Signal()                # 몸통이나 말풍선을 클릭 (드래그가 아닌)
    prev_requested = Signal()         # 말풍선의 ‹
    next_requested = Signal()         # 말풍선의 ›
    font_size_changed = Signal(int)   # app.py 의 배선을 맞추기 위한 것. 쓰이지 않는다

    def __init__(self, cfg, sprites_dir):
        super().__init__(None)
        self.sprites_dir = sprites_dir
        self.context_menu = None      # 트레이를 못 쓸 때의 탈출구 (app.py 가 붙인다)

        self._word = ""
        self._meaning = None
        self._meaning_visible = False
        self._bubble_enabled = True
        self._font = QFont()
        self._text_color = QColor("#FFFFFF")
        self._meaning_color = QColor("#B9D4F5")
        self._bubble_bg = QColor(20, 20, 24, 210)
        self._bubble_border = QColor(255, 255, 255, 70)

        self._sprites: sprites_mod.SpriteSet | None = None
        self._pixmap = None
        self._body = QRect()          # 창 안에서 캐릭터가 차지하는 영역
        self._bubble = QRect()
        self._lines: list[tuple[str, QColor]] = []
        self._hovered = False
        self._wander_wanted = True
        self._can_prev = False
        self._can_next = True
        self._prev_rect = QRect()     # 창 좌표. 화살표가 없으면 빈 사각형
        self._next_rect = QRect()
        self._warnings: list[str] = []

        self._drag_grab = None        # (누른 지점, 그때의 발밑 좌표)
        self._drag_moved = 0.0

        self.mascot = Mascot()

        self.setWindowFlags(FLAGS)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        if IS_MAC:
            self.setAttribute(Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setMinimumSize(1, 1)

        self._clock = QElapsedTimer()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

        self.apply_config(cfg)

    # --- 설정 ---------------------------------------------------------

    def apply_config(self, cfg) -> None:
        self._warnings = []

        font = QFont(resolve_font_family(cfg.font_family))
        font.setPointSizeF(float(cfg.font_size_pt))
        font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
        self._font = font

        alpha = max(0.0, min(1.0, float(cfg.opacity)))
        self._text_color = QColor(cfg.color)
        self._text_color.setAlphaF(alpha)
        self._meaning_color = QColor("#B9D4F5")
        self._meaning_color.setAlphaF(max(0.35, alpha - 0.1))
        # 말풍선 배경은 글자보다 진해야 배경화면 위에서 글자가 읽힌다.
        self._bubble_bg = QColor(cfg.outline_color)
        self._bubble_bg.setAlphaF(min(1.0, alpha * 0.85 + 0.1))
        self._bubble_border = QColor(cfg.color)
        self._bubble_border.setAlphaF(alpha * 0.3)

        self._bubble_enabled = bool(getattr(cfg, "bubble", True))
        self.set_wander(bool(getattr(cfg, "mascot_wander", True)))

        # 위치를 먼저 정한다. 캐릭터를 먼저 불러오면 set_character 안의 _relayout 이
        # 아직 (0,0) 인 좌표로 창을 잡아서, 화면 밖으로 판정돼 한 번 튕겨 나갔다 온다.
        x = getattr(cfg, "mascot_x", None)
        y = getattr(cfg, "mascot_y", None)
        if x is not None and y is not None:
            self.mascot.place(float(x), float(y))
        else:
            self._place_default()

        self.set_character(getattr(cfg, "character", "dog-00"),
                           float(getattr(cfg, "mascot_scale", 1.0)))
        self._relayout()

    def set_character(self, name: str, scale: float | None = None) -> bool:
        """캐릭터를 바꾼다. 성공하면 True."""
        chosen, warning = sprites_mod.pick_character(self.sprites_dir, name)
        if warning:
            log.warning("%s", warning)
            self._warnings.append(warning)
        if chosen is None:
            return False
        if scale is None:
            scale = self._sprites.scale if self._sprites else 1.0

        spec = sprites_mod.load_spec(self.sprites_dir / chosen)
        if spec is None:
            return False
        self._sprites = sprites_mod.SpriteSet(spec, scale)
        # 그림이 없는 동작은 고르지 않게 한다. 폴백으로 서 있는 그림이 나오면
        # 보는 사람 눈에는 몇 초 동안 앱이 멈춘 것처럼 보인다.
        self.mascot.set_available({a for a in spec.actions})
        self._relayout()
        return True

    @property
    def character(self) -> str | None:
        return self._sprites.name if self._sprites else None

    @property
    def warnings(self) -> list[str]:
        return list(self._warnings)

    def set_wander(self, on: bool) -> None:
        """트레이의 '산책'. 호버로 잠시 멈춘 것과 구분해서 기억해 둔다."""
        self._wander_wanted = bool(on)
        self._apply_wander()

    def set_hovered(self, on: bool) -> None:
        """커서가 캐릭터 위에 있는 동안은 걷지 않는다.

        뜻을 읽는 중에 걸어서 커서 밑을 빠져나가면 말풍선이 닫혀 버린다.
        멈춰 세우면 마우스를 올려둔 동안 계속 읽을 수 있다.
        """
        on = bool(on)
        if on == self._hovered:
            return
        self._hovered = on
        self._apply_wander()
        self._relayout()      # 화살표가 나타나거나 사라진다

    def _apply_wander(self) -> None:
        self.mascot.set_wander(self._wander_wanted and not self._hovered)

    def set_scale(self, scale: float) -> None:
        if self._sprites:
            self._sprites.set_scale(scale)
            self._relayout()

    # --- app.py 가 기대하는 인터페이스 -----------------------------------

    def set_word(self, word: str, meaning: str | None = None) -> None:
        self._word = word or ""
        self._meaning = meaning
        # 커서를 올려 둔 채 화살표로 단어를 넘기는 중이라면 뜻을 계속 보여준다.
        # 매번 감추면 넘길 때마다 뜻이 깜빡였다가 다시 뜬다.
        self._meaning_visible = self._hovered and meaning is not None
        self._relayout()

    def set_history_state(self, can_prev: bool, can_next: bool) -> None:
        """화살표를 흐리게 할지 정한다. app.py 가 단어를 바꿀 때마다 알려준다."""
        can_prev, can_next = bool(can_prev), bool(can_next)
        if (can_prev, can_next) == (self._can_prev, self._can_next):
            return
        self._can_prev, self._can_next = can_prev, can_next
        self.update()

    def set_meaning_visible(self, on: bool) -> None:
        on = bool(on) and self._meaning is not None
        if on == self._meaning_visible:
            return
        self._meaning_visible = on
        self._relayout()

    @property
    def has_meaning(self) -> bool:
        return bool(self._meaning)

    @property
    def meaning_visible(self) -> bool:
        return self._meaning_visible

    def hover_rect(self) -> QRect:
        """마우스가 여기 머물면 뜻과 화살표를 보여준다.

        몸통만으로 잡으면 화살표를 누르러 올라가는 순간 호버가 풀려 화살표가
        사라진다. 말풍선까지 포함해야 눌러볼 수 있다.
        """
        area = self._body.united(self._bubble) if not self._bubble.isEmpty() else self._body
        return QRect(self.mapToGlobal(area.topLeft()), area.size())

    @property
    def position(self) -> tuple[int, int]:
        state = self.mascot.state
        return int(round(state.x)), int(round(state.y))

    # 텍스트 모드에만 있는 것들. app.py 가 모드를 몰라도 되게 조용히 받아 넘긴다.
    def set_move_mode(self, on: bool) -> None:
        pass

    def set_font_limits(self, min_pt: int, max_pt: int) -> None:
        pass

    def set_font_size_pt(self, pt: float) -> None:
        pass

    # --- 화면 계산 ------------------------------------------------------

    def _screen_bounds(self) -> tuple[float, float, float]:
        """캐릭터의 발밑이 갈 수 있는 (왼쪽, 오른쪽, 바닥).

        바닥은 availableGeometry 라 작업표시줄 위에 정확히 선다.
        """
        state = self.mascot.state
        probe = QPoint(int(state.x), int(state.y) - 1)
        screen = QGuiApplication.screenAt(probe) or QGuiApplication.primaryScreen()
        avail = screen.availableGeometry()
        half = (self._body.width() or 32) / 2.0
        return (avail.left() + half, avail.right() + 1 - half, float(avail.bottom() + 1))

    def _place_default(self) -> None:
        avail = QGuiApplication.primaryScreen().availableGeometry()
        self.mascot.place(avail.center().x(), avail.bottom() + 1)

    # --- 레이아웃 -------------------------------------------------------

    def _arrows_visible(self) -> bool:
        """커서를 올려 둔 동안에만 ‹ › 를 보여준다. 평소에는 단어만 떠 있어야 한다."""
        return bool(self._hovered and self._bubble_enabled and self._word)

    def _bubble_lines(self) -> list[tuple[str, QColor]]:
        """말풍선에 그릴 줄들. 뜻은 단어와 같은 줄에 붙이지 않고 아래로 내린다.

        한 줄에 이어 붙이면 말풍선이 화면을 가로질러 버리고, 길이를 제한하면
        정작 읽고 싶은 뜻이 말줄임으로 잘린다. 줄을 나누면 둘 다 온전히 보인다.
        """
        if not self._bubble_enabled or not self._word:
            return []
        fm = QFontMetricsF(self._font)
        limit = BUBBLE_MAX_W - 2 * BUBBLE_PAD_X

        def fit(text: str) -> str:
            if fm.horizontalAdvance(text) <= limit:
                return text
            return fm.elidedText(text, Qt.TextElideMode.ElideRight, limit)

        lines = [(fit(self._word), self._text_color)]
        if self._meaning_visible and self._meaning:
            lines.append((fit(self._meaning), self._meaning_color))
        return lines

    def _relayout(self) -> None:
        """창 크기와 내부 배치를 다시 잡는다. 그림이나 글자가 바뀔 때만 부른다."""
        if self._sprites is None:
            return

        state = self.mascot.state
        action = self._sprites.resolve(state.action)
        index = self.mascot.frame_index(action.fps, action.frame_count)
        self._pixmap = self._sprites.frame(state.action, index, state.facing)

        body_w = self._pixmap.width() if self._pixmap else 32
        body_h = self._pixmap.height() if self._pixmap else 32

        # 그릴 줄을 여기서 확정해 두고 paintEvent 는 그대로 쓴다.
        # 재는 쪽과 그리는 쪽이 따로 계산하면 한쪽만 바뀌었을 때 글자가 잘린다.
        self._lines = self._bubble_lines()
        arrows = self._arrows_visible()
        if self._lines:
            fm = QFontMetricsF(self._font)
            text_w = max(fm.horizontalAdvance(t) for t, _ in self._lines)
            line_h = fm.height() + BUBBLE_LINE_GAP
            bubble_w = math.ceil(text_w) + 2 * BUBBLE_PAD_X
            bubble_h = math.ceil(line_h * len(self._lines)) + 2 * BUBBLE_PAD_Y
            top = bubble_h + BUBBLE_TAIL + BUBBLE_GAP
        else:
            bubble_w = bubble_h = 0
            top = 0

        win_w = max(body_w, bubble_w)
        win_h = top + body_h
        self._body = QRect((win_w - body_w) // 2, top, body_w, body_h)
        self._bubble = (QRect((win_w - bubble_w) // 2, 0, bubble_w, bubble_h)
                        if bubble_w else QRect())
        # 화살표는 말풍선이 아니라 **몸통 위**에 얹는다. 말풍선은 단어 길이에 따라
        # 폭이 변해 창이 리사이즈되고, 그러면 누르는 도중에 단추가 커서 밑에서
        # 빠져나간다. 몸통은 발밑 기준으로 늘 같은 자리에 있어 흔들리지 않는다.
        if arrows and self._body.width() >= ARROW_MIN_BODY:
            b = self._body
            size = min(ARROW_W, b.height())
            y = b.top() + int((b.height() - size) * ARROW_Y_RATIO)
            self._prev_rect = QRect(b.left(), y, size, size)
            self._next_rect = QRect(b.right() + 1 - size, y, size, size)
        else:
            self._prev_rect = QRect()
            self._next_rect = QRect()

        self._apply_geometry(win_w, win_h)

    def _apply_geometry(self, win_w: int, win_h: int) -> None:
        state = self.mascot.state
        x = int(round(state.x - win_w / 2.0))
        y = int(round(state.y - win_h))
        rect = QRect(x, y, max(1, win_w), max(1, win_h))
        if self.size() != rect.size():
            # 크기가 바뀔 때만 setGeometry. 매 프레임 resize 하면 레이어드 창이 비싸다.
            self.setGeometry(clamp_to_screens(rect))
        else:
            self.move(rect.topLeft())

    # --- 매 틱 ---------------------------------------------------------

    def _tick(self) -> None:
        if self._sprites is None:
            return
        dt = self._clock.restart() / 1000.0
        before = (self.mascot.action, self._body.size())

        self.mascot.update(dt, self._screen_bounds())

        state = self.mascot.state
        action = self._sprites.resolve(state.action)
        index = self.mascot.frame_index(action.fps, action.frame_count)
        pixmap = self._sprites.frame(state.action, index, state.facing)

        if pixmap is not self._pixmap or before[0] != state.action:
            # 그림이 바뀌면 창 크기도 달라질 수 있다 (앉으면 낮아진다).
            self._pixmap = pixmap
            self._relayout()
        else:
            self._apply_geometry(self.width(), self.height())
        self.update()

    # --- 마우스 ---------------------------------------------------------

    def mousePressEvent(self, event) -> None:
        """드래그 기준점은 event 가 아니라 OS 커서에서 받는다.

        끌고 있는 동안 창이 커서 밑에서 계속 움직이는데, event.globalPosition() 은
        창 원점을 거쳐 계산되므로 창이 막 움직인 직후에는 한 프레임 뒤처진 값이 온다.
        그 값으로 위치를 정하면 캐릭터가 커서를 따라오다 말고 뒤처진다(실제로 220px
        끌었을 때 66px 만 따라왔다). QCursor.pos() 는 OS 에 직접 물으므로 창과 무관하다.
        """
        if event.button() != Qt.MouseButton.LeftButton:
            event.ignore()
            return

        # 화살표를 누른 것이라면 드래그를 시작하지 않는다. 눌렀다 떼는 사이에
        # 캐릭터가 손을 따라오면 단어를 넘기려다 위치만 옮기게 된다.
        pos = event.position().toPoint()
        if not self._prev_rect.isEmpty():
            if self._prev_rect.contains(pos):
                if self._can_prev:
                    self.prev_requested.emit()
                event.accept()
                return
            if self._next_rect.contains(pos):
                if self._can_next:
                    self.next_requested.emit()
                event.accept()
                return

        state = self.mascot.state
        cursor = QCursor.pos()
        self._drag_grab = (cursor, (state.x - cursor.x(), state.y - cursor.y()))
        self._drag_moved = 0.0
        self.mascot.grab()
        self.setCursor(Qt.CursorShape.ClosedHandCursor)
        event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self._drag_grab is None:
            event.ignore()
            return
        origin, (dx, dy) = self._drag_grab
        cursor = QCursor.pos()
        self._drag_moved = max(self._drag_moved,
                               math.hypot(cursor.x() - origin.x(),
                                          cursor.y() - origin.y()))
        self.mascot.drag_to(cursor.x() + dx, cursor.y() + dy)
        self._relayout()
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if self._drag_grab is None:
            event.ignore()
            return
        origin, (dx, dy) = self._drag_grab
        # 놓는 순간의 커서를 한 번 더 반영한다. 마지막 이동 이벤트와 버튼 놓기 사이에
        # 한 메시지가 밀리면 캐릭터가 손보다 조금 뒤에서 떨어진다.
        cursor = QCursor.pos()
        self.mascot.drag_to(cursor.x() + dx, cursor.y() + dy)
        self._drag_moved = max(self._drag_moved,
                               math.hypot(cursor.x() - origin.x(),
                                          cursor.y() - origin.y()))
        self._drag_grab = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.mascot.release()
        if self._drag_moved <= CLICK_SLOP:
            self.clicked.emit()
        else:
            x, y = self.position
            self.moved.emit(x, y)
        event.accept()

    def contextMenuEvent(self, event) -> None:
        if self.context_menu is not None:
            self.context_menu.exec(event.globalPos())
            event.accept()

    # --- 그리기 ---------------------------------------------------------

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)

        # 줄어든 레이어드 창에 이전 픽셀이 남을 수 있어 명시적으로 지운다.
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        p.fillRect(self.rect(), Qt.GlobalColor.transparent)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)

        if self._pixmap is not None:
            p.drawPixmap(self._body.topLeft(), self._pixmap)
        if not self._prev_rect.isEmpty():
            self._paint_arrow(p, self._prev_rect, -1, self._can_prev)
            self._paint_arrow(p, self._next_rect, +1, self._can_next)
        if not self._bubble.isEmpty():
            self._paint_bubble(p)
        p.end()

    def _paint_bubble(self, p) -> None:
        box = QRectF(self._bubble)
        path = QPainterPath()
        path.addRoundedRect(box, BUBBLE_RADIUS, BUBBLE_RADIUS)

        # 꼬리는 머리 쪽을 가리킨다. 몸통 중앙에 맞추되 말풍선 밖으로 나가지 않게 한다.
        tip_x = min(max(self._body.center().x(), box.left() + BUBBLE_RADIUS + 6),
                    box.right() - BUBBLE_RADIUS - 6)
        tail = QPainterPath()
        tail.moveTo(tip_x - 6, box.bottom() - 1)
        tail.lineTo(tip_x + 6, box.bottom() - 1)
        tail.lineTo(tip_x, box.bottom() + BUBBLE_TAIL)
        tail.closeSubpath()
        path = path.united(tail)

        p.setPen(QPen(self._bubble_border, 1))
        p.setBrush(self._bubble_bg)
        p.drawPath(path)

        fm = QFontMetricsF(self._font)
        p.setFont(self._font)
        p.setBrush(Qt.BrushStyle.NoBrush)
        line_h = fm.height() + BUBBLE_LINE_GAP
        left = box.left() + BUBBLE_PAD_X
        width = box.width() - 2 * BUBBLE_PAD_X
        y = box.top() + BUBBLE_PAD_Y
        for text, color in self._lines:
            p.setPen(color)
            p.drawText(QRectF(left, y, width, line_h),
                       int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                       text)
            y += line_h

    def _paint_arrow(self, p, rect: QRect, direction: int, enabled: bool) -> None:
        """갈매기표를 선으로 그린다. 글꼴에 있는 글자를 쓰면 글꼴마다 크기가 달라진다.

        캐릭터 그림 위에 얹히므로 뒤에 어두운 원을 깐다. 털색이 밝은 강아지
        (white, golden) 위에서는 선만으로는 보이지 않는다.
        """
        # 배경은 흐리게 하지 않는다. 단추가 있다는 것 자체는 보여야
        # 왜 눌러도 반응이 없는지 알 수 있다 (흐려진 갈매기표가 그 답이다).
        backing = QColor(self._bubble_bg)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(backing)
        p.drawEllipse(rect)

        color = QColor(self._text_color)
        color.setAlphaF(color.alphaF() * (1.0 if enabled else 0.25))
        pen = QPen(color, 2.0)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)

        # direction 은 화살표가 가리키는 쪽이다. 꼭짓점이 그쪽으로 가야 한다.
        cx, cy = rect.center().x() + 1, rect.center().y() + 1
        tip = cx + direction * ARROW_SIZE * 0.6
        back = cx - direction * ARROW_SIZE * 0.6
        path = QPainterPath()
        path.moveTo(back, cy - ARROW_SIZE)
        path.lineTo(tip, cy)
        path.lineTo(back, cy + ARROW_SIZE)
        p.drawPath(path)

    # --- 창 수명 ---------------------------------------------------------

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if platform_win.IS_WINDOWS:
            # Qt 6.8 은 WindowDoesNotAcceptFocus 를 WS_EX_NOACTIVATE 로 옮겨주지 않는다.
            # 이게 없으면 캐릭터를 잡는 순간 편집기가 포커스를 잃는다.
            platform_win.set_no_activate(int(self.winId()))
        self._clock.restart()
        self._timer.start(TICK_MS)

    def hideEvent(self, event) -> None:
        # 전체화면 앱 위에서 숨어 있는 동안 CPU 를 쓰지 않는다.
        self._timer.stop()
        super().hideEvent(event)
