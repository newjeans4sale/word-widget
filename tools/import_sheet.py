"""격자 스프라이트시트를 캐릭터 폴더로 자른다.

오프라인 도구다. 위젯은 이걸 부르지 않는다 — 한 번 잘라 두면 `sprites/<이름>/` 이
남고 그다음부터는 PNG 만 읽는다.

    python tools/import_sheet.py 시트.png --cell 60x38 --out sprites/dog \
        --row 1=walk --row 5=idle --row 4=sit --facing left --scale 2

프레임이 가로 한 줄로만 있는 스트립이면 `--row 0=walk` 하나만 주면 된다.

**정렬에 대해:** 잘라낸 프레임들의 투명 여백을 각자 잘라내면 프레임마다 발 위치가
달라져서 캐릭터가 걸을 때 위아래로 떤다. 그래서 `--trim` 은 **한 동작 안의 모든
프레임의 합집합** 경계로 그 동작 전체를 똑같이 자른다. 동작끼리는 크기가 달라도
되는데, 그리는 쪽이 발밑 중앙을 기준으로 놓기 때문이다 (앉으면 낮아지는 게 자연스럽다).

출처가 여러 파일로 나뉘어 있으면 `--append` 로 같은 폴더에 이어 붙인다.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QRect  # noqa: E402
from PySide6.QtGui import QGuiApplication, QImage  # noqa: E402

ALPHA_FLOOR = 8      # 이보다 흐린 픽셀은 없는 것으로 친다 (안티에일리어싱 찌꺼기)


def parse_cell(text: str) -> tuple[int, int]:
    try:
        w, h = text.lower().split("x")
        return int(w), int(h)
    except ValueError:
        raise argparse.ArgumentTypeError(f"--cell 은 60x38 형식이어야 합니다: {text!r}")


def parse_row(text: str) -> tuple[int, str, int | None]:
    """`1=walk` 또는 `1=walk:4` (앞 4프레임만)."""
    if "=" not in text:
        raise argparse.ArgumentTypeError(f"--row 는 1=walk 형식이어야 합니다: {text!r}")
    index, rest = text.split("=", 1)
    count = None
    if ":" in rest:
        rest, count_text = rest.split(":", 1)
        count = int(count_text)
    try:
        return int(index), rest.strip().lower(), count
    except ValueError:
        raise argparse.ArgumentTypeError(f"행 번호가 숫자가 아닙니다: {text!r}")


def content_rect(image: QImage) -> QRect | None:
    """불투명한 픽셀이 차지하는 최소 사각형. 전부 투명하면 None."""
    left, top = image.width(), image.height()
    right = bottom = -1
    for y in range(image.height()):
        for x in range(image.width()):
            if image.pixelColor(x, y).alpha() > ALPHA_FLOOR:
                left, top = min(left, x), min(top, y)
                right, bottom = max(right, x), max(bottom, y)
    if right < 0:
        return None
    return QRect(left, top, right - left + 1, bottom - top + 1)


def slice_row(sheet: QImage, row: int, cell: tuple[int, int],
              limit: int | None) -> list[QImage]:
    """한 행을 프레임으로 자른다. 빈 칸에서 멈춘다 (행 끝 패딩)."""
    cw, ch = cell
    frames = []
    columns = sheet.width() // cw
    for col in range(columns):
        if limit is not None and len(frames) >= limit:
            break
        frame = sheet.copy(col * cw, row * ch, cw, ch)
        if content_rect(frame) is None:
            break
        frames.append(frame)
    return frames


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="스프라이트시트를 캐릭터 폴더로 자릅니다")
    ap.add_argument("sheet", type=Path)
    ap.add_argument("--cell", type=parse_cell, required=True, help="한 칸 크기, 예: 60x38")
    ap.add_argument("--out", type=Path, required=True, help="캐릭터 폴더")
    ap.add_argument("--row", type=parse_row, action="append", required=True,
                    metavar="N=동작[:프레임수]")
    ap.add_argument("--trim", action="store_true",
                    help="동작마다 그 동작 프레임 공통의 투명 여백을 잘라낸다")
    ap.add_argument("--append", action="store_true",
                    help="폴더를 비우지 않고 이 동작들만 덮어쓴다 (출처가 여러 파일일 때)")
    # 기본값을 None 으로 두면 --append 때 "준 것만 덮어쓰기" 를 구분할 수 있다.
    ap.add_argument("--facing", choices=("left", "right"), default=None)
    ap.add_argument("--scale", type=float, default=None)
    ap.add_argument("--fps", type=float, default=None)
    ap.add_argument("--action-fps", action="append", default=[],
                    metavar="동작=fps", help="동작별 fps, 예: walk=12")
    ap.add_argument("--credits", default=None, help="CREDITS.txt 에 남길 한 줄")
    args = ap.parse_args(argv)

    if not args.sheet.exists():
        print(f"시트를 찾을 수 없습니다: {args.sheet}", file=sys.stderr)
        return 1

    QGuiApplication.instance() or QGuiApplication([])   # QImage 에 필요

    sheet = QImage(str(args.sheet))
    if sheet.isNull():
        print(f"이미지를 읽지 못했습니다: {args.sheet}", file=sys.stderr)
        return 1
    sheet = sheet.convertToFormat(QImage.Format_ARGB32)

    collected: dict[str, list[QImage]] = {}
    for row, action, limit in args.row:
        frames = slice_row(sheet, row, args.cell, limit)
        if not frames:
            print(f"행 {row} 이 비어 있습니다 → {action} 건너뜀", file=sys.stderr)
            continue
        collected[action] = frames

    if args.trim:
        # 동작 안에서는 합집합 경계로 똑같이 자른다 (프레임마다 따로 자르면 발이 떤다).
        # 동작끼리 크기가 달라지는 것은 괜찮다 — 그리는 쪽이 발밑 중앙으로 맞춘다.
        trimmed = {}
        for action, frames in collected.items():
            box = None
            for frame in frames:
                rect = content_rect(frame)
                box = rect if box is None else box.united(rect)
            trimmed[action] = [f.copy(box) for f in frames] if box else frames
        collected = trimmed

    args.out.mkdir(parents=True, exist_ok=True)
    if args.append:
        # 이번에 쓰는 동작만 지운다. 프레임 수가 줄었을 때 옛 파일이 남지 않게.
        for action in collected:
            for stale in args.out.glob(f"{action}_*.png"):
                stale.unlink()
            stale = args.out / f"{action}.png"
            stale.unlink(missing_ok=True)
    else:
        for stale in args.out.glob("*.png"):
            stale.unlink()

    written = 0
    for action, frames in sorted(collected.items()):
        for i, frame in enumerate(frames):
            frame.save(str(args.out / f"{action}_{i}.png"))
            written += 1

    per_action = {}
    for item in args.action_fps:
        name, _, value = item.partition("=")
        per_action[name.strip().lower()] = float(value)

    meta_path = args.out / "meta.json"
    meta = {}
    if args.append and meta_path.exists():
        # 먼저 넣은 시트가 정한 값을 유지하고, 이번에 명시한 것만 덮어쓴다.
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except ValueError:
            meta = {}
    for key, given, default in (("fps", args.fps, 8.0),
                                ("scale", args.scale, 1.0),
                                ("facing", args.facing, "right")):
        meta[key] = given if given is not None else meta.get(key, default)
    if per_action:
        meta["actions"] = {**meta.get("actions", {}),
                           **{a: {"fps": f} for a, f in per_action.items()}}
    meta_path.write_text(
        json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    if args.credits:
        credits_path = args.out / "CREDITS.txt"
        existing = (credits_path.read_text(encoding="utf-8")
                    if args.append and credits_path.exists() else "")
        if args.credits not in existing:
            credits_path.write_text(existing + args.credits + "\n", encoding="utf-8")

    print(f"{args.out}: PNG {written}장")
    for action, frames in sorted(collected.items()):
        print(f"  {action:6s} {len(frames)}프레임 "
              f"{frames[0].width()}x{frames[0].height()}")

    # 여러 번 나눠 넣는 것이 정상 사용이므로, 다 쓰고 난 폴더를 위젯과 같은 눈으로 본다.
    import sprites
    if sprites.load_spec(args.out) is None:
        print("  ! idle 프레임이 없어 아직 캐릭터로 인식되지 않습니다", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
