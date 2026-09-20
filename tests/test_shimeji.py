"""Shimeji 규격 표 단위 테스트. Qt 없이 돈다.

실제 파일을 자르는 부분은 tools/import_shimeji.py 를 직접 돌려 확인한다.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
import import_shimeji as shimeji  # noqa: E402

FULL = set(range(1, 47))


def test_full_pack_gets_every_mapped_action():
    assert set(shimeji.plan(FULL)) == set(shimeji.FRAME_MAP)


def test_missing_frame_drops_only_that_action():
    # shime21(Sprawl)이 없는 팩은 흔하다. lie 만 빠지고 나머지는 남아야 한다.
    got = shimeji.plan(FULL - {21})
    assert "lie" not in got
    assert {"idle", "walk", "sit", "fall", "drag"} <= set(got)


def test_a_half_finished_walk_is_dropped_entirely():
    """중간 프레임이 빠진 채로 재생하면 걷다가 튄다. 통째로 버리는 편이 낫다."""
    got = shimeji.plan(FULL - {3})
    assert "walk" not in got and "run" not in got
    assert "idle" in got


def test_bare_minimum_pack():
    got = shimeji.plan({1})
    assert list(got) == ["idle"]


def test_empty_pack_has_nothing():
    assert shimeji.plan(set()) == {}


def test_every_mapped_frame_is_in_range():
    # Shimeji 규격은 shime1~46 이다. 표에 오타로 엉뚱한 번호가 들어가면 잡는다.
    for action, frames in shimeji.FRAME_MAP.items():
        assert frames, action
        assert all(1 <= n <= 46 for n in frames), action


def test_actions_are_ones_our_state_machine_knows():
    import sprites
    assert set(shimeji.FRAME_MAP) <= set(sprites.ACTIONS)
