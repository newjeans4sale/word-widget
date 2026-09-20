"""기본 캐릭터를 내려받아 `sprites/` 를 만든다.

한 번만 돌리면 되는 도구다. 받은 원본은 `raw/sprites/` 에 캐시하므로 다시 돌려도
네트워크를 두 번 타지 않는다.

    python tools/fetch_sprites.py            # 없는 것만
    python tools/fetch_sprites.py --force    # 다시 내려받고 다시 자름

두 캐릭터 모두 **CC0(퍼블릭 도메인)** 이라 출처를 밝힐 의무가 없다. 그래도 나중에
어디서 왔는지 알 수 있도록 각 폴더에 CREDITS.txt 를 남긴다.
"""
from __future__ import annotations

import argparse
import shutil
import sys
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

import import_sheet  # noqa: E402  (tools/ 안의 이웃 모듈)

CACHE = ROOT / "raw" / "sprites"
SPRITES = ROOT / "sprites"

DOG_CREDITS = ("Dog (husky) sprites by rmazanek - CC0 / public domain, "
               "no attribution required. https://opengameart.org/content/dog-3")
ANIME_CREDITS = ("Anime Girl by Hordana - CC0 / public domain, "
                 "no attribution required. https://opengameart.org/content/anime-girl")

DOWNLOADS = {
    "dog_medium.png": "https://opengameart.org/sites/default/files/dog_medium.png",
    "anime_walk.png": "https://opengameart.org/sites/default/files/11walk_4.png",
    "anime_blink.png": "https://opengameart.org/sites/default/files/blink%20strip%205.png",
}

# 캐릭터마다 (출력폴더, [import_sheet 인자들]).
# 한 캐릭터의 그림이 여러 파일에 흩어져 있으면 두 번째부터 --append 로 이어 붙인다.
RECIPES = {
    "dog": [
        ["{cache}/dog_medium.png", "--cell", "60x38", "--out", "{out}",
         "--row", "5=idle", "--row", "1=walk", "--row", "4=sit",
         "--trim", "--facing", "left", "--scale", "2", "--fps", "6",
         "--action-fps", "walk=10", "--credits", DOG_CREDITS],
    ],
    "anime": [
        ["{cache}/anime_blink.png", "--cell", "221x221", "--out", "{out}",
         "--row", "0=idle", "--trim", "--facing", "right", "--scale", "0.5",
         "--fps", "6", "--action-fps", "idle=4", "--credits", ANIME_CREDITS],
        ["{cache}/anime_walk.png", "--cell", "250x221", "--out", "{out}",
         "--row", "0=walk", "--trim", "--append",
         "--action-fps", "walk=12", "--credits", ANIME_CREDITS],
    ],
}


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

    print("\n완료. 트레이 > 캐릭터 에서 고를 수 있습니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
