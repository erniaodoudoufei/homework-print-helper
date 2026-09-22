from __future__ import annotations

import os
import sys
from pathlib import Path

if "--smoke-test" in sys.argv:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    # A windowed executable has no console. Keep import/startup failures observable
    # during release checks instead of leaving an invisible bootloader error dialog.
    _qa_directory = Path(sys.argv[sys.argv.index("--smoke-test") + 1]).resolve()
    _qa_directory.mkdir(parents=True, exist_ok=True)
    _qa_log = (_qa_directory / "startup.log").open("w", encoding="utf-8", buffering=1)
    sys.stdout = sys.stderr = _qa_log
    def _qa_exception(kind, value, tb):
        import traceback
        traceback.print_exception(kind, value, tb, file=_qa_log)
        _qa_log.flush()
        os._exit(1)
    sys.excepthook = _qa_exception
    print("Starting imports", flush=True)

from PySide6.QtCore import QTimer, QTranslator, QLibraryInfo
from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QMessageBox

from homework_print.window import MainWindow

if "--smoke-test" in sys.argv:
    print("Imports ready", flush=True)


def make_icon():
    pixmap = QPixmap(128, 128)
    pixmap.fill(QColor("transparent"))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QColor("#087f72"))
    painter.setBrush(QColor("#087f72"))
    painter.drawRoundedRect(2, 2, 124, 124, 28, 28)
    painter.setPen(QColor("white"))
    painter.setBrush(QColor("white"))
    painter.drawRoundedRect(32, 21, 66, 87, 6, 6)
    painter.setPen(QColor("#087f72"))
    for y, width in ((43, 40), (56, 40), (69, 28)):
        painter.fillRect(44, y, width, 5, QColor("#087f72"))
    painter.end()
    return QIcon(pixmap)


def main():
    app = QApplication(sys.argv)
    if "--smoke-test" in sys.argv:
        print("QApplication ready", flush=True)
    app.setApplicationName("作业图片打印助手")
    app.setOrganizationName("HomeworkPrint")
    app.setStyle("Fusion")
    if os.environ.get("QT_QPA_PLATFORM") == "offscreen":
        # The headless Qt platform doesn't discover Windows system fonts itself.
        for name in ("msyh.ttc", "msyhbd.ttc"):
            font_path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / name
            if font_path.exists():
                QFontDatabase.addApplicationFont(str(font_path))
    app.setFont(QFont("Microsoft YaHei UI", 10))
    app.setWindowIcon(make_icon())
    translator = QTranslator(app)
    translator.load("qtbase_zh_CN", QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath))
    app.installTranslator(translator)
    window = MainWindow()
    window.show()
    if "--smoke-test" in sys.argv:
        # Packaged release self-check; intentionally never submits a print job.
        from homework_print.selftest import run_selftest
        def check():
            try:
                index = sys.argv.index("--smoke-test")
                directory = Path(sys.argv[index + 1]).resolve()
                run_selftest(window, directory)
            except Exception:
                import traceback
                print(traceback.format_exc())
                if 'directory' in locals():
                    directory.mkdir(parents=True, exist_ok=True)
                    (directory / "smoke-error.txt").write_text(traceback.format_exc(), encoding="utf-8")
                app.exit(1)
            else:
                window.close()
                app.exit(0)
        QTimer.singleShot(100, check)
    else:
        paths = [arg for arg in sys.argv[1:] if Path(arg).suffix.lower() in (".jpg", ".jpeg", ".png")]
        if paths:
            QTimer.singleShot(100, lambda: window.import_files(paths))
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
