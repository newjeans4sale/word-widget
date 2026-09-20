"""기본 캐릭터를 내려받아 `sprites/` 를 만든다.

한 번만 돌리면 되는 도구다. 받은 원본은 `raw/sprites/` 에 캐시하므로 다시 돌려도
네트워크를 두 번 타지 않는다.

    python tools/fetch_sprites.py            # 없는 것만
    python tools/fetch_sprites.py --force    # 다시 내려받고 다시 자름

`husky` 는 CC0 라 그냥 내려받는다. `dog-00`~`dog-23` 은 itch.io 의 Pixel Dogs 라
사람이 직접 받아 `raw/inbox/` 에 넣어 두어야 한다 — itch.io 는 "가격을 직접 정하기"
화면을 거치기 때문이다. zip 이 있으면 알아서 풀고 자른다.

어디서 온 그림인지 알 수 있도록 캐릭터 폴더마다 CREDITS.txt 를 남긴다.
Pixel Dogs 는 CC0 가 아니다 — 기부하지 못할 경우 크레딧을 부탁한다고 되어 있다.
"""
from __future__ import annotations

import argparse
import shutil
import sys
import zipfile
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

import import_sheet  # noqa: E402  (tools/ 안의 이웃 모듈)

CACHE = ROOT / "raw" / "sprites"
INBOX = ROOT / "raw" / "inbox"
SPRITES = ROOT / "sprites"

# --- 직접 받아야 하는 팩 -------------------------------------------------
# itch.io 는 "가격을 직접 정하기" 화면을 거치므로 이 스크립트가 대신 받지 않는다.
# zip 을 raw/inbox/ 에 넣어 두면 여기서 알아서 풀고 자른다.
PIXEL_DOGS_ZIP = "PixelDogsSprites.zip"
PIXEL_DOGS_URL = "https://benvictus.itch.io/pixel-dogs"
PIXEL_DOGS_CREDITS = (
    "Pixel Dogs by Benvictus - " + PIXEL_DOGS_URL + chr(10) +
    "Name-your-own-price, commercial use allowed. "
    "The artist asks for a credit if you cannot donate.")
# 한 칸은 64x48 이고 24장이 두 가지 배치로 나뉜다. 혀를 문 쪽(홀수 번호)은
# 걷기/달리기 행이 한 벌뿐이라 9행이 아니라 7행이다. idle/sit/walk 의 행 번호는
# 둘 다 같고 sleep(웅크려 자기) 만 마지막 행에 있으므로, 그 행은 찾아서 쓴다.
PIXEL_DOGS_CELL = (64, 48)
PIXEL_DOGS_ROWS = ["0=idle", "4=walk", "1=sit"]

HUSKY_CREDITS = ("Dog (husky) sprites by rmazanek - CC0 / public domain, "
                 "no attribution required. https://opengameart.org/content/dog-3")

DOWNLOADS = {
    "dog_medium.png": "https://opengameart.org/sites/default/files/dog_medium.png",
}

# 캐릭터마다 (출력폴더, [import_sheet 인자들]).
# 한 캐릭터의 그림이 여러 파일에 흩어져 있으면 두 번째부터 --append 로 이어 붙인다.
RECIPES = {
    "husky": [
        ["{cache}/dog_medium.png", "--cell", "60x38", "--out", "{out}",
         "--row", "5=idle", "--row", "1=walk", "--row", "4=sit",
         "--trim", "--facing", "left", "--scale", "2", "--fps", "6",
         "--action-fps", "walk=10", "--credits", HUSKY_CREDITS],
    ],
}


