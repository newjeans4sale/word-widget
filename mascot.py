"""마스코트의 움직임. Qt 도 시간도 난수도 직접 만들지 않는다.

`update(dt, bounds)` 만 호출하면 위치와 동작이 갱신된다. 시간과 난수를 밖에서
주입받으므로 테스트에서 dt 와 시드를 고정해 놓고 몇 분치를 즉시 돌려볼 수 있다.

좌표계는 **발밑(bottom-center)** 기준이다. 스프라이트 크기가 동작마다 달라도
(앉으면 낮아진다) 발이 바닥에 붙어 있게 하려면 이 기준이어야 한다.
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

# 타이머가 밀리거나 절전에서 깨어나면 dt 가 몇 초씩 들어온다. 그대로 적분하면
# 캐릭터가 화면을 가로질러 순간이동하거나 바닥을 뚫는다. 한 틱의 최대치를 정해 둔다.
MAX_DT = 0.25


@dataclass
class MascotState:
    """그리는 쪽이 알아야 하는 전부."""

    x: float
    y: float
    action: str
    facing: int      # +1 오른쪽을 봄, -1 왼쪽을 봄
    elapsed: float   # 현재 동작이 시작된 뒤 흐른 시간. 프레임 번호는 이것으로 계산한다


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

        self._remaining = 0.0
        self._vy = 0.0
        self._wander = True
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
        껐는데도 계속 움직여서 고장난 것처럼 보인다."""
        on = bool(on)
        if on == self._wander:
            return
        self._wander = on
        if not on and self.action in WANDER_ACTIONS:
            self._begin(IDLE)

    @property
    def wandering(self) -> bool:
        return self._wander

    def place(self, x: float, y: float) -> None:
        """위치를 그냥 놓는다 (설정에서 복원할 때)."""
        self.x, self.y = float(x), float(y)
        self._vy = 0.0

    # --- 마우스 ------------------------------------------------------

    def grab(self) -> None:
        if self.action != DRAG:
            self._begin(DRAG)
            self._vy = 0.0

    def drag_to(self, x: float, y: float) -> None:
        if self.action == DRAG:
            self.x, self.y = float(x), float(y)

    def release(self) -> None:
        if self.action == DRAG:
            self._begin(FALL)
            self._vy = 0.0

    @property
    def dragging(self) -> bool:
        return self.action == DRAG

    # --- 매 틱 -------------------------------------------------------

    def update(self, dt: float, bounds) -> None:
        """bounds = (left, right, floor_y) — 전부 발밑 기준점이 갈 수 있는 한계."""
        left, right, floor = bounds
        if right < left:
            left = right = (left + right) / 2.0
        dt = min(max(float(dt), 0.0), MAX_DT)

        self.elapsed += dt
        self._remaining -= dt

        if self.action == DRAG:
            return                      # 손에 들려 있는 동안은 물리도 타이머도 없다

        if self.action == FALL:
            self._fall(dt, floor)
        else:
            if self.y != floor:
                # 화면 배치가 바뀌었다 (해상도 변경, 작업표시줄 자동숨김, 모니터 이동).
                # 공중에 뜬 채로 두지 않고 떨어뜨린다.
                self._begin(FALL)
                self._fall(dt, floor)
            elif self.action in MOVING:
                self._walk(dt, left, right)

        self.x = min(max(self.x, left), right)

        if self.action not in (FALL, DRAG) and self._remaining <= 0.0:
            self._begin(self._choose_next())

    def _walk(self, dt: float, left: float, right: float) -> None:
        speed = self.walk_speed * MOVING.get(self.action, 1.0)
        self.x += self.facing * speed * dt
        if self.x <= left:
            self.x, self.facing = left, 1
        elif self.x >= right:
            self.x, self.facing = right, -1

    def _fall(self, dt: float, floor: float) -> None:
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

    # --- 동작 전환 ----------------------------------------------------

    def _begin(self, action: str) -> None:
        self.action = action
        self.elapsed = 0.0
        if action in DURATIONS:
            lo, hi = DURATIONS[action]
            self._remaining = self.rng.uniform(lo, hi)
            if action in MOVING:
                # 움직이기 시작할 때만 방향을 새로 뽑는다. 매 틱 뽑으면 제자리에서 떤다.
                self.facing = self.rng.choice((-1, 1))
        else:
            self._remaining = float("inf")

    def _choose_next(self) -> str:
        if not self._wander:
            return IDLE
        choices = [(a, w) for a, w in NEXT.get(self.action, NEXT[IDLE])
                   if a in self._available]
        if not choices:
            return IDLE
        actions = [a for a, _ in choices]
        weights = [w for _, w in choices]
        return self.rng.choices(actions, weights=weights, k=1)[0]

    # --- 읽기 ---------------------------------------------------------

    @property
    def state(self) -> MascotState:
        return MascotState(x=self.x, y=self.y, action=self.action,
                           facing=self.facing, elapsed=self.elapsed)

    def frame_index(self, fps: float, frame_count: int) -> int:
        """현재 동작에서 지금 보여야 할 프레임 번호."""
        if frame_count <= 1 or fps <= 0:
            return 0
        return int(self.elapsed * fps) % frame_count
