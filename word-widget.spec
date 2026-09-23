# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 레시피. tools/build_exe.py 가 이 파일로 빌드한다.

onedir 로 만든다. onefile 은 실행할 때마다 임시 폴더에 풀어서 시작이 몇 초 느리고
백신이 자주 잡는다. 부팅 때 자동 실행되는 위젯에는 맞지 않는다.

sprites/ 와 words.txt 는 여기 넣지 않는다. 앱이 실행 파일 옆 폴더에서 읽으므로
(main.py 의 BASE_DIR) 빌드 스크립트가 dist/ 에 그대로 복사한다. 그래야 사용자가
단어장을 메모장으로 고치고 캐릭터 폴더를 떨궈 넣을 수 있다.
"""

import re
import sys
from pathlib import Path

# conda 기반 파이썬의 _ctypes/_lzma/_bz2 는 Library/bin 의 DLL 에 기대는데 PyInstaller 가
# 그 폴더를 찾지 못한다. 없으면 얼린 exe 가 `import ctypes` 에서 죽는다 (실제로 죽었다).
_conda_bin = Path(sys.base_prefix) / "Library" / "bin"
_extra_dlls = [(str(_conda_bin / n), ".")
               for n in ("ffi.dll", "liblzma.dll", "LIBBZ2.dll")
               if (_conda_bin / n).exists()]

a = Analysis(
    ["main.py"],
    pathex=["."],
    binaries=_extra_dlls,
    datas=[],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    # 쓰지 않는 Qt 모듈. PySide6 훅이 통째로 끌어오면 수백 MB 가 된다.
    excludes=[
        "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
        "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets", "PySide6.QtQuick3D",
        "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets", "PySide6.QtNetwork",
        "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtPdf", "PySide6.QtPdfWidgets",
        "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.Qt3DCore",
        "PySide6.Qt3DRender", "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets",
        "PySide6.QtSvg", "PySide6.QtSvgWidgets", "PySide6.QtPrintSupport",
        "PySide6.QtBluetooth", "PySide6.QtNfc", "PySide6.QtPositioning",
        "PySide6.QtLocation", "PySide6.QtSensors", "PySide6.QtSerialPort",
        "PySide6.QtWebSockets", "PySide6.QtWebChannel", "PySide6.QtRemoteObjects",
        "PySide6.QtTextToSpeech", "PySide6.QtDesigner", "PySide6.QtHelp",
        "PySide6.QtUiTools", "PySide6.QtXml", "PySide6.QtConcurrent",
        "PySide6.QtStateMachine", "PySide6.QtScxml", "PySide6.QtHttpServer",
        "PySide6.QtSpatialAudio", "PySide6.QtGraphs", "PySide6.QtAsyncio",
        "tkinter", "unittest", "pytest", "PIL", "numpy",
        # 네트워크를 안 쓴다. 이걸 빼면 libcrypto(5MB) 가 같이 빠진다.
        "ssl", "_ssl", "_hashlib",
    ],
    noarchive=False,
)


def _keep_pyside(dest: str) -> bool:
    """QtWidgets 앱이 실제로 쓰는 것만 남긴다.

    PySide6 훅은 Quick/Qml/Pdf/소프트웨어 OpenGL 까지 통째로 끌어와 87MB 가 된다.
    excludes 는 파이썬 모듈만 막고 DLL 은 막지 못하므로 여기서 걸러낸다.
    """
    d = dest.replace("\\", "/")
    if not d.startswith("PySide6/"):
        return True
    name = d.rsplit("/", 1)[-1]
    if re.match(r"(Qt6Core|Qt6Gui|Qt6Widgets|pyside6)\.", name):
        return True
    if name in ("QtCore.pyd", "QtGui.pyd", "QtWidgets.pyd"):
        return True
    if re.search(r"(MSVCP|VCRUNTIME|concrt)140", name, re.I):
        return True
    if "/plugins/" in d:
        if re.search(r"/plugins/(platforms|styles|platforminputcontexts|generic)/", d):
            return True
        if "/plugins/imageformats/" in d and not re.search(r"q(pdf|svg)", name):
            return True
        return False
    return name.endswith((".py", ".pyi", ".conf", ".txt"))


_before = len(a.binaries) + len(a.datas)
a.binaries = [b for b in a.binaries if _keep_pyside(b[0])]
a.datas = [d for d in a.datas if _keep_pyside(d[0])]
print(f"PySide6 화이트리스트: {_before} -> {len(a.binaries) + len(a.datas)} 항목")

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="word-widget",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,          # 콘솔 창이 뜨면 안 된다 (pythonw 와 같은 역할)
    icon="icon.ico",
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="word-widget",
)
