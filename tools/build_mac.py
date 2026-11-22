"""macOS 앱을 만든다.

    .venv/bin/python tools/build_mac.py            # dist/WordWidget.app 만 만든다
    .venv/bin/python tools/build_mac.py --install  # /Applications 에 넣고 켠다

순서:
  1. 저장소의 config.json 에서 Windows 화면에만 맞는 값(글꼴, 캐릭터 좌표)을 뺀
     Mac 기본 설정을 build/mac-seed/config.json 에 만든다
  2. PyInstaller 로 word-widget-mac.spec 을 빌드한다
  3. 만든 앱을 --selftest 로 잠깐 띄워 실제로 기동하는지 본다
  4. --install 이면 /Applications 에 복사하고, 로그인 시 실행을 등록하고, 켠다
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import platform_mac  # noqa: E402

PY = ROOT / ".venv" / "bin" / "python"
APP = ROOT / "dist" / "WordWidget.app"
EXE = APP / "Contents" / "MacOS" / "word-widget"
INSTALLED = Path("/Applications/WordWidget.app")
WINDOWS_ONLY_KEYS = ("font_family", "mascot_x", "mascot_y", "anchor_x", "anchor_y")


def run(*args) -> int:
    print("$", " ".join(str(a) for a in args))
    return subprocess.run([str(a) for a in args], cwd=str(ROOT)).returncode


def write_seed_config() -> None:
    cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    for key in WINDOWS_ONLY_KEYS:
        cfg.pop(key, None)
    out = ROOT / "build" / "mac-seed" / "config.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def selftest(exe: Path) -> bool:
    log = platform_mac.DATA_DIR / "word-widget.log"
    before = log.stat().st_size if log.exists() else 0
    proc = subprocess.run([str(exe), "--selftest", "2000"], timeout=60)
    text = log.read_text(encoding="utf-8", errors="replace")[before:] if log.exists() else ""
    if "이미 실행 중" in text:
        print("위젯이 이미 떠 있어 셀프테스트를 확인하지 못했습니다", file=sys.stderr)
        return False
    if proc.returncode != 0 or "셀프테스트 종료 (rc=0)" not in text:
        print("셀프테스트 실패:\n" + text, file=sys.stderr)
        return False
    print("셀프테스트 통과")
    return True


def main() -> int:
    write_seed_config()
    if run(PY, "-m", "PyInstaller", "--noconfirm", "--clean", "word-widget-mac.spec") != 0:
        return 1
    if not EXE.exists():
        print("앱이 만들어지지 않았습니다:", APP, file=sys.stderr)
        return 1
    if not selftest(EXE):
        return 1

    if "--install" in sys.argv:
        if INSTALLED.exists():
            shutil.rmtree(INSTALLED)
        shutil.copytree(APP, INSTALLED, symlinks=True)
        installed_exe = INSTALLED / "Contents" / "MacOS" / "word-widget"
        platform_mac.set_autostart(True, platform_mac.autostart_command(installed_exe))
        run("open", INSTALLED)
        print("설치:", INSTALLED)
    return 0


if __name__ == "__main__":
    sys.exit(main())
