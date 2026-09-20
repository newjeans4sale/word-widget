r"""Shimeji 캐릭터 팩을 우리 sprites/ 폴더로 옮긴다.

    python tools/import_shimeji.py 받은폴더_또는_zip --out sprites/miku

Shimeji 는 `shime1.png` ~ `shime46.png` 라는 오래된 규격을 쓴다. 번호와 동작의
대응은 shimeji-ee 의 기본 `conf/actions.xml` 에서 가져왔다
(https://github.com/weirdogamergirl/shimeji-ee/blob/master/conf/actions.xml).

우리 상태기계에 없는 것(벽 타기, 천장 매달리기, 분열)은 버린다. 반대로
`drag` 는 Shimeji 의 Pinched(머리를 집힌 모습)가 그대로 들어맞는다.

**정렬:** Shimeji 프레임은 전부 같은 크기의 캔버스에 맞춰 그려져 있다. 그래서
여백을 동작마다 따로 자르면 안 되고 **모든 프레임의 합집합**으로 한 번에 잘라야
발 위치가 유지된다 (import_sheet.py 의 --trim 과 반대다).
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

# 우리 동작 -> shime 번호. 같은 번호가 되풀이되는 것은 원본 그대로다
# (Walk 는 선 자세와 발을 뗀 자세를 오간다).
FRAME_MAP = {
    "idle": [1],
    "walk": [1, 2, 1, 3],
    "run": [1, 2, 1, 3],      # Shimeji 도 같은 그림을 쓰고 속도만 올린다
    "sit": [11],
    "lie": [21],              # Sprawl
    "fall": [4],              # Falling
    "drag": [9, 7, 1, 8, 10],  # Pinched - 머리를 집혀 대롱거리는 모습
}
REQUIRED = "idle"

CREDITS_NOTE = (
    "Imported from a Shimeji character pack." + chr(10) +
    "Shimeji frame layout: shimeji-ee conf/actions.xml." + chr(10) +
    "The artwork belongs to whoever drew it - most packs use existing characters, "
    "so keep this to personal use unless you know otherwise.")


def plan(available: set[int]) -> dict[str, list[int]]:
    """가진 번호로 만들 수 있는 동작만 추린다. 순수 함수 — 파일을 보지 않는다.

    한 프레임이라도 빠진 동작은 통째로 버린다. 중간이 빠진 채로 재생하면
    걷다가 한 칸씩 튀는 것처럼 보인다.
    """
    out = {}
    for action, frames in FRAME_MAP.items():
        if all(n in available for n in frames):
            out[action] = list(frames)
    return out


def find_frames(root: Path) -> dict[int, Path]:
    """shimeN.png 를 찾는다. zip 을 풀면 한 겹 더 들어가 있는 경우가 많아 재귀로 본다."""
    found: dict[int, Path] = {}
    for path in root.rglob("*.png"):
        stem = path.stem.lower()
        if not stem.startswith("shime"):
            continue
        digits = stem[5:]
        if digits.isdigit():
            found.setdefault(int(digits), path)
    return found


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Shimeji 팩을 캐릭터 폴더로 옮깁니다")
    ap.add_argument("source", type=Path, help="shime*.png 이 든 폴더 또는 zip")
    ap.add_argument("--out", type=Path, required=True)
    # Shimeji 원본 그림은 왼쪽을 보고 있고 엔진이 뒤집어 쓴다.
    ap.add_argument("--facing", choices=("left", "right"), default="left")
    ap.add_argument("--scale", type=float, default=1.0)
    ap.add_argument("--fps", type=float, default=6.0)
    args = ap.parse_args(argv)

    if not args.source.exists():
        print(f"경로가 없습니다: {args.source}", file=sys.stderr)
        return 1

    # Qt 는 여기서 불러온다. 위에 두면 규격 표만 쓰려 해도 PySide6 가 필요해진다.
    from PySide6.QtGui import QGuiApplication, QImage

    from import_sheet import content_rect

    QGuiApplication.instance() or QGuiApplication([])

    tmp = None
    root = args.source
    if args.source.is_file():
        if args.source.suffix.lower() != ".zip":
            print("파일이라면 zip 이어야 합니다", file=sys.stderr)
            return 1
        tmp = Path(tempfile.mkdtemp(prefix="shimeji-"))
        with zipfile.ZipFile(args.source) as z:
            z.extractall(tmp)
        root = tmp

    try:
        frames = find_frames(root)
        if not frames:
            print(f"shime*.png 을 찾지 못했습니다: {root}", file=sys.stderr)
            return 1
        print(f"프레임 {len(frames)}장 발견 (shime{min(frames)}~shime{max(frames)})")

        chosen = plan(set(frames))
        if REQUIRED not in chosen:
            print(f"shime1.png 이 없어 캐릭터로 쓸 수 없습니다", file=sys.stderr)
            return 1
        skipped = [a for a in FRAME_MAP if a not in chosen]

        images = {n: QImage(str(p)).convertToFormat(QImage.Format_ARGB32)
                  for n, p in frames.items()}
        used = {n for nums in chosen.values() for n in nums}

        # 모든 프레임을 같은 상자로 자른다. 동작마다 따로 자르면 발이 떠다닌다.
        box = None
        for n in sorted(used):
            rect = content_rect(images[n])
            if rect is None:
                continue
            box = rect if box is None else box.united(rect)

        args.out.mkdir(parents=True, exist_ok=True)
        for stale in args.out.glob("*.png"):
            stale.unlink()

        for action, nums in sorted(chosen.items()):
            for i, n in enumerate(nums):
                img = images[n]
                if box is not None:
                    img = img.copy(box)
                img.save(str(args.out / f"{action}_{i}.png"))

        meta = {"fps": args.fps, "scale": args.scale, "facing": args.facing,
                "actions": {"walk": {"fps": 8}, "run": {"fps": 12}}}
        (args.out / "meta.json").write_text(
            json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        (args.out / "CREDITS.txt").write_text(CREDITS_NOTE + "\n", encoding="utf-8")

        size = f"{box.width()}x{box.height()}" if box else "?"
        print(f"{args.out}: {len(chosen)}개 동작, 한 칸 {size}")
        for action, nums in sorted(chosen.items()):
            print(f"  {action:5s} {len(nums)}프레임")
        if skipped:
            print("  (프레임이 없어 건너뜀: " + ", ".join(skipped) + ")")
        return 0
    finally:
        if tmp is not None:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
