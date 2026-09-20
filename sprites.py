"""캐릭터 스프라이트 폴더를 읽는다.

두 층으로 나뉜다.

- `CharacterSpec` 과 그 아래(`list_characters`, `load_spec`)는 **순수 파이썬**이다.
  파일 이름과 `meta.json` 만 본다. Qt 를 import 하지 않으므로 QApplication 없이 테스트된다.
- `SpriteSet` 은 Qt 층이다. spec 이 가리키는 PNG 를 실제로 읽어 배율과 좌우 반전을 적용한
  QPixmap 을 캐시한다. QPixmap 은 QGuiApplication 이 있어야 만들 수 있다.

폴더 규격:

    sprites/dog/
        meta.json        (선택)
        idle_0.png  idle_1.png
        walk_0.png  walk_1.png ...
        sit_0.png   sleep_0.png

프레임이 하나뿐이면 `sit.png` 처럼 번호를 빼도 된다.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

# 상태기계가 쓰는 동작 이름. 이 순서가 폴더 검사 순서이기도 하다.
ACTIONS = ("idle", "walk", "run", "sit", "lie", "sleep", "beg", "bark",
           "fall", "drag")

# 없는 동작을 무엇으로 대신할지. 그림이 적은 캐릭터도 일단 움직이게 하는 것이 목적이다.
# 값은 "이 동작이 없으면 다음으로 넘어갈 후보"의 순서다.
FALLBACK = {
    "idle": (),
    "walk": ("idle",),
    "run": ("walk", "idle"),
    "sit": ("idle",),
    "lie": ("sit", "idle"),
    "sleep": ("lie", "sit", "idle"),
    "beg": ("idle",),
    "bark": ("idle",),
    "fall": ("idle",),
    "drag": ("fall", "idle"),
}

DEFAULT_FPS = 8.0
FPS_RANGE = (0.5, 60.0)
SCALE_RANGE = (0.05, 8.0)

_FRAME_RE = re.compile(r"^(?P<action>[a-z]+)(?:_(?P<index>\d+))?$", re.IGNORECASE)


@dataclass(frozen=True)
class ActionSpec:
    """동작 하나 — 프레임 파일 목록과 재생 속도."""

    name: str
    files: tuple[Path, ...]
    fps: float = DEFAULT_FPS

    @property
    def frame_count(self) -> int:
        return len(self.files)

    def duration(self) -> float:
        """한 바퀴 도는 데 걸리는 초."""
        return self.frame_count / self.fps


@dataclass
class CharacterSpec:
    """캐릭터 하나의 폴더를 해석한 결과. Qt 를 모른다."""

    name: str
    directory: Path
    actions: dict[str, ActionSpec] = field(default_factory=dict)
    scale: float = 1.0
    facing: int = 1          # 원본 그림이 보는 방향. +1 오른쪽, -1 왼쪽
    smooth: bool | None = None   # None 이면 배율을 보고 정한다
    warnings: tuple[str, ...] = ()

    def resolve(self, action: str) -> ActionSpec:
        """요청한 동작, 없으면 폴백 체인을 따라간 동작을 돌려준다.

        `idle` 은 항상 있다(없는 폴더는 애초에 캐릭터로 인정하지 않는다). 그래서
        이 함수는 절대 실패하지 않는다 — 호출하는 쪽에서 None 을 걱정할 필요가 없다.
        """
        if action in self.actions:
            return self.actions[action]
        for candidate in FALLBACK.get(action, ()):
            if candidate in self.actions:
                return self.actions[candidate]
        return self.actions["idle"]

    def has(self, action: str) -> bool:
        """폴백 없이 그 동작의 그림이 실제로 있는지."""
        return action in self.actions

    def use_smooth(self, total_scale: float) -> bool:
        """축소할 때만 부드럽게. 도트를 확대할 때 매끄럽게 하면 뭉개진다."""
        if self.smooth is not None:
            return self.smooth
        return total_scale < 1.0


# --- 순수 층: 폴더 읽기 --------------------------------------------------

def _clamp(value, lo, hi):
    return min(max(value, lo), hi)


def _clamped(key, value, lo, hi, warnings: list[str]) -> float:
    """범위 밖이면 깎고 경고를 남긴다. config.py 가 값을 다루는 방식과 같게 맞춘 것."""
    result = _clamp(float(value), lo, hi)
    if result != float(value):
        warnings.append(f"{key}: {value} 는 범위 [{lo}, {hi}] 밖 → {result}")
    return result


def _frame_key(path: Path) -> tuple[int, str]:
    """`walk_10.png` 이 `walk_9.png` 뒤에 오도록 숫자로 정렬한다.

    문자열로 정렬하면 walk_10 이 walk_2 앞에 와서 걷기가 뒤죽박죽이 된다.
    """
    m = _FRAME_RE.match(path.stem)
    index = m.group("index") if m else None
    return (int(index) if index is not None else 0, path.name.lower())


def _collect_frames(directory: Path) -> dict[str, list[Path]]:
    """폴더의 PNG 를 동작별로 모은다."""
    found: dict[str, list[Path]] = {}
    for path in sorted(directory.glob("*.png")):
        m = _FRAME_RE.match(path.stem)
        if not m:
            continue
        action = m.group("action").lower()
        if action not in ACTIONS:
            continue
        found.setdefault(action, []).append(path)
    for files in found.values():
        files.sort(key=_frame_key)
    return found


def _read_meta(directory: Path, warnings: list[str]) -> dict:
    """meta.json 은 전부 선택값이다. 깨져 있어도 캐릭터를 버리지 않는다."""
    path = directory / "meta.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        warnings.append(f"meta.json 을 읽지 못했습니다 ({exc}) → 기본값")
        return {}
    if not isinstance(data, dict):
        warnings.append("meta.json 이 객체가 아닙니다 → 기본값")
        return {}
    return data


def _meta_fps(meta: dict, key: str, default: float, warnings: list[str]) -> float:
    value = meta.get("fps")
    if value is None:
        return default
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        warnings.append(f"{key} fps: 숫자가 아님({value!r}) → {default}")
        return default
    return _clamped(f"{key} fps", value, *FPS_RANGE, warnings=warnings)


def load_spec(directory) -> CharacterSpec | None:
    """캐릭터 폴더 하나를 읽는다. 쓸 수 없는 폴더면 None.

    `idle` 프레임이 하나도 없으면 캐릭터로 보지 않는다. 폴백 체인의 끝이 idle 이라
    idle 이 없으면 그릴 것이 아무것도 없는 상태가 되기 때문이다.
    """
    directory = Path(directory)
    if not directory.is_dir():
        return None

    warnings: list[str] = []
    frames = _collect_frames(directory)
    if "idle" not in frames:
        log.warning("%s: idle 프레임이 없어 건너뜁니다", directory.name)
        return None

    meta = _read_meta(directory, warnings)
    base_fps = _meta_fps(meta, "기본", DEFAULT_FPS, warnings)

    per_action = meta.get("actions")
    if per_action is not None and not isinstance(per_action, dict):
        warnings.append(f"actions: 객체가 아님({per_action!r}) → 무시")
        per_action = None
    per_action = per_action or {}

    actions: dict[str, ActionSpec] = {}
    for name, files in frames.items():
        override = per_action.get(name)
        fps = base_fps
        if isinstance(override, dict):
            fps = _meta_fps(override, name, base_fps, warnings)
        elif override is not None:
            warnings.append(f"actions.{name}: 객체가 아님({override!r}) → 무시")
        actions[name] = ActionSpec(name=name, files=tuple(files), fps=fps)

    scale = meta.get("scale", 1.0)
    if not isinstance(scale, (int, float)) or isinstance(scale, bool):
        warnings.append(f"scale: 숫자가 아님({scale!r}) → 1.0")
        scale = 1.0
    scale = _clamped("scale", scale, *SCALE_RANGE, warnings=warnings)

    facing_raw = meta.get("facing", "right")
    if facing_raw not in ("right", "left"):
        if "facing" in meta:
            warnings.append(f"facing: 'right'/'left' 가 아님({facing_raw!r}) → right")
        facing_raw = "right"

    smooth = meta.get("smooth")
    if smooth is not None and not isinstance(smooth, bool):
        warnings.append(f"smooth: 참/거짓이 아님({smooth!r}) → 자동")
        smooth = None

    for w in warnings:
        log.warning("%s: %s", directory.name, w)

    return CharacterSpec(
        name=directory.name,
        directory=directory,
        actions=actions,
        scale=scale,
        facing=1 if facing_raw == "right" else -1,
        smooth=smooth,
        warnings=tuple(warnings),
    )


def list_characters(root) -> list[str]:
    """쓸 수 있는 캐릭터 폴더 이름을 정렬해 돌려준다."""
    root = Path(root)
    if not root.is_dir():
        return []
    names = []
    for child in sorted(root.iterdir()):
        if child.is_dir() and load_spec(child) is not None:
            names.append(child.name)
    return names


def pick_character(root, preferred: str) -> tuple[str | None, str | None]:
    """설정에 적힌 캐릭터를 쓰되, 없으면 첫 번째 것으로 물러난다.

    (고른 이름, 경고) 를 돌려준다. 쓸 수 있는 캐릭터가 하나도 없으면 (None, 경고).
    """
    available = list_characters(root)
    if not available:
        return None, f"쓸 수 있는 캐릭터가 없습니다: {root}"
    if preferred in available:
        return preferred, None
    return available[0], (f"캐릭터 {preferred!r} 를 찾지 못해 {available[0]!r} 로 대체합니다")


# --- Qt 층: 픽스맵 캐시 ---------------------------------------------------

class SpriteSet:
    """spec 이 가리키는 PNG 를 읽어 배율·반전을 적용한 QPixmap 을 캐시한다.

    QPixmap 은 QGuiApplication 이 만들어진 뒤에만 생성할 수 있으므로 이 클래스는
    반드시 앱이 뜬 다음에 만들어야 한다. 캐시 키는 (동작, 프레임, 방향) 이고
    배율이 바뀌면 캐시를 통째로 버린다 — 배율은 자주 바뀌지 않는다.
    """

    def __init__(self, spec: CharacterSpec, scale: float = 1.0):
        self.spec = spec
        self._scale = 1.0
        self._cache: dict[tuple[str, int, int], object] = {}
        self._missing: set[Path] = set()
        self.set_scale(scale)

    @property
    def name(self) -> str:
        return self.spec.name

    @property
    def scale(self) -> float:
        """설정에서 준 배율. meta.json 의 배율은 여기에 곱해진다."""
        return self._scale

    @property
    def total_scale(self) -> float:
        """meta.json 의 배율과 설정의 배율을 곱한 최종 배율."""
        return self.spec.scale * self._scale

    def set_scale(self, scale: float) -> None:
        scale = _clamp(float(scale), *SCALE_RANGE)
        if scale == self._scale:
            return
        self._scale = scale
        self._cache.clear()

    def resolve(self, action: str) -> ActionSpec:
        return self.spec.resolve(action)

    def frame(self, action: str, index: int, facing: int = 1):
        """그릴 QPixmap 하나. 읽지 못한 파일은 None 을 돌려준다.

        facing 은 캐릭터가 **보는** 방향이다. 원본이 반대쪽을 보고 있으면 좌우로 뒤집는다.
        """
        spec = self.spec.resolve(action)
        if spec.frame_count == 0:
            return None
        index = index % spec.frame_count
        flip = -1 if facing != self.spec.facing else 1
        key = (spec.name, index, flip)

        cached = self._cache.get(key)
        if cached is not None:
            return cached

        pixmap = self._load(spec.files[index], flip)
        if pixmap is not None:
            self._cache[key] = pixmap
        return pixmap

    def _load(self, path: Path, flip: int):
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QPixmap, QTransform

        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            if path not in self._missing:
                self._missing.add(path)
                log.warning("스프라이트를 읽지 못했습니다: %s", path)
            return None

        total = self.total_scale
        if abs(total - 1.0) > 1e-6:
            mode = (Qt.SmoothTransformation if self.spec.use_smooth(total)
                    else Qt.FastTransformation)
            pixmap = pixmap.scaled(
                max(1, round(pixmap.width() * total)),
                max(1, round(pixmap.height() * total)),
                Qt.IgnoreAspectRatio, mode)
        if flip < 0:
            pixmap = pixmap.transformed(QTransform().scale(-1, 1))
        return pixmap

    @classmethod
    def load(cls, directory, scale: float = 1.0) -> "SpriteSet | None":
        spec = load_spec(directory)
        return None if spec is None else cls(spec, scale)
