"""Sample-specific manual QA: corner choices below are review data, not app defaults."""
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from pathlib import Path
from dataclasses import replace
from hashlib import sha256
from threading import Event
import json

from PIL import Image
from PySide6.QtCore import QSettings, QSize
from PySide6.QtGui import QFontDatabase, QFont
from PySide6.QtPdf import QPdfDocument
from PySide6.QtWidgets import QApplication

from homework_print.models import PrintOptions
from homework_print.outputs import prepare_pages
from homework_print.print_dialog import PrintDialog
from homework_print.printing import export_pdf
from homework_print.processing import process, load_rgb, resize_preview
from homework_print.selftest import wait_idle
from homework_print.window import MainWindow
from homework_print.widgets import GeometryDialog

root = Path(__file__).resolve().parent
output = root.parent / "示例处理结果"
output.mkdir(exist_ok=True)
qa = root / "qa" / "real"
qa.mkdir(parents=True, exist_ok=True)
app = QApplication([])
app.setStyle("Fusion")
for font in ("msyh.ttc", "msyhbd.ttc"):
    QFontDatabase.addApplicationFont(str(Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / font))
app.setFont(QFont("Microsoft YaHei UI", 10))
window = MainWindow(QSettings(str(qa / "settings.ini"), QSettings.Format.IniFormat))
window.show()
sources = sorted(root.parent.glob("*.jpg"))
hashes = {p.name: sha256(p.read_bytes()).hexdigest() for p in sources}
window.import_files(sources)
wait_idle(window)
window.compare.setCurrentIndex(2)
app.processEvents()
window.grab().save(str(qa / "写字示范-前后对比.png"))

window.list.setCurrentRow(2)
page = window.current_page()
# Chosen against the original photo; the lower-left physical corner lies outside it.
quad = ((.059, .145), (.897, .174), (.924, .972), (.020, .999))
window.change_page(replace(page.settings, quad=quad, deskew=0, crop=(.01, .015, .99, .985)), "课程表：手动四角校正，轻裁外围纸边")
wait_idle(window)
app.processEvents()
window.grab().save(str(qa / "课程表-前后对比.png"))
dialog = GeometryDialog(page.original_preview, "quad", quad, window)
dialog.show()
app.processEvents()
dialog.grab().save(str(qa / "四角调整.png"))
dialog.close()

names = ["数字5-彩色去底.png", "数字4-彩色去底.png", "课程表-四角校正去底.png"]
prepared = []
for p, name in zip(window.ordered_pages(), names):
    rgb = process(load_rgb(p.source), p.settings)
    target = output / name
    Image.fromarray(rgb).save(target, dpi=(300, 300))
    Image.fromarray(resize_preview(rgb, 1500)).save(qa / name)
    prepared.append((target, rgb.shape[1], rgb.shape[0], name))

pdf = output / "三张样图-A4打印.pdf"
if pdf.exists():
    pdf.unlink()
export_pdf(pdf, prepared, PrintOptions())
print_dialog = PrintDialog(prepared, output, window.settings, window)
print_dialog.show()
app.processEvents()
print_dialog.refresh_preview()
print_dialog.preview.setCurrentPage(3)
app.processEvents()
assert not print_dialog.preview_error
print_dialog.grab().save(str(qa / "课程表-A4打印预览.png"))
print_dialog.refresh_timer.stop()
print_dialog.close()

document = QPdfDocument()
document.load(str(pdf))
assert document.pageCount() == 3
for i in range(3):
    size = document.pagePointSize(i)
    document.render(i, QSize(round(size.width() * 1.5), round(size.height() * 1.5))).save(str(qa / f"PDF第{i+1}页.png"))
document.close()
assert all(sha256(p.read_bytes()).hexdigest() == hashes[p.name] for p in sources)
(qa / "report.json").write_text(json.dumps({"originals_unchanged": True,
    "source_sha256": hashes, "course_table_manual_quad": quad, "pdf_pages": 3,
    "physical_print_submitted": False}, ensure_ascii=False, indent=2), encoding="utf-8")
window.close()
print("Sample QA completed; original files unchanged. No physical printing.")
