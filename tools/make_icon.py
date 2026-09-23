r"""앱 아이콘(icon.ico)을 스프라이트 한 장에서 만든다.

    .venv\Scripts\python.exe tools\make_icon.py [sprites/tan/idle_0.png] [--out icon.ico]

ICO 는 여러 크기를 한 파일에 담는다. Windows 는 상황마다 다른 크기를 꺼내 쓰므로
(작업표시줄 32, 탐색기 큰 아이콘 256, 창 제목줄 16) 전부 넣어 두어야 어느 자리에서든
번지지 않는다. 도트 그림이라 정수배 nearest 로 키우고, 정수배가 안 되는 크기는 그
아래 정수배로 키운 뒤 가운데에 놓는다 — 어중간한 배수로 늘리면 픽셀이 들쭉날쭉해진다.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter  # noqa: E402

SIZES = (16, 24, 32, 48, 64, 128, 256)
DEFAULT_SPRITE = ROOT / "sprites" / "tan" / "idle_0.png"


def fit_square(src: QImage, size: int) -> QImage:
    """정사각형 size 안에 스프라이트를 정수배로 키워 가운데 놓는다."""
    factor = max(1, min(size // src.width(), size // src.height()))
    scaled = src.scaled(src.width() * factor, src.height() * factor,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.FastTransformation)
    if scaled.width() > size or scaled.height() > size:
        # 원본이 아이콘보다 큰 경우(16px 칸)에는 줄일 수밖에 없다. 부드럽게 줄인다.
        scaled = src.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation)
    canvas = QImage(size, size, QImage.Format.Format_ARGB32)
    canvas.fill(QColor(0, 0, 0, 0))
    p = QPainter(canvas)
    p.drawImage((size - scaled.width()) // 2, (size - scaled.height()) // 2, scaled)
    p.end()
    return canvas


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="스프라이트로 앱 아이콘을 만듭니다")
    ap.add_argument("sprite", nargs="?", type=Path, default=DEFAULT_SPRITE)
    ap.add_argument("--out", type=Path, default=ROOT / "icon.ico")
    args = ap.parse_args(argv)

    QGuiApplication.instance() or QGuiApplication([])
    src = QImage(str(args.sprite))
    if src.isNull():
        print(f"그림을 읽지 못했습니다: {args.sprite}", file=sys.stderr)
        return 1
    src = src.convertToFormat(QImage.Format.Format_ARGB32)

    # Qt 의 ICO 쓰기는 한 번에 한 그림만 넣는다. 여러 크기를 담으려면 ICO 컨테이너를
    # 직접 조립해야 한다 - 각 크기를 PNG 로 인코딩해 ICO 헤더 뒤에 이어 붙인다
    # (Vista 이후 Windows 는 ICO 안의 PNG 항목을 읽는다).
    from PySide6.QtCore import QBuffer, QIODevice
    import struct

    entries = []
    for size in SIZES:
        img = fit_square(src, size)
        buf = QBuffer()
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        img.save(buf, "PNG")
        entries.append((size, bytes(buf.data())))
        buf.close()

    header = struct.pack("<HHH", 0, 1, len(entries))
    offset = len(header) + 16 * len(entries)
    directory = b""
    payload = b""
    for size, png in entries:
        wh = 0 if size == 256 else size          # 256 은 0 으로 적는 규약
        directory += struct.pack("<BBBBHHII", wh, wh, 0, 0, 1, 32, len(png), offset)
        payload += png
        offset += len(png)

    args.out.write_bytes(header + directory + payload)
    print(f"{args.out}: {len(entries)}개 크기 ({', '.join(str(s) for s in SIZES)}) "
          f"<- {args.sprite.relative_to(ROOT) if args.sprite.is_relative_to(ROOT) else args.sprite}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