def last_content_row(path: Path, cell) -> int:
    """내용이 있는 마지막 행 번호. 배치가 다른 시트를 같은 레시피로 다루기 위한 것."""
    from PySide6.QtGui import QGuiApplication, QImage

    QGuiApplication.instance() or QGuiApplication([])
    img = QImage(str(path)).convertToFormat(QImage.Format_ARGB32)
    cw, ch = cell
    last = -1
    for row in range(img.height() // ch):
        # 보통 첫 칸에서 바로 끝난다 (any 가 짧게 끊는다).
        if any(import_sheet.content_rect(img.copy(c * cw, row * ch, cw, ch)) is not None
               for c in range(img.width() // cw)):
            last = row
    return last


def pixel_dogs(force: bool) -> int:
    """raw/inbox 의 Pixel Dogs zip 을 풀어 24마리를 전부 만든다."""
    zip_path = INBOX / PIXEL_DOGS_ZIP
    if not zip_path.exists():
        print("  " + PIXEL_DOGS_ZIP + " 이 없어 건너뜁니다.")
        print("  " + PIXEL_DOGS_URL + " 에서 받아 " + str(INBOX) + " 에 넣어주세요.")
        return 0

    extracted = CACHE / "pixeldogs"
    if force or not extracted.exists():
        shutil.rmtree(extracted, ignore_errors=True)
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(extracted)

    sheets = sorted(extracted.rglob("Dogs-Remastered-*.png"))
    if not sheets:
        print("  ! zip 안에서 시트를 찾지 못했습니다: " + str(zip_path), file=sys.stderr)
        return 1

    made = 0
    for sheet in sheets:
        name = "dog-" + sheet.stem.rsplit("-", 1)[1]
        out = SPRITES / name
        if out.exists() and not force:
            continue
        shutil.rmtree(out, ignore_errors=True)
        argv = [str(sheet), "--cell", "64x48", "--out", str(out), "--trim",
                "--facing", "left", "--scale", "2", "--fps", "6",
                "--action-fps", "walk=10", "--action-fps", "sleep=3",
                "--credits", PIXEL_DOGS_CREDITS]
        rows = list(PIXEL_DOGS_ROWS)
        sleep_row = last_content_row(sheet, PIXEL_DOGS_CELL)
        if sleep_row > 4:
            rows.append(str(sleep_row) + "=sleep")
        for row in rows:
            argv += ["--row", row]
        if import_sheet.main(argv) != 0:
            print("  ! " + name + " 을 만들지 못했습니다", file=sys.stderr)
            return 1
        made += 1
    print("  Pixel Dogs " + (str(made) + "마리" if made else "이미 있음"))
    return 0


def download(name: str, url: str, force: bool) -> Path:
    CACHE.mkdir(parents=True, exist_ok=True)
    target = CACHE / name
    if target.exists() and not force:
        print(f"  캐시 사용: {name}")
        return target
    print(f"  내려받는 중: {url}")
    try:
        with urllib.request.urlopen(url, timeout=60) as response:
            data = response.read()
    except (urllib.error.URLError, TimeoutError) as exc:
        raise SystemExit(f"내려받지 못했습니다: {url}\n  {exc}")
    if not data.startswith(b"\x89PNG"):
        raise SystemExit(f"PNG 가 아닙니다: {url} (사이트가 바뀌었을 수 있습니다)")
    target.write_bytes(data)
    return target


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="기본 캐릭터 스프라이트를 준비합니다")
    ap.add_argument("--force", action="store_true", help="다시 내려받고 다시 자릅니다")
    ap.add_argument("--only", action="append", choices=sorted(RECIPES),
                    help="이 캐릭터만 (여러 번 줄 수 있음)")
    args = ap.parse_args(argv)

    wanted = args.only or sorted(RECIPES)

    print("1) 원본 내려받기")
    for name, url in DOWNLOADS.items():
        download(name, url, args.force)

    print("2) 자르기")
    for character in wanted:
        out = SPRITES / character
        if out.exists() and not args.force:
            print(f"  이미 있음, 건너뜀: sprites/{character} (다시 만들려면 --force)")
            continue
        if out.exists():
            shutil.rmtree(out)
        for recipe in RECIPES[character]:
            argv_slice = [part.format(cache=CACHE, out=out) for part in recipe]
            if import_sheet.main(argv_slice) != 0:
                print(f"  ! sprites/{character} 를 만들지 못했습니다", file=sys.stderr)
                return 1

    print("3) 직접 받은 팩")
    if pixel_dogs(args.force) != 0:
        return 1

    print("\n완료. 트레이 > 캐릭터 에서 고를 수 있습니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
