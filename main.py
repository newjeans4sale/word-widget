"""앱 부트스트랩.

pythonw.exe 로 실행되면 콘솔이 없다. 로깅과 excepthook 을 제일 먼저 세우지 않으면
예외가 나도 아무 흔적 없이 사라져 원인을 영영 못 찾는다.
"""
from __future__ import annotations

import argparse
import logging
import signal
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

# 얼린 배포를 고려해 __file__ 이 아니라 argv[0] 을 기준으로 삼는다.
BASE_DIR = Path(sys.argv[0]).resolve().parent
LOG_PATH = BASE_DIR / "word-widget.log"
SINGLETON_KEY = "word-widget-singleton"

log = logging.getLogger("word-widget")


def setup_logging(verbose: bool = False) -> None:
    handler = RotatingFileHandler(LOG_PATH, maxBytes=512 * 1024, backupCount=2,
                                  encoding="utf-8")
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    root.addHandler(handler)
    if verbose:
        root.addHandler(logging.StreamHandler(sys.stderr))

    def excepthook(exc_type, exc, tb):
        log.critical("처리되지 않은 예외", exc_info=(exc_type, exc, tb))
        sys.__excepthook__(exc_type, exc, tb)

    sys.excepthook = excepthook


def install_qt_message_handler() -> None:
    from PySide6.QtCore import QtMsgType, qInstallMessageHandler

    levels = {
        QtMsgType.QtDebugMsg: logging.DEBUG,
        QtMsgType.QtInfoMsg: logging.INFO,
        QtMsgType.QtWarningMsg: logging.WARNING,
        QtMsgType.QtCriticalMsg: logging.ERROR,
        QtMsgType.QtFatalMsg: logging.CRITICAL,
    }

    def handler(mode, context, message):
        logging.getLogger("qt").log(levels.get(mode, logging.INFO), "%s", message)

    qInstallMessageHandler(handler)


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="영단어 바탕화면 위젯")
    p.add_argument("--selftest", type=int, metavar="MS",
                   help="지정한 밀리초 뒤 스스로 종료한다 (기동 확인용)")
    p.add_argument("--verbose", action="store_true", help="콘솔에도 로그를 출력한다")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    setup_logging(args.verbose)

    from PySide6.QtCore import QLibraryInfo, QSharedMemory, Qt, QTimer
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QApplication

    # QApplication 생성 전에 해야 한다. 150% 배율을 2.0 으로 반올림하지 않게 한다.
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)

    install_qt_message_handler()

    app = QApplication(sys.argv)
    # 없으면 전체화면 감지로 오버레이를 숨기는 순간 앱이 통째로 종료된다.
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("word-widget")

    log.info("시작 | 인터프리터: %s", sys.executable)
    log.info("Qt 플러그인 경로: %s",
             QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath))

    # 두 번 실행되면 오버레이가 두 개 뜨고 config.json 을 두고 서로 덮어쓴다.
    shared = QSharedMemory(SINGLETON_KEY)
    if not shared.create(1):
        log.info("이미 실행 중입니다. 조용히 종료합니다.")
        return 0

    # Ctrl-C 를 받으려면 파이썬 콜백이 주기적으로 돌아야 한다.
    # 그렇지 않으면 이벤트 루프가 C 안에서 막혀 시그널이 전달되지 않는다.
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    keepalive = QTimer()
    keepalive.start(200)
    keepalive.timeout.connect(lambda: None)

    if args.selftest is not None:
        log.info("셀프테스트 모드: %dms 후 종료", args.selftest)
        QTimer.singleShot(args.selftest, app.quit)
        rc = app.exec()
        log.info("셀프테스트 종료 (rc=%d)", rc)
        return rc

    from app import WidgetApp

    widget_app = WidgetApp(app, BASE_DIR)
    widget_app.start()
    rc = app.exec()
    widget_app.shutdown()
    log.info("종료 (rc=%d)", rc)
    return rc


if __name__ == "__main__":
    sys.exit(main())
