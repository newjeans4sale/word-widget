r"""실행 파일을 만든다.

    .venv\Scripts\python.exe tools\build_exe.py

결과는 dist\word-widget\ 폴더다. 그 안의 word-widget.exe 를 더블클릭하면 뜬다.
폴더째 옮겨도 되고, 안의 words.txt 는 메모장으로 고칠 수 있다.

순서:
  1. icon.ico 가 없으면 tools/make_icon.py 로 만든다
  2. PyInstaller 로 word-widget.spec 을 빌드한다
  3. sprites/ 와 words.txt, README.md 를 dist/word-widget/ 에 복사한다
     (실행 파일 안에 넣지 않는다 - 사용자가 고치고 늘리는 파일들이다)
  4. 만든 exe 를 --selftest 로 잠깐 띄워 실제로 기동하는지 본다
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist" / "word-widget"
PY = ROOT / ".venv" / "Scripts" / "python.exe"


def run(*args) -> int:
    print("$", " ".join(str(a) for a in args))
    return subprocess.run([str(a) for a in args], cwd=str(ROOT)).returncode


def main() -> int:
    icon = ROOT / "icon.ico"
    if not icon.exists():
        if run(PY, ROOT / "tools" / "make_icon.py") != 0:
            return 1

    # 재빌드하면 dist/ 가 통째로 새로 만들어진다. 그 안에서 실제로 쓰던 설정
    # (모드, 캐릭터, 위치, 자동실행 상태) 이 날아가면 매번 다시 맞춰야 한다.
    kept_config = None
    if (DIST / "config.json").exists():
        kept_config = (DIST / "config.json").read_bytes()

    if run(PY, "-m", "PyInstaller", "--noconfirm", "--clean", "word-widget.spec") != 0:
        return 1

    if kept_config is not None:
        (DIST / "config.json").write_bytes(kept_config)
        print("이전 config.json 을 그대로 두었습니다")

    exe = DIST / "word-widget.exe"
    if not exe.exists():
        print("exe 가 만들어지지 않았습니다:", exe, file=sys.stderr)
        return 1

    # 사용자가 고치는 파일들. exe 안에 넣지 않고 옆에 둔다.
    shutil.copytree(ROOT / "sprites", DIST / "sprites", dirs_exist_ok=True)
    for name in ("words.txt", "README.md"):
        if (ROOT / name).exists():
            shutil.copy2(ROOT / name, DIST / name)
    # 개발용 config.json 은 복사하지 않는다. 첫 실행 때 기본값으로 새로 만들어지고,
    # 그 뒤로는 위에서 보존한 exe 쪽 설정이 재빌드를 넘어 이어진다.

    # 기동 확인. 2초 뒤 스스로 꺼지는 모드로 띄워 로그가 남는지 본다.
    log = DIST / "word-widget.log"
    log.unlink(missing_ok=True)
    proc = subprocess.Popen([str(exe), "--selftest", "2000"], cwd=str(DIST))
    try:
        proc.wait(timeout=30)
    except subprocess.TimeoutExpired:
        proc.kill()
        print("셀프테스트가 끝나지 않았습니다", file=sys.stderr)
        return 1
    text = log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""
    if "이미 실행 중" in text:
        # 위젯이 떠 있으면 단일 인스턴스 잠금 때문에 exe 가 바로 빠진다.
        # 빌드가 잘못된 게 아니라 확인을 못 한 것이다.
        print("셀프테스트 건너뜀: 위젯이 이미 떠 있습니다. 끄고 다시 빌드하면 확인됩니다.")
        return 0
    ok = proc.returncode == 0 and "셀프테스트 종료" in text
    print("셀프테스트:", "통과" if ok else f"실패 (rc={proc.returncode})")
    if not ok:
        print(text[-1500:], file=sys.stderr)
        return 1
    log.unlink(missing_ok=True)

    total = sum(f.stat().st_size for f in DIST.rglob("*") if f.is_file())
    print(f"\n완료: {exe}  ({total / 1024 / 1024:.0f} MB, "
          f"{sum(1 for _ in DIST.rglob('*') if _.is_file())} 파일)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
