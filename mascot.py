"""마스코트의 움직임. Qt 도 시간도 난수도 직접 만들지 않는다.

`update(dt, bounds)` 만 호출하면 위치와 동작이 갱신된다. 시간과 난수를 밖에서
주입받으므로 테스트에서 dt 와 시드를 고정해 놓고 몇 분치를 즉시 돌려볼 수 있다.

좌표계는 **발밑** 기준이다. 스프라이트 크기가 동작마다 달라도(앉으면 낮아진다)
발이 딛는 면에 붙어 있게 하려면 이 기준이어야 한다.

딛는 면(surface)은 넷이다. 바닥에서는 발밑이 (x, 바닥), 왼쪽 벽에서는 (왼쪽 끝, y),
오른쪽 벽에서는 (오른쪽 끝, y), 천장에서는 (x, 천장)이다. 벽과 천장에서는 그리는
쪽이 몸을 돌려 발이 그 면에 닿게 한다.

벽과 천장에서 스스로 손을 놓지는 않는다. 떨어지는 것은 사용자가 잡았다 놓았을 때,
산책을 껐을 때, 화면이 바뀌어 딛던 면이 사라졌을 때뿐이다.
"""
from __future__ import annotations

import random
from dataclasses import dataclass

IDLE = "idle"
WALK = "walk"
RUN = "run"
SIT = "sit"
LIE = "lie"
SLEEP = "sleep"
BEG = "beg"
BARK = "bark"
FALL = "fall"
DRAG = "drag"
JUMP = "jump"

FLOOR = "floor"
LEFT = "left"
RIGHT = "right"
CEILING = "ceiling"
WALLS = (LEFT, RIGHT)

# 스스로 오갈 수 있는 동작. FALL/DRAG 는 사용자가 건드릴 때만 들어간다.
WANDER_ACTIONS = (IDLE, WALK, RUN, SIT, LIE, SLEEP, BEG, BARK)

# 가로로 움직이는 동작과 그 속도 배수.
MOVING = {WALK: 1.0, RUN: 2.6}

# 동작이 얼마나 이어지는지 (초). 매번 이 범위에서 균등하게 뽑는다.
DURATIONS = {
    IDLE: (1.0, 4.0),
    WALK: (2.0, 6.0),
    RUN: (1.2, 3.5),      # 짧게 뛰고 만다. 오래 뛰면 화면 끝을 계속 오간다
    SIT: (3.0, 8.0),
    LIE: (5.0, 15.0),
    SLEEP: (10.0, 30.0),
    BEG: (1.5, 3.5),
    BARK: (0.8, 1.6),
}

# 동작이 끝났을 때 다음에 뭘 할지. (동작, 가중치)
# 쉬는 쪽으로 흐르되 가끔 눈에 띄는 짓을 하게 한다. 짖기/두 발로 서기의 가중치가
# 낮은 것은 일부러다 — 자주 나오면 시선을 계속 빼앗는다.
NEXT = {
    IDLE: ((WALK, 6), (SIT, 3), (RUN, 1), (BARK, 1), (BEG, 1), (IDLE, 1)),
    WALK: ((IDLE, 5), (WALK, 3), (SIT, 2), (RUN, 2)),
    RUN: ((WALK, 4), (IDLE, 3)),
    SIT: ((IDLE, 5), (SLEEP, 2), (LIE, 2), (SIT, 2), (BEG, 1)),
    LIE: ((SLEEP, 3), (IDLE, 3), (SIT, 2)),
    SLEEP: ((LIE, 2), (IDLE, 1)),
    BEG: ((IDLE, 2), (BARK, 1)),
    BARK: ((IDLE, 3), (WALK, 1)),
}

