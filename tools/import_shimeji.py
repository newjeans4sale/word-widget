r"""Shimeji 캐릭터 팩을 우리 sprites/ 폴더로 옮긴다.

    python tools/import_shimeji.py 받은폴더_또는_zip --out sprites/miku

Shimeji 는 `shime1.png` ~ `shime46.png` 라는 오래된 규격을 쓴다. 번호와 동작의
대응은 shimeji-ee 의 기본 `conf/actions.xml` 에서 가져왔다
(https://github.com/weirdogamergirl/shimeji-ee/blob/master/conf/actions.xml).

우리 상태기계에 없는 것(벽 타기, 천장 매달리기, 분열)은 버린다. 반대로
`drag` 는 Shimeji 의 Pinched(머리를 집힌 모습)가 그대로 들어맞는다.

**정렬:** 여백은 **동작마다** 딱 맞게 잘라낸다 (import_sheet.py 와 같다).

처음에는 모든 프레임을 같은 상자로 잘랐다. 원본 캔버스가 같으니 그게 맞을 줄
알았는데, 팬메이드 팩은 프레임마다 캔버스 안의 위치가 제각각이었다. gojo 는
앉은 그림이 선 그림보다 26px 아래에, toothless 는 떨어지는 그림이 23px 아래에
그려져 있었고, 공통 상자로 자르니 **서 있는 캐릭터가 바닥에서 그만큼 떠 버렸다**.
게다가 넓게 뻗는 자세 하나 때문에 캔버스가 통째로 넓어져(피카츄 277px), 몸통
양옆에 붙는 화살표가 허공에 떴다.

동작마다 자르면 그 자세의 가장 낮은 픽셀이 바닥에 놓인다. 서면 발이, 앉으면
엉덩이가 바닥에 닿는다 — 어느 쪽이든 그게 옳다. 공중에 있는 자세(떨어지는 중,
집혀 대롱거리는 중)는 어차피 물리가 높이를 정하므로 상관없다.
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
    ap.add_argument("--scale", type=float, default=None,
                    help="배율을 직접 지정 (기본은 --fit 으로 자동 계산)")
    ap.add_argument("--fit", type=float, default=130.0,
                    help="서 있는 모습의 긴 변을 이 픽셀에 맞춘다")
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

        rects = {n: content_rect(images[n]) for n in sorted(used)}
        rects = {n: r for n, r in rects.items() if r is not None}
        if not rects:
            print("전부 투명한 프레임뿐입니다", file=sys.stderr)
            return 1

        args.out.mkdir(parents=True, exist_ok=True)
        for stale in args.out.glob("*.png"):
            stale.unlink()

        sizes = {}
        for action, nums in sorted(chosen.items()):
            xs = [rects[n] for n in nums if n in rects]
            if not xs:
                continue
            # 한 동작 안에서는 공통 상자를 쓴다. 프레임마다 따로 자르면 걸을 때 떤다.
            left = min(r.left() for r in xs)
            right = max(r.right() for r in xs)
            top = min(r.top() for r in xs)
            bottom = max(r.bottom() for r in xs)
            for i, n in enumerate(nums):
                crop = images[n].copy(left, top, right - left + 1, bottom - top + 1)
                crop.save(str(args.out / f"{action}_{i}.png"))
            sizes[action] = (right - left + 1, bottom - top + 1)

        scale = args.scale
        if scale is None:
            # 서 있는 모습의 긴 변을 기준으로 잡는다. 캔버스가 아니라 실제 그림 크기다.
            idle = rects[chosen["idle"][0]]
            scale = round(args.fit / max(idle.width(), idle.height()), 2)

        meta = {"fps": args.fps, "scale": scale, "facing": args.facing,
                "actions": {"walk": {"fps": 8}, "run": {"fps": 12}}}
        (args.out / "meta.json").write_text(
            json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        (args.out / "CREDITS.txt").write_text(CREDITS_NOTE + "\n", encoding="utf-8")

        print(f"{args.out}: {len(chosen)}개 동작, 배율 {scale}")
        for action, nums in sorted(chosen.items()):
            w, h = sizes.get(action, (0, 0))
            print(f"  {action:5s} {len(nums)}프레임 {w}x{h}"
                  f" -> {round(w * scale)}x{round(h * scale)}")
        if skipped:
            print("  (프레임이 없어 건너뜀: " + ", ".join(skipped) + ")")
        return 0
    finally:
        if tmp is not None:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
