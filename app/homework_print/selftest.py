"""Packaged, offline smoke test. No access to a physical printer is requested."""
from __future__ import annotations

from pathlib import Path
import json
import time

import cv2
import numpy as np
from PIL import Image
from PySide6.QtCore import QSize, QSettings
from PySide6.QtPdf import QPdfDocument
from PySide6.QtWidgets import QApplication

from .models import PrintOptions
from .print_dialog import PrintDialog
from .printing import export_pdf
from .processing import process, load_rgb


def wait_idle(window, timeout=30):
    start = time.monotonic()
    while window.job or window.preview_timer.isActive() or window.edit_timer.isActive():
        QApplication.processEvents()
        time.sleep(.01)
        if time.monotonic() - start > timeout:
            raise AssertionError("等待后台处理超时")
    QApplication.processEvents()


def run_selftest(window, destination: Path):
    destination.mkdir(parents=True, exist_ok=True)
    window.settings = QSettings(str(destination / "test-settings.ini"), QSettings.Format.IniFormat)
    # Colored strokes, thin grid and uneven paper illumination.
    height, width = 1200, 850
    paper = np.zeros((height, width, 3), np.uint8)
    for y in range(height):
        paper[y, :] = [230 - y * 30 // height, 223 - y * 30 // height, 199 - y * 30 // height]
    for y in range(150, 1080, 100):
        cv2.line(paper, (60, y), (790, y), (50, 85, 75), 1)
    cv2.putText(paper, "HOMEWORK  12345", (70, 105), cv2.FONT_HERSHEY_SIMPLEX, 1.25, (25, 30, 32), 3)
    cv2.putText(paper, "Keep red notes", (80, 240), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (155, 20, 15), 2)
    source = destination / "测试图片.png"
    Image.fromarray(paper).save(source)
    landscape = np.full((600, 1000, 3), 238, np.uint8)
    cv2.putText(landscape, "WEEKLY SCHEDULE", (65, 100), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (25, 45, 60), 3)
    for y in range(150, 550, 80):
        cv2.line(landscape, (50, y), (950, y), (80, 80, 80), 1)
    source2 = destination / "横向测试.png"
    Image.fromarray(landscape).save(source2)
    window.import_files([source, source2])
    wait_idle(window)
    assert len(window.pages) == 2
    window.list.setCurrentRow(0)
    old = window.current_page().settings
    window.white_slider.setValue(60)
    window.commit_controls()
    wait_idle(window)
    assert window.current_page().settings.whitening == 60
    window.undo()
    wait_idle(window)
    assert window.current_page().settings == old
    window.redo()
    wait_idle(window)
    assert window.current_page().settings.whitening == 60
    window.compare.setCurrentIndex(2)
    QApplication.processEvents()
    window.grab().save(str(destination / "应用界面.png"))
    prepared = []
    for i, page in enumerate(window.ordered_pages()):
        result = process(load_rgb(page.source), page.settings)
        target = destination / f"处理结果-{i + 1}.png"
        Image.fromarray(result).save(target)
        prepared.append((target, result.shape[1], result.shape[0], page.title))
    target_pdf = destination / "混合方向测试.pdf"
    if target_pdf.exists():
        # Selftest owns this exact named artifact in its explicit output directory.
        target_pdf.unlink()
    export_pdf(target_pdf, prepared, PrintOptions())
    document = QPdfDocument()
    assert document.load(str(target_pdf)) == QPdfDocument.Error.None_
    assert document.pageCount() == 2
    sizes = [(document.pagePointSize(i).width(), document.pagePointSize(i).height()) for i in range(2)]
    assert sizes[0][1] > sizes[0][0] and sizes[1][0] > sizes[1][1], sizes
    for i in range(2):
        size = document.pagePointSize(i)
        image = document.render(i, QSize(round(size.width() * 1.4), round(size.height() * 1.4)))
        assert not image.isNull()
        image.save(str(destination / f"PDF页面-{i + 1}.png"))
    document.close()
    dialog = PrintDialog(prepared, destination, window.settings, window)
    dialog.show()
    for _ in range(8):
        QApplication.processEvents()
        time.sleep(.05)
    dialog.refresh_preview()
    QApplication.processEvents()
    assert not dialog.preview_error, dialog.preview_error
    assert dialog.preview.pageCount() == 2
    dialog.grab().save(str(destination / "打印预览.png"))
    dialog.refresh_timer.stop()
    dialog.close()
    dialog.deleteLater()
    (destination / "smoke-result.json").write_text(json.dumps({"status": "passed", "pages": len(prepared),
        "pdf_sizes_points": sizes, "physical_print_submitted": False,
        "checks": ["import", "processing", "undo", "redo", "preview", "PDF", "mixed_orientation"]},
        ensure_ascii=False, indent=2), encoding="utf-8")
