"""설정 파일 로드/저장.

순수 Python 모듈이다 — Qt도 ctypes도 import하지 않는다. 글꼴 상한(cap)은 OS에서
읽어와 호출자가 주입한다(`osfont.max_font_pt()`). 이 모듈은 OS에 아무것도 묻지 않는다.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, fields
from pathlib import Path

# 글꼴 하한. 상한은 호출자가 주입한다 (이 PC 기준 18pt = 아이콘 글꼴 9pt의 2배).
MIN_FONT_PT = 6
INTERVAL_RANGE = (1.0, 3600.0)
OPACITY_RANGE = (0.1, 1.0)
ANCHORS = ("top-left", "top-right", "bottom-left", "bottom-right")

# #rgb / #rrggbb / #aarrggbb
_COLOR_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")


@dataclass
class Config:
    words_file: str = "words.txt"
    interval_sec: float = 5.0
    font_size_pt: int = 14
    font_family: str = "Segoe UI"
    color: str = "#FFFFFF"
    outline_color: str = "#000000"
    opacity: float = 0.85
    anchor: str = "bottom-right"
    anchor_x: int | None = None
    anchor_y: int | None = None
    hide_on_fullscreen: bool = True
    paused: bool = False


# --- 값 강제 변환 -------------------------------------------------------
# 어떤 입력이 와도 예외를 던지지 않는다. 잘못된 값은 기본값으로 되돌리고 경고만 남긴다.

def _is_number(v) -> bool:
    # bool은 int의 서브클래스라 명시적으로 걸러야 한다.
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _num(key, value, default, lo, hi, warnings, *, integer=False):
    if not _is_number(value):
        warnings.append(f"{key}: 숫자가 아님({value!r}) → 기본값 {default}")
        return default
    clamped = min(max(float(value), lo), hi)
    if clamped != float(value):
        warnings.append(f"{key}: {value} 는 범위 [{lo}, {hi}] 밖 → {clamped}")
    return int(clamped) if integer else clamped


def _text(key, value, default, warnings):
    if not isinstance(value, str) or not value.strip():
        warnings.append(f"{key}: 문자열이 아님({value!r}) → 기본값 {default!r}")
        return default
    return value


def _color(key, value, default, warnings):
    if not isinstance(value, str) or not _COLOR_RE.match(value):
        warnings.append(f"{key}: 색상 형식이 아님({value!r}) → 기본값 {default}")
        return default
    return value


def _choice(key, value, default, allowed, warnings):
    if value not in allowed:
        warnings.append(f"{key}: 허용되지 않는 값({value!r}) → 기본값 {default!r}")
        return default
    return value


def _flag(key, value, default, warnings):
    if not isinstance(value, bool):
        warnings.append(f"{key}: true/false 가 아님({value!r}) → 기본값 {default}")
        return default
    return value


def _coord(key, value, warnings):
    """화면 좌표. None 은 '아직 정해지지 않음'이다.

    음수는 정상값이다 — 두 번째 모니터가 x = -1920 에 있다. 절대 0으로 깎지 않는다.
    """
    if value is None:
        return None
    if not _is_number(value):
        warnings.append(f"{key}: 좌표가 숫자가 아님({value!r}) → 미지정")
        return None
    return int(value)


# --- 로드 / 저장 --------------------------------------------------------

def _backup_path(path: Path) -> Path:
    return path.parent / (path.name + ".bak")


def load(path, max_font_pt: float = 18.0) -> tuple[Config, list[str]]:
    """설정을 읽는다. 절대 예외를 던지지 않고, 파일을 새로 만들지도 않는다.

    반환: (Config, 경고 목록). 경고는 트레이 알림과 로그로 보낸다.
    """
    path = Path(path)
    warnings: list[str] = []
    defaults = Config()

    if not path.exists():
        return defaults, warnings

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raw = None
        warnings.append(f"config.json 을 읽을 수 없음({exc}) → 기본값으로 시작")

    if not isinstance(raw, dict):
        if not warnings:
            warnings.append("config.json 의 최상위가 객체가 아님 → 기본값으로 시작")
        try:
            # 사용자가 쓴 원본 바이트를 보존한다.
            os.replace(path, _backup_path(path))
            warnings.append(f"원본을 {_backup_path(path).name} 으로 보관했습니다")
        except OSError as exc:
            warnings.append(f"백업 실패: {exc}")
        return defaults, warnings

    cap = max(float(max_font_pt), float(MIN_FONT_PT))
    d = defaults
    cfg = Config(
        words_file=_text("words_file", raw.get("words_file", d.words_file), d.words_file, warnings),
        interval_sec=_num("interval_sec", raw.get("interval_sec", d.interval_sec),
                          d.interval_sec, *INTERVAL_RANGE, warnings=warnings),
        font_size_pt=_num("font_size_pt", raw.get("font_size_pt", d.font_size_pt),
                          d.font_size_pt, MIN_FONT_PT, cap, warnings=warnings, integer=True),
        font_family=_text("font_family", raw.get("font_family", d.font_family), d.font_family, warnings),
        color=_color("color", raw.get("color", d.color), d.color, warnings),
        outline_color=_color("outline_color", raw.get("outline_color", d.outline_color),
                             d.outline_color, warnings),
        opacity=_num("opacity", raw.get("opacity", d.opacity), d.opacity,
                     *OPACITY_RANGE, warnings=warnings),
        anchor=_choice("anchor", raw.get("anchor", d.anchor), d.anchor, ANCHORS, warnings),
        anchor_x=_coord("anchor_x", raw.get("anchor_x"), warnings),
        anchor_y=_coord("anchor_y", raw.get("anchor_y"), warnings),
        hide_on_fullscreen=_flag("hide_on_fullscreen",
                                 raw.get("hide_on_fullscreen", d.hide_on_fullscreen),
                                 d.hide_on_fullscreen, warnings),
        paused=_flag("paused", raw.get("paused", d.paused), d.paused, warnings),
    )
    return cfg, warnings


def save(path, cfg: Config) -> None:
    """설정을 원자적으로 저장한다.

    읽고-고쳐-쓰기를 하는 이유: 트레이에 '설정 열기'가 있어서 사용자가 편집기로
    파일을 열어둔 채 위젯을 드래그할 수 있다. 앱이 아는 키만 갱신하고 나머지는 남긴다.
    """
    path = Path(path)
    data: dict = {}
    try:
        existing = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(existing, dict):
            data = existing
    except Exception:
        pass  # 읽을 수 없으면 그냥 새로 쓴다. load() 가 이미 백업을 떠 뒀다.

    data.update(asdict(cfg))

    tmp = path.parent / (path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)  # Windows 에서도 원자적이다


def known_keys() -> tuple[str, ...]:
    return tuple(f.name for f in fields(Config))