# 벽과 천장에서 할 수 있는 것. 벽에서 앉거나 자는 모습은 돌려 놓으면 어색하다.
SURFACE_ACTIONS = {
    LEFT: (IDLE, WALK),
    RIGHT: (IDLE, WALK),
    CEILING: (IDLE, WALK, RUN),
}
NEXT_WALL = {
    IDLE: ((WALK, 5), (IDLE, 1)),
    WALK: ((WALK, 3), (IDLE, 2)),
}
NEXT_CEILING = {
    IDLE: ((WALK, 5), (RUN, 1), (IDLE, 1)),
    WALK: ((WALK, 3), (IDLE, 2), (RUN, 1)),
    RUN: ((WALK, 3), (IDLE, 2)),
}
# 바닥에서 벽으로 뛰어오르는 가중치. 바닥의 NEXT 에 더해진다.
# 아래 확률들과 함께 바닥 1/3, 벽 2/5, 천장 1/4 쯤에 머물도록 맞춘 값이다.
JUMP_WEIGHT = {IDLE: 1, WALK: 1, RUN: 1}

CLIMB_SPEED = 0.7          # 벽을 기는 속도 (걷기 대비)
JUMP_VX = 420.0            # 뛰어오를 때의 가로 속도 (px/s)
JUMP_RANGE = 700.0         # 벽이 이보다 멀면 뛰지 않는다
JUMP_HEIGHT = (0.2, 0.6)   # 벽의 어느 높이에 붙을지 (화면 높이 대비)
# 끝에 닿았을 때 다음 면으로 넘어갈 확률. 나머지는 돌아선다.
P_CLIMB = 0.3              # 바닥 끝 → 벽
P_CORNER = 0.85            # 벽 위 → 천장, 천장 끝 → 벽
P_STEP_DOWN = 0.95         # 벽 아래 → 바닥
KEEP_DIRECTION = 0.75      # 벽·천장에서 다시 걸을 때 가던 쪽을 유지할 확률

# 타이머가 밀리거나 절전에서 깨어나면 dt 가 몇 초씩 들어온다. 그대로 적분하면
# 캐릭터가 화면을 가로질러 순간이동하거나 바닥을 뚫는다. 한 틱의 최대치를 정해 둔다.
MAX_DT = 0.25


@dataclass(frozen=True)
class Area:
    """캐릭터가 다닐 수 있는 화면 영역. 발밑 기준점이 닿을 수 있는 가장자리다.

    half 는 딛는 면을 따라 잰 몸 길이의 절반이다. 모서리에서 몸이 화면 밖으로
    나가지 않도록 발밑을 그만큼 안쪽에 둔다.
    top 이 None 이면 벽과 천장이 없는 것으로 보고 바닥만 다닌다.
    """

    left: float
    top: float | None
    right: float
    bottom: float
    half: float = 0.0

    @property
    def climbable(self) -> bool:
        return self.top is not None and self.bottom - self.top > 4 * self.half


def as_area(bounds) -> Area:
    """(left, right, floor) 세 값이면 벽 없는 바닥으로 본다."""
    if isinstance(bounds, Area):
        return bounds
    left, right, floor = bounds
    return Area(left=left, top=None, right=right, bottom=floor)


@dataclass
class MascotState:
    """그리는 쪽이 알아야 하는 전부."""

    x: float
    y: float
    action: str
    facing: int      # 바닥·천장: +1 오른쪽으로, -1 왼쪽으로. 벽: +1 위로, -1 아래로
    elapsed: float   # 현재 동작이 시작된 뒤 흐른 시간. 프레임 번호는 이것으로 계산한다
    surface: str = FLOOR


