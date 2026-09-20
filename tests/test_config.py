"""config 모듈 단위 테스트. Qt 없이 돈다."""
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config as cfgmod  # noqa: E402


CAP = 18.0


def load(path, cap=CAP):
    return cfgmod.load(path, max_font_pt=cap)


def write_json(path, obj):
    path.write_text(json.dumps(obj), encoding="utf-8")


# --- 없는 파일 / 왕복 ---------------------------------------------------

def test_missing_file_returns_defaults_and_creates_nothing(tmp_path):
    p = tmp_path / "config.json"
    cfg, warnings = load(p)
    assert cfg.interval_sec == 5.0
    assert cfg.font_size_pt == 14
    assert not p.exists(), "load()는 파일을 만들면 안 된다"
    assert warnings == []


def test_save_load_roundtrip(tmp_path):
    p = tmp_path / "config.json"
    cfg, _ = load(p)
    cfg.interval_sec = 7.5
    cfg.anchor_x, cfg.anchor_y = 1200, 900
    cfg.paused = True
    cfgmod.save(p, cfg)
    again, warnings = load(p)
    assert again == cfg
    assert warnings == []


# --- 손상된 파일 --------------------------------------------------------

def test_corrupt_json_backs_up_original_bytes(tmp_path):
    p = tmp_path / "config.json"
    original = '{"interval_sec": 3, oops'
    p.write_text(original, encoding="utf-8")
    cfg, warnings = load(p)
    assert cfg.interval_sec == 5.0
    bak = tmp_path / "config.json.bak"
    assert bak.exists()
    assert bak.read_text(encoding="utf-8") == original
    assert warnings


@pytest.mark.parametrize("payload", [[1, 2, 3], "hello", None, 42])
def test_non_dict_json_falls_back_to_defaults(tmp_path, payload):
    p = tmp_path / "config.json"
    write_json(p, payload)
    cfg, warnings = load(p)
    assert cfg.interval_sec == 5.0
    assert (tmp_path / "config.json.bak").exists()
    assert warnings


def test_missing_keys_filled_from_defaults(tmp_path):
    p = tmp_path / "config.json"
    write_json(p, {"interval_sec": 9})
    cfg, warnings = load(p)
    assert cfg.interval_sec == 9
    assert cfg.font_size_pt == 14
    assert cfg.font_family == "Segoe UI"
    assert warnings == []


def test_wrong_types_fall_back_with_warning(tmp_path):
    p = tmp_path / "config.json"
    write_json(p, {"interval_sec": "five", "font_size_pt": [1], "paused": "yes"})
    cfg, warnings = load(p)
    assert cfg.interval_sec == 5.0
    assert cfg.font_size_pt == 14
    assert cfg.paused is False
    assert len(warnings) >= 3


# --- 클램프 -------------------------------------------------------------

@pytest.mark.parametrize("given,cap,expected", [
    (30, 18.0, 18),
    (30, 24.0, 24),
    (100, 18.0, 18),
    (2, 18.0, 6),
    (14, 18.0, 14),
    (18, 18.0, 18),
])
def test_font_size_clamped_to_cap(tmp_path, given, cap, expected):
    p = tmp_path / "config.json"
    write_json(p, {"font_size_pt": given})
    cfg, _ = load(p, cap=cap)
    assert cfg.font_size_pt == expected


@pytest.mark.parametrize("given,expected", [(0, 1.0), (-5, 1.0), (99999, 3600.0), (5, 5.0)])
def test_interval_clamped(tmp_path, given, expected):
    p = tmp_path / "config.json"
    write_json(p, {"interval_sec": given})
    cfg, _ = load(p)
    assert cfg.interval_sec == expected


@pytest.mark.parametrize("given,expected", [(2.0, 1.0), (0.0, 0.1), (-1, 0.1), (0.5, 0.5)])
def test_opacity_clamped(tmp_path, given, expected):
    p = tmp_path / "config.json"
    write_json(p, {"opacity": given})
    cfg, _ = load(p)
    assert cfg.opacity == pytest.approx(expected)


# --- 값 검증 ------------------------------------------------------------

@pytest.mark.parametrize("value,valid", [
    ("#ffcc00", True), ("#FC0", True), ("#11223344", True),
    ("banana", False), ("ffcc00", False), ("#gg0011", False), ("#12345", False),
])
def test_color_validation(tmp_path, value, valid):
    p = tmp_path / "config.json"
    write_json(p, {"color": value})
    cfg, warnings = load(p)
    if valid:
        assert cfg.color == value
        assert warnings == []
    else:
        assert cfg.color == "#FFFFFF"
        assert warnings


