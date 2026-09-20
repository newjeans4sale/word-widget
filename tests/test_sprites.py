"""sprites 모듈의 순수 층 단위 테스트. Qt 없이 돈다.

여기서 다루는 것은 폴더 스캔, meta.json 해석, 동작 폴백까지다. QPixmap 을 만드는
SpriteSet 은 QGuiApplication 이 있어야 하므로 tools/verify_mascot.py 로 확인한다.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import sprites  # noqa: E402


def make_char(root, name, frames, meta=None):
    """빈 PNG 파일로 캐릭터 폴더를 만든다. 내용은 보지 않으므로 비어 있어도 된다."""
    d = root / name
    d.mkdir(parents=True)
    for filename in frames:
        (d / filename).write_bytes(b"")
    if meta is not None:
        (d / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return d


# --- 폴더 스캔 ----------------------------------------------------------

def test_collects_frames_per_action(tmp_path):
    d = make_char(tmp_path, "dog", [
        "idle_0.png", "idle_1.png", "walk_0.png", "walk_1.png", "walk_2.png"])
    spec = sprites.load_spec(d)
    assert spec is not None
    assert spec.name == "dog"
    assert spec.actions["idle"].frame_count == 2
    assert spec.actions["walk"].frame_count == 3


def test_frames_sort_numerically_not_alphabetically(tmp_path):
    # walk_10 이 walk_2 앞에 오면 걷기가 뒤죽박죽이 된다.
    d = make_char(tmp_path, "dog", ["idle_0.png"] + [f"walk_{i}.png" for i in range(12)])
    spec = sprites.load_spec(d)
    names = [p.name for p in spec.actions["walk"].files]
    assert names[:3] == ["walk_0.png", "walk_1.png", "walk_2.png"]
    assert names[-1] == "walk_11.png"


def test_single_frame_needs_no_index(tmp_path):
    d = make_char(tmp_path, "dog", ["idle.png", "sit.png"])
    spec = sprites.load_spec(d)
    assert spec.actions["idle"].frame_count == 1
    assert spec.has("sit")


def test_unknown_files_are_ignored(tmp_path):
    d = make_char(tmp_path, "dog", [
        "idle_0.png", "dance_0.png", "thumbnail.png", "walk_0.png"])
    spec = sprites.load_spec(d)
    assert set(spec.actions) == {"idle", "walk"}


def test_folder_without_idle_is_rejected(tmp_path):
    d = make_char(tmp_path, "broken", ["walk_0.png", "sit_0.png"])
    assert sprites.load_spec(d) is None


def test_missing_directory_is_rejected(tmp_path):
    assert sprites.load_spec(tmp_path / "nope") is None


# --- 폴백 체인 ----------------------------------------------------------

def test_missing_action_falls_back_to_idle(tmp_path):
    d = make_char(tmp_path, "dog", ["idle_0.png"])
    spec = sprites.load_spec(d)
    for action in sprites.ACTIONS:
        assert spec.resolve(action).name == "idle"
        if action != "idle":
            assert not spec.has(action)


def test_sleep_prefers_sit_over_idle(tmp_path):
    d = make_char(tmp_path, "dog", ["idle_0.png", "sit_0.png"])
    spec = sprites.load_spec(d)
    assert spec.resolve("sleep").name == "sit"
    assert spec.resolve("drag").name == "idle"   # fall 도 없으므로 idle


def test_drag_prefers_fall(tmp_path):
    d = make_char(tmp_path, "dog", ["idle_0.png", "fall_0.png"])
    spec = sprites.load_spec(d)
    assert spec.resolve("drag").name == "fall"


# --- meta.json ----------------------------------------------------------

def test_defaults_without_meta(tmp_path):
    d = make_char(tmp_path, "dog", ["idle_0.png"])
    spec = sprites.load_spec(d)
    assert spec.scale == 1.0
    assert spec.facing == 1
    assert spec.actions["idle"].fps == sprites.DEFAULT_FPS
    assert spec.warnings == ()


def test_meta_sets_scale_facing_and_fps(tmp_path):
    d = make_char(tmp_path, "dog", ["idle_0.png", "walk_0.png"],
                  meta={"fps": 6, "scale": 2, "facing": "left",
                        "actions": {"walk": {"fps": 12}}})
    spec = sprites.load_spec(d)
    assert spec.scale == 2.0
    assert spec.facing == -1
    assert spec.actions["idle"].fps == 6
    assert spec.actions["walk"].fps == 12


def test_broken_meta_falls_back_without_losing_character(tmp_path):
    d = make_char(tmp_path, "dog", ["idle_0.png"])
    (d / "meta.json").write_text("{ this is not json", encoding="utf-8")
    spec = sprites.load_spec(d)
    assert spec is not None
    assert spec.scale == 1.0
    assert spec.warnings, "경고는 남겨야 한다"


def test_bad_values_are_clamped_or_defaulted(tmp_path):
    d = make_char(tmp_path, "dog", ["idle_0.png"],
                  meta={"fps": "빠르게", "scale": 999, "facing": "up", "smooth": "네"})
    spec = sprites.load_spec(d)
    assert spec.actions["idle"].fps == sprites.DEFAULT_FPS
    assert spec.scale == sprites.SCALE_RANGE[1]
    assert spec.facing == 1
    assert spec.smooth is None
    assert len(spec.warnings) == 4


def test_action_duration(tmp_path):
    d = make_char(tmp_path, "dog", ["idle_0.png"] + [f"walk_{i}.png" for i in range(4)],
                  meta={"actions": {"walk": {"fps": 8}}})
    spec = sprites.load_spec(d)
    assert spec.actions["walk"].duration() == 0.5


def test_smooth_is_automatic_for_shrinking(tmp_path):
    d = make_char(tmp_path, "dog", ["idle_0.png"])
    spec = sprites.load_spec(d)
    assert spec.use_smooth(0.4) is True
    assert spec.use_smooth(2.0) is False


def test_smooth_can_be_forced(tmp_path):
    d = make_char(tmp_path, "dog", ["idle_0.png"], meta={"smooth": True})
    spec = sprites.load_spec(d)
    assert spec.use_smooth(2.0) is True


# --- 목록과 선택 --------------------------------------------------------

def test_list_characters_skips_invalid_and_sorts(tmp_path):
    make_char(tmp_path, "zebra", ["idle_0.png"])
    make_char(tmp_path, "dog", ["idle_0.png"])
    make_char(tmp_path, "broken", ["walk_0.png"])
    (tmp_path / "notes.txt").write_text("무시되어야 한다", encoding="utf-8")
    assert sprites.list_characters(tmp_path) == ["dog", "zebra"]


def test_list_characters_on_missing_root(tmp_path):
    assert sprites.list_characters(tmp_path / "nope") == []


def test_pick_character_uses_preferred(tmp_path):
    make_char(tmp_path, "dog", ["idle_0.png"])
    make_char(tmp_path, "cat", ["idle_0.png"])
    assert sprites.pick_character(tmp_path, "dog") == ("dog", None)


def test_pick_character_falls_back_with_warning(tmp_path):
    make_char(tmp_path, "cat", ["idle_0.png"])
    name, warning = sprites.pick_character(tmp_path, "dog")
    assert name == "cat"
    assert warning and "dog" in warning


def test_pick_character_with_nothing_available(tmp_path):
    name, warning = sprites.pick_character(tmp_path, "dog")
    assert name is None
    assert warning
