"""mascot 상태기계 단위 테스트. Qt 없이 돈다.

시간과 난수를 주입하므로 실제로 기다릴 필요가 없다. `run()` 으로 몇 분치를
한순간에 돌린다.
"""
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import mascot as mascot_mod  # noqa: E402
from mascot import DRAG, FALL, IDLE, SIT, SLEEP, WALK, Mascot  # noqa: E402


BOUNDS = (0.0, 1000.0, 500.0)      # left, right, floor
DT = 1 / 16                        # 오버레이 타이머와 같은 간격


def make(seed=0, **kwargs):
    m = Mascot(rng=random.Random(seed), **kwargs)
    m.place(500.0, BOUNDS[2])
    return m


def run(m, seconds, bounds=BOUNDS, dt=DT):
    """그만큼의 시간을 흘려보내고 지나간 동작들을 돌려준다."""
    seen = []
    for _ in range(int(seconds / dt)):
        m.update(dt, bounds)
        if not seen or seen[-1] != m.action:
            seen.append(m.action)
    return seen


# --- 기본 -------------------------------------------------------------

def test_starts_idle_on_the_floor():
    m = make()
    assert m.action == IDLE
    assert m.state.y == BOUNDS[2]


def test_deterministic_for_a_given_seed():
    a, b = make(seed=7), make(seed=7)
    for _ in range(600):
        a.update(DT, BOUNDS)
        b.update(DT, BOUNDS)
    assert (a.state.x, a.state.action, a.state.facing) == \
           (b.state.x, b.state.action, b.state.facing)


def test_visits_every_wander_action_eventually():
    seen = set(run(make(seed=3), 600))
    assert {IDLE, WALK, SIT, SLEEP} <= seen


def test_stays_on_the_floor_while_wandering():
    m = make(seed=11)
    for _ in range(4000):
        m.update(DT, BOUNDS)
        assert m.state.y == BOUNDS[2]


# --- 걷기 -------------------------------------------------------------

def test_walking_moves_horizontally():
    m = make()
    m._begin(WALK)
    x0 = m.state.x
    for _ in range(16):
        m.update(DT, BOUNDS)
    assert abs(m.state.x - x0) > 1.0


def test_turns_around_at_the_edges():
    m = make()
    m.place(10.0, BOUNDS[2])
    m._begin(WALK)
    m.facing = -1
    for _ in range(200):
        m.update(DT, BOUNDS)
        assert BOUNDS[0] <= m.state.x <= BOUNDS[1]
    # 왼쪽 벽에 닿았으면 오른쪽을 보고 있어야 한다 (걷는 중이라면)
    m.place(0.0, BOUNDS[2])
    m._begin(WALK)
    m.facing = -1
    m.update(DT, BOUNDS)
    assert m.facing == 1


def test_never_leaves_bounds_over_a_long_run():
    m = make(seed=5)
    for _ in range(20000):
        m.update(DT, BOUNDS)
        assert BOUNDS[0] <= m.state.x <= BOUNDS[1]


def test_narrow_bounds_do_not_explode():
    m = make()
    m._begin(WALK)
    for _ in range(100):
        m.update(DT, (400.0, 400.0, 500.0))
    assert m.state.x == 400.0


def test_inverted_bounds_are_survived():
    # 화면 계산이 잘못되어 right < left 로 들어와도 죽지 않아야 한다.
    m = make()
    for _ in range(50):
        m.update(DT, (800.0, 200.0, 500.0))
    assert 200.0 <= m.state.x <= 800.0


# --- 산책 끄기 ---------------------------------------------------------

def test_wander_off_stops_immediately():
    m = make(seed=2)
    m._begin(WALK)
    m.set_wander(False)
    assert m.action == IDLE
    x0 = m.state.x
    assert set(run(m, 300)) == {IDLE}
    assert m.state.x == x0


def test_wander_can_be_turned_back_on():
    m = make(seed=2)
    m.set_wander(False)
    run(m, 30)
    m.set_wander(True)
    assert WALK in run(m, 300)


def test_wander_off_does_not_interrupt_a_fall():
    m = make()
    m.grab()
    m.drag_to(500.0, 100.0)
    m.release()
    m.set_wander(False)
    assert m.action == FALL


# --- 드래그와 낙하 ------------------------------------------------------

def test_drag_follows_the_cursor_and_ignores_gravity():
    m = make()
    m.grab()
    assert m.dragging
    m.drag_to(120.0, 80.0)
    for _ in range(100):
        m.update(DT, BOUNDS)
    assert (m.state.x, m.state.y) == (120.0, 80.0)
    assert m.action == DRAG


def test_release_falls_and_lands_on_the_floor():
    m = make()
    m.grab()
    m.drag_to(300.0, 50.0)
    m.release()
    assert m.action == FALL
    for _ in range(200):
        m.update(DT, BOUNDS)
        if m.action != FALL:
            break
    assert m.state.y == BOUNDS[2]
    assert m.state.x == 300.0
    assert m.action == IDLE