@pytest.mark.parametrize("value,expected", [
    ("top-left", "top-left"), ("bottom-right", "bottom-right"), ("sideways", "bottom-right"),
])
def test_anchor_validation(tmp_path, value, expected):
    p = tmp_path / "config.json"
    write_json(p, {"anchor": value})
    cfg, _ = load(p)
    assert cfg.anchor == expected


def test_negative_anchor_x_survives(tmp_path):
    """두 번째 모니터는 x = -1920에 있다. 음수 좌표를 깎아내면 버그다."""
    p = tmp_path / "config.json"
    write_json(p, {"anchor_x": -1800, "anchor_y": 500})
    cfg, warnings = load(p)
    assert cfg.anchor_x == -1800
    assert cfg.anchor_y == 500
    assert warnings == []

    cfgmod.save(p, cfg)
    again, _ = load(p)
    assert again.anchor_x == -1800


def test_anchor_none_allowed(tmp_path):
    p = tmp_path / "config.json"
    write_json(p, {"anchor_x": None})
    cfg, warnings = load(p)
    assert cfg.anchor_x is None
    assert warnings == []


# --- 저장 동작 ----------------------------------------------------------

def test_save_is_atomic_and_leaves_no_tmp(tmp_path):
    p = tmp_path / "config.json"
    cfg, _ = load(p)
    cfgmod.save(p, cfg)
    assert not (tmp_path / "config.json.tmp").exists()
    json.loads(p.read_text(encoding="utf-8"))


def test_save_preserves_unknown_keys(tmp_path):
    """사용자가 편집기로 열어둔 채 위치가 저장돼도 사용자 키를 날리면 안 된다."""
    p = tmp_path / "config.json"
    write_json(p, {"interval_sec": 5, "my_note": "손대지 마세요", "future_option": 7})
    cfg, _ = load(p)
    cfg.anchor_x = 100
    cfgmod.save(p, cfg)
    raw = json.loads(p.read_text(encoding="utf-8"))
    assert raw["my_note"] == "손대지 마세요"
    assert raw["future_option"] == 7
    assert raw["anchor_x"] == 100


def test_non_ascii_path_roundtrips_readable(tmp_path):
    p = tmp_path / "config.json"
    cfg, _ = load(p)
    cfg.words_file = "단어목록.txt"
    cfgmod.save(p, cfg)
    text = p.read_text(encoding="utf-8")
    assert "단어목록.txt" in text, "ensure_ascii=False 여야 읽을 수 있다"
    again, _ = load(p)
    assert again.words_file == "단어목록.txt"


def test_save_creates_parent_readable_json(tmp_path):
    p = tmp_path / "config.json"
    cfg, _ = load(p)
    cfgmod.save(p, cfg)
    text = p.read_text(encoding="utf-8")
    assert "\n" in text, "indent=2 로 사람이 읽을 수 있게 저장한다"


# --- 마스코트 키 --------------------------------------------------------

def test_mascot_defaults(tmp_path):
    cfg, warnings = load(tmp_path / "config.json")
    assert cfg.mode == "text"
    assert cfg.character == "tan"
    assert cfg.mascot_scale == 1.0
    assert cfg.mascot_wander is True
    assert cfg.bubble is True
    assert cfg.mascot_x is None and cfg.mascot_y is None
    assert warnings == []


def test_mascot_roundtrip(tmp_path):
    p = tmp_path / "config.json"
    cfg, _ = load(p)
    cfg.mode = "mascot"
    cfg.character = "husky"
    cfg.mascot_scale = 2.5
    cfg.mascot_wander = False
    cfg.mascot_x, cfg.mascot_y = -1500, 1040
    cfg.bubble = False
    cfgmod.save(p, cfg)
    again, warnings = load(p)
    assert again == cfg
    assert warnings == []


def test_unknown_mode_falls_back(tmp_path):
    p = tmp_path / "config.json"
    write_json(p, {"mode": "hologram"})
    cfg, warnings = load(p)
    assert cfg.mode == "text"
    assert warnings


def test_mascot_scale_is_clamped(tmp_path):
    p = tmp_path / "config.json"
    write_json(p, {"mascot_scale": 99})
    cfg, warnings = load(p)
    assert cfg.mascot_scale == cfgmod.MASCOT_SCALE_RANGE[1]
    assert warnings


def test_negative_mascot_x_is_kept(tmp_path):
    # 두 번째 모니터가 x = -1920 에 있다. 0으로 깎으면 위젯이 순간이동한다.
    p = tmp_path / "config.json"
    write_json(p, {"mascot_x": -1800, "mascot_y": 1040})
    cfg, warnings = load(p)
    assert (cfg.mascot_x, cfg.mascot_y) == (-1800, 1040)
    assert warnings == []
