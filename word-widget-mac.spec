# -*- mode: python ; coding: utf-8 -*-
"""macOS 용 PyInstaller 레시피. tools/build_mac.py 가 이 파일로 빌드한다.

결과는 dist/WordWidget.app 이다. Dock 에 뜨지 않고 메뉴 막대 아이콘만 있다.

단어장, 설정, 캐릭터는 seed/ 로 넣어 둔다. 앱은 처음 뜰 때 이것을
~/Library/Application Support/word-widget 로 꺼내 놓고 거기서 읽는다 (main.py).
seed/config.json 은 tools/build_mac.py 가 build/ 에 만든다.
"""

a = Analysis(
    ["main.py"],
    pathex=["."],
    binaries=[],
    datas=[
        ("words.txt", "seed"),
        ("README.md", "seed"),
        ("sprites", "seed/sprites"),
        ("build/mac-seed/config.json", "seed"),
    ],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
        "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets", "PySide6.QtQuick3D",
        "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets", "PySide6.QtNetwork",
        "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtPdf", "PySide6.QtPdfWidgets",
        "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.Qt3DCore",
        "PySide6.Qt3DRender", "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets",
        "PySide6.QtSvg", "PySide6.QtSvgWidgets", "PySide6.QtPrintSupport",
        "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.QtUiTools", "PySide6.QtXml",
        "tkinter", "unittest", "pytest", "PIL", "numpy",
    ],
    noarchive=False,
)

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
    console=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="word-widget",
)
app = BUNDLE(
    coll,
    name="WordWidget.app",
    bundle_identifier="io.github.newjeans4sale.word-widget",
    info_plist={
        "CFBundleDisplayName": "Word Widget",
        "CFBundleShortVersionString": "1.0",
        # Dock 과 Cmd+Tab 에 뜨지 않는다. Windows 판이 작업표시줄에 안 뜨는 것과 같다.
        "LSUIElement": True,
        "NSHighResolutionCapable": True,
    },
)