class Mascot:
    def __init__(self, rng: random.Random | None = None, *,
                 walk_speed: float = 40.0, gravity: float = 1400.0,
                 available=None):
        self.rng = rng if rng is not None else random.Random()
        self.walk_speed = float(walk_speed)
        self.gravity = float(gravity)

        self.x = 0.0
        self.y = 0.0
        self.action = IDLE
        self.facing = 1
        self.elapsed = 0.0
        self.surface = FLOOR

        self._remaining = 0.0
        self._vx = 0.0
        self._vy = 0.0
        self._wander = True
        self._held = False
        self._area: Area | None = None
        self._available = set(WANDER_ACTIONS)
        if available is not None:
            self.set_available(available)
        self._begin(IDLE)

    # --- 바깥에서 알려주는 것들 --------------------------------------

    def set_available(self, actions) -> None:
        """그림이 실제로 있는 동작만 고르게 한다.

        앉는 그림이 없는 캐릭터에게 SIT 을 시키면 폴백 때문에 서 있는 그림이 나오고,
        보는 사람 눈에는 몇 초 동안 아무 일도 일어나지 않는 것처럼 보인다.
        """
        usable = {a for a in actions if a in WANDER_ACTIONS}
        usable.add(IDLE)      # idle 은 항상 있다 (sprites.load_spec 이 보장한다)
        self._available = usable
        if self.action in WANDER_ACTIONS and self.action not in usable:
            self._begin(IDLE)

    def set_wander(self, on: bool) -> None:
        """산책 끄기. 끄면 그 자리에 바로 선다 — 걷던 것을 마저 걷게 하면
        껐는데도 계속 움직여서 고장난 것처럼 보인다. 벽이나 천장에 있었다면
        바닥으로 내려와 선다."""
        on = bool(on)
        if on == self._wander:
            return
        self._wander = on
        if on:
            return
        if self.surface != FLOOR or self.action == JUMP:
            self._drop()
        elif self.action in WANDER_ACTIONS:
            self._begin(IDLE)

    def set_held(self, on: bool) -> None:
        """커서를 올려 둔 동안 그 자리에 멈춰 있게 한다. 벽이나 천장에서도 붙은 채로 있다."""
        on = bool(on)
        if on == self._held:
            return
        self._held = on
        if on and self.action in MOVING:
            self._begin(IDLE)

    @property
    def wandering(self) -> bool:
        return self._wander

    def place(self, x: float, y: float) -> None:
        """위치를 그냥 놓는다 (설정에서 복원할 때). 늘 바닥 위의 점으로 본다."""
        self.x, self.y = float(x), float(y)
        self.surface = FLOOR
        self._vx = self._vy = 0.0

    # --- 마우스 ------------------------------------------------------

    def grab(self) -> None:
        if self.action != DRAG:
            self.surface = FLOOR
            self._begin(DRAG)
            self._vx = self._vy = 0.0

    def drag_to(self, x: float, y: float) -> None:
        if self.action == DRAG:
            self.x, self.y = float(x), float(y)

    def release(self) -> None:
        """놓으면 그 자리에서 아래로 똑바로 떨어진다."""
        if self.action == DRAG:
            self._begin(FALL)
            self._vx = self._vy = 0.0

    @property
    def dragging(self) -> bool:
        return self.action == DRAG

    # --- 매 틱 -------------------------------------------------------

    def update(self, dt: float, bounds) -> None:
        """bounds 는 Area, 또는 (left, right, floor) — 벽 없는 바닥."""
        area = as_area(bounds)
        left, right = area.left + area.half, area.right - area.half
        if right < left:
            left = right = (left + right) / 2.0
        floor = area.bottom
        self._area = area
        dt = min(max(float(dt), 0.0), MAX_DT)

        self.elapsed += dt
        self._remaining -= dt

        if self.action == DRAG:
            return                      # 손에 들려 있는 동안은 물리도 타이머도 없다

        if self.action == FALL:
            self._fall(dt, floor)
        elif self.action == JUMP:
            self._jump(dt, area, left, right)
        elif self.surface == FLOOR:
            if self.y != floor:
                # 화면 배치가 바뀌었다 (해상도 변경, 작업표시줄 자동숨김, 모니터 이동).
                # 공중에 뜬 채로 두지 않고 떨어뜨린다.
                self._begin(FALL)
                self._fall(dt, floor)
            elif self.action in MOVING:
                self._walk(dt, area, left, right)
        else:
            self._on_surface(dt, area, left, right)

        if self.surface in (FLOOR, CEILING) and self.action != JUMP:
            self.x = min(max(self.x, left), right)

        if self.action not in (FALL, DRAG, JUMP) and self._remaining <= 0.0:
            self._begin(self._choose_next())

    # --- 바닥 --------------------------------------------------------

    def _walk(self, dt: float, area: Area, left: float, right: float) -> None:
        speed = self.walk_speed * MOVING.get(self.action, 1.0)
        self.x += self.facing * speed * dt
        if self.x <= left or self.x >= right:
            wall = LEFT if self.x <= left else RIGHT
            self.x = left if wall == LEFT else right
            if self._can_climb(area) and self.rng.random() < P_CLIMB:
                self._attach(wall, area.bottom - area.half, area, facing=1)
            else:
                self.facing = 1 if wall == LEFT else -1

    def _fall(self, dt: float, floor: float) -> None:
        self.surface = FLOOR
        if self.y > floor:
            # 바닥이 올라왔다 (더 작은 화면으로 옮겨졌다). 떨어뜨릴 게 아니라 끌어올린다.
            self.y, self._vy = floor, 0.0
            self._begin(IDLE)
            return
        self._vy += self.gravity * dt
        self.y += self._vy * dt
        if self.y >= floor:
            self.y, self._vy = floor, 0.0
            self._begin(IDLE)

    def _start_jump(self) -> bool:
        """가까운 벽으로 뛰어오른다. 벽이 너무 멀면 False."""
        area = self._area
        if area is None or not self._can_climb(area):
            return False
        to_left = self.x - area.left
        to_right = area.right - self.x
        wall, dist = (LEFT, to_left) if to_left <= to_right else (RIGHT, to_right)
        if dist > JUMP_RANGE:
            return False
        dist = max(dist, 1.0)
        height = area.bottom - area.top
        lo, hi = JUMP_HEIGHT
        rise = self.rng.uniform(lo, hi) * height
        rise = min(rise, height - 2 * area.half)
        t = dist / JUMP_VX
        self.facing = -1 if wall == LEFT else 1
        self._vx = self.facing * JUMP_VX
        self._vy = -(rise / t + 0.5 * self.gravity * t)
        self.action = JUMP
        self.elapsed = 0.0
        self._remaining = float("inf")
        return True

    def _jump(self, dt: float, area: Area, left: float, right: float) -> None:
        self._vy += self.gravity * dt
        self.x += self._vx * dt
        self.y += self._vy * dt
        if self.x <= area.left or self.x >= area.right:
            wall = LEFT if self.x <= area.left else RIGHT
            self._attach(wall, self.y, area, facing=1, action=IDLE)
        elif area.top is not None and self.y <= area.top:
            self.surface = CEILING
            self.y = area.top
            self.x = min(max(self.x, left), right)
            self._vx = self._vy = 0.0
            self._begin(IDLE)
        elif self.y >= area.bottom:
            self.y = area.bottom
            self.x = min(max(self.x, left), right)
            self._vx = self._vy = 0.0
            self.surface = FLOOR
            self._begin(IDLE)

    # --- 벽과 천장 ----------------------------------------------------

    def _attach(self, wall: str, y: float, area: Area, *, facing: int,
                action: str = WALK) -> None:
        self.surface = wall
        self.x = area.left if wall == LEFT else area.right
        self.y = min(max(y, area.top + area.half), area.bottom - area.half)
        self._vx = self._vy = 0.0
        self._begin(action)
        self.facing = facing

    def _on_surface(self, dt: float, area: Area, left: float, right: float) -> None:
        if not area.climbable:
            self._drop()                  # 벽이 없는 화면으로 옮겨졌다
            return
        if self.surface == CEILING:
            self.y = area.top
            if self.action in MOVING:
                speed = self.walk_speed * MOVING[self.action]
                self.x += self.facing * speed * dt
                if self.x <= left or self.x >= right:
                    wall = LEFT if self.x <= left else RIGHT
                    self.x = left if wall == LEFT else right
                    if self.rng.random() < P_CORNER:
                        self._attach(wall, area.top + area.half, area, facing=-1)
                    else:
                        self.facing = -self.facing
            return

        # 벽. 화면이 바뀌었으면 새 가장자리에 다시 붙인다.
        self.x = area.left if self.surface == LEFT else area.right
        top, bottom = area.top + area.half, area.bottom - area.half
        self.y = min(max(self.y, top), bottom)
        if self.action not in MOVING:
            return
        self.y -= self.facing * self.walk_speed * CLIMB_SPEED * dt
        if self.y <= top:
            self.y = top
            if self.rng.random() < P_CORNER:
                self.surface = CEILING
                self.x = left if self.x <= area.left else right
                self.y = area.top
                self.facing = 1 if self.x == left else -1
            else:
                self.facing = -1
        elif self.y >= bottom:
            self.y = bottom
            if self.rng.random() < P_STEP_DOWN:
                wall = self.surface
                self.surface = FLOOR
                self.x = left if wall == LEFT else right
                self.y = area.bottom
                self.facing = 1 if wall == LEFT else -1
            else:
                self.facing = 1

    def _drop(self) -> None:
        """벽이나 천장에서 바닥으로 똑바로 떨어뜨린다."""
        area = self._area
        if area is not None:
            if self.surface == LEFT:
                self.x = area.left + area.half
            elif self.surface == RIGHT:
                self.x = area.right - area.half
        self.surface = FLOOR
        self._vx = self._vy = 0.0
        self._begin(FALL)

    def _can_climb(self, area: Area) -> bool:
        return self._wander and not self._held and area.climbable

    # --- 동작 전환 ----------------------------------------------------

    def _begin(self, action: str) -> None:
        self.action = action
        self.elapsed = 0.0
        if action in DURATIONS:
            lo, hi = DURATIONS[action]
            self._remaining = self.rng.uniform(lo, hi)
            if action in MOVING:
                # 움직이기 시작할 때만 방향을 새로 뽑는다. 매 틱 뽑으면 제자리에서 떤다.
                # 벽과 천장에서는 대개 가던 쪽으로 계속 간다. 매번 새로 뽑으면 한 자리에서
                # 오르락내리락만 하다가 끝까지 가지 못한다.
                if self.surface == FLOOR or self.rng.random() >= KEEP_DIRECTION:
                    self.facing = self.rng.choice((-1, 1))
        else:
            self._remaining = float("inf")

    def _choose_next(self) -> str:
        if not self._wander or self._held:
            return IDLE
        if self.surface == FLOOR:
            table = NEXT.get(self.action, NEXT[IDLE])
            usable = self._available
        else:
            table = (NEXT_CEILING if self.surface == CEILING else NEXT_WALL)
            table = table.get(self.action, table[IDLE])
            usable = self._available & set(SURFACE_ACTIONS[self.surface])
        choices = [(a, w) for a, w in table if a in usable]
        jump = JUMP_WEIGHT.get(self.action, 0) if self.surface == FLOOR else 0
        if jump and self._area is not None and self._can_climb(self._area):
            choices.append((JUMP, jump))
        if not choices:
            return IDLE
        actions = [a for a, _ in choices]
        weights = [w for _, w in choices]
        chosen = self.rng.choices(actions, weights=weights, k=1)[0]
        if chosen == JUMP:
            return JUMP if self._start_jump() else IDLE
        return chosen

    # --- 읽기 ---------------------------------------------------------

    @property
    def state(self) -> MascotState:
        return MascotState(x=self.x, y=self.y, action=self.action,
                           facing=self.facing, elapsed=self.elapsed,
                           surface=self.surface)

    def frame_index(self, fps: float, frame_count: int) -> int:
        """현재 동작에서 지금 보여야 할 프레임 번호."""
        if frame_count <= 1 or fps <= 0:
            return 0
        return int(self.elapsed * fps) % frame_count