def test_falling_never_sinks_below_the_floor():
    m = make()
    m.grab()
    m.drag_to(300.0, 0.0)
    m.release()
    for _ in range(400):
        m.update(DT, BOUNDS)
        assert m.state.y <= BOUNDS[2]


def test_dropped_outside_bounds_is_pulled_back():
    # 첫 틱에 경계 안으로 들어와야 한다. 그 뒤로는 알아서 걸어다니므로 여기서 확인한다.
    m = make()
    m.grab()
    m.drag_to(5000.0, 50.0)
    m.release()
    m.update(DT, BOUNDS)
    assert m.state.x == BOUNDS[1]


def test_grab_while_falling_is_ignored_until_grabbed():
    m = make()
    m.grab()
    m.release()
    assert m.action == FALL
    m.grab()
    assert m.action == DRAG


def test_release_without_grab_does_nothing():
    m = make()
    m.release()
    assert m.action == IDLE


# --- 화면이 바뀌는 경우 --------------------------------------------------

def test_floor_moving_down_makes_it_fall():
    m = make()
    assert m.action == IDLE
    m.update(DT, (0.0, 1000.0, 900.0))    # 더 큰 화면으로 옮겨졌다
    assert m.action == FALL
    for _ in range(200):
        m.update(DT, (0.0, 1000.0, 900.0))
        if m.action != FALL:
            break
    assert m.state.y == 900.0


def test_floor_moving_up_snaps_without_falling_through():
    m = make()
    m.update(DT, (0.0, 1000.0, 300.0))    # 더 작은 화면
    assert m.state.y == 300.0
    assert m.action == IDLE


# --- 튼튼함 ------------------------------------------------------------

def test_huge_dt_does_not_teleport():
    """절전에서 깨어나면 dt 가 몇 분씩 들어온다. 한 틱으로 화면을 가로지르면 안 된다."""
    m = make()
    m._begin(WALK)
    x0 = m.state.x
    m.update(600.0, BOUNDS)
    assert abs(m.state.x - x0) <= m.walk_speed * mascot_mod.MAX_DT + 1e-6


def test_negative_dt_is_ignored():
    m = make()
    x0 = m.state.x
    m._begin(WALK)
    m.update(-5.0, BOUNDS)
    assert m.state.x == x0


# --- 그림이 없는 동작은 고르지 않는다 -------------------------------------

def test_only_available_actions_are_chosen():
    m = Mascot(rng=random.Random(4), available={IDLE, WALK})
    m.place(500.0, BOUNDS[2])
    assert set(run(m, 900)) <= {IDLE, WALK}


def test_idle_is_always_available_even_if_not_listed():
    m = Mascot(rng=random.Random(1), available=set())
    m.place(500.0, BOUNDS[2])
    assert set(run(m, 120)) == {IDLE}


def test_losing_the_current_action_falls_back_to_idle():
    m = make()
    m._begin(SIT)
    m.set_available({IDLE, WALK})
    assert m.action == IDLE


# --- 프레임 번호 --------------------------------------------------------

def test_frame_index_cycles_with_elapsed_time():
    m = make()
    m._begin(WALK)
    assert m.frame_index(fps=8, frame_count=4) == 0
    for _ in range(2):          # 2/16 초 = 0.125s, 8fps 면 1 프레임
        m.update(DT, BOUNDS)
    assert m.frame_index(fps=8, frame_count=4) == 1


def test_frame_index_is_zero_for_a_single_frame():
    m = make()
    run(m, 5)
    assert m.frame_index(fps=8, frame_count=1) == 0
    assert m.frame_index(fps=0, frame_count=4) == 0


# --- 늘어난 동작 (run / lie / beg / bark) ---------------------------------

def test_visits_the_new_actions_too():
    seen = set(run(make(seed=9), 2000))
    assert set(mascot_mod.WANDER_ACTIONS) <= seen


def test_running_is_faster_than_walking():
    def distance(action):
        m = make(seed=1)
        m._begin(action)
        m.facing = 1
        m.place(100.0, BOUNDS[2])
        for _ in range(16):          # 1초
            m.update(DT, BOUNDS)
        return m.state.x - 100.0
    assert distance("run") > distance("walk") * 2


def test_standing_actions_do_not_move():
    for action in ("idle", "sit", "lie", "sleep", "beg", "bark"):
        m = make(seed=2)
        m.set_wander(False)          # 다음 동작으로 넘어가지 않게 고정
        m._begin(action)
        x0 = m.state.x
        for _ in range(32):
            m.update(DT, BOUNDS)
        assert m.state.x == x0, action


def test_a_dog_without_the_fancy_actions_still_works():
    """허스키처럼 lie/beg/sleep 이 없는 캐릭터도 돌아야 한다."""
    m = Mascot(rng=random.Random(3), available={"idle", "walk", "run", "sit", "bark"})
    m.place(500.0, BOUNDS[2])
    seen = set(run(m, 900))
    assert seen <= {"idle", "walk", "run", "sit", "bark"}
    assert "walk" in seen


def test_bark_and_beg_are_short():
    for action in ("bark", "beg"):
        lo, hi = mascot_mod.DURATIONS[action]
        assert hi <= 4.0, action
