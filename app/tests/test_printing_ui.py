import time
from dataclasses import replace
from pathlib import Path

import numpy as np
from PIL import Image
from pypdf import PdfReader
from PySide6.QtCore import QRectF, QSettings
from PySide6.QtWidgets import QApplication

from homework_print.models import EditSettings, PrintOptions
from homework_print.printing import export_pdf, fit_rect
from homework_print.selftest import run_selftest, wait_idle
from homework_print.window import MainWindow


def test_aspect_fit():
    result = fit_rect(400, 200, QRectF(10, 20, 100, 100))
    assert result == QRectF(10, 45, 100, 50)


def test_pdf_mixed_orientation_range_and_existing_file(qt_app, tmp_path):
    pages = []
    for i, (w, h) in enumerate([(500, 800), (900, 600)]):
        p = tmp_path / f"page-{i}.png"
        Image.new("RGB", (w, h), (200, 20, 20)).save(p)
        pages.append((p, w, h, p.name))
    target = tmp_path / "结果.pdf"
    export_pdf(target, pages, PrintOptions())
    reader = PdfReader(target)
    assert len(reader.pages) == 2
    for page, landscape in zip(reader.pages, [False, True]):
        w, h = float(page.mediabox.width), float(page.mediabox.height)
        assert (w > h) == landscape
        assert abs(min(w, h) - 595.28) < 1
        assert abs(max(w, h) - 841.89) < 1
        assert len(page.images) == 1
    original = target.read_bytes()
    import pytest
    with pytest.raises(FileExistsError):
        export_pdf(target, pages, PrintOptions())
    assert target.read_bytes() == original
    gray = tmp_path / "黑白.pdf"
    export_pdf(gray, pages[1:], PrintOptions(grayscale=True))
    reader = PdfReader(gray)
    assert len(reader.pages) == 1
    rgb = np.asarray(reader.pages[0].images[0].image.convert("RGB"))
    assert np.array_equal(rgb[:, :, 0], rgb[:, :, 1])


def test_source_smoke(qt_app, tmp_path):
    window = MainWindow(QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat))
    window.show()
    try:
        run_selftest(window, tmp_path)
    finally:
        wait_idle(window)
        window.close()
        qt_app.processEvents()


def test_selection_edits_sort_reset_and_remove(qt_app, tmp_path):
    paths = []
    for i in range(3):
        p = tmp_path / f"作业{i}.png"
        Image.new("RGB", (200 + i * 30, 300), (220, 210, 180)).save(p)
        paths.append(p)
    window = MainWindow(QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat))
    try:
        window.import_files(paths)
        wait_idle(window)
        page0 = window.current_page()
        window.white_slider.setValue(42)
        window.list.setCurrentRow(1)
        wait_idle(window)
        assert page0.settings.whitening == 42
        assert window.current_page().settings.whitening == 75
        window.move_current(-1)
        assert window.ordered_pages()[0].source == paths[1]
        window.rotate_current(1)
        wait_idle(window)
        assert window.current_page().settings.rotation == 1
        window.reset_current()
        wait_idle(window)
        assert window.current_page().settings == EditSettings(whitening=0, ink=0)
        window.undo()
        wait_idle(window)
        assert window.current_page().settings.rotation == 1
        window.remove_current()
        assert len(window.pages) == 2
    finally:
        wait_idle(window)
        window.close()


def test_clipboard_import(qt_app, tmp_path):
    from PySide6.QtGui import QImage, QColor
    image = QImage(200, 300, QImage.Format.Format_RGB888)
    image.fill(QColor(235, 225, 200))
    qt_app.clipboard().setImage(image)
    window = MainWindow(QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat))
    try:
        window.paste_image()
        wait_idle(window)
        assert len(window.pages) == 1
        assert window.current_page().source.exists()
        assert window.default_output_directory() != window.temp_path
    finally:
        wait_idle(window)
        window.close()
        qt_app.clipboard().clear()


def test_preview_matches_pdf_page_geometry(qt_app, tmp_path):
    from PySide6.QtCore import QSize
    from PySide6.QtPdf import QPdfDocument
    from homework_print.printing import make_printer, preview_page
    source = tmp_path / "red.png"
    Image.new("RGB", (900, 600), (220, 15, 15)).save(source)
    page = (source, 900, 600, "red")
    options = PrintOptions(margin_mm=10)
    target = tmp_path / "preview-check.pdf"
    export_pdf(target, [page], options)
    printer = make_printer(pdf_path=tmp_path / "unused.pdf")
    preview = preview_page(printer, page, options, 1000)
    document = QPdfDocument()
    document.load(str(target))
    rendered = document.render(0, preview.size()).convertToFormat(preview.format())
    def red_bounds(image):
        raw = np.frombuffer(image.constBits(), np.uint8).reshape(image.height(), image.bytesPerLine())
        rgb = raw[:, :image.width() * 3].reshape(image.height(), image.width(), 3)
        y, x = np.where((rgb[:, :, 0] > 150) & (rgb[:, :, 1] < 70))
        return np.array([x.min(), y.min(), x.max(), y.max()])
    assert np.max(np.abs(red_bounds(preview) - red_bounds(rendered))) <= 2
    assert red_bounds(preview)[0] >= 1000 * 10 / 297 - 2
    document.close()


def test_no_printer_and_close_without_submission(qt_app, tmp_path, monkeypatch):
    import homework_print.print_dialog as module
    p = tmp_path / "page.png"
    Image.new("RGB", (100, 160), "white").save(p)
    monkeypatch.setattr(module.QPrinterInfo, "availablePrinterNames", lambda: [])
    calls = []
    monkeypatch.setattr(module, "render_pages", lambda *a, **kw: calls.append(a))
    dialog = module.PrintDialog([(p, 100, 160, "test")], tmp_path,
                                 QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat))
    try:
        dialog.refresh_preview()
        assert not dialog.print_button.isEnabled()
        assert dialog.preview.pageCount() == 1
        assert not dialog.preview_error
        dialog.reject()
        assert not calls
    finally:
        dialog.refresh_timer.stop()
        dialog.close()


def test_pdf_keeps_driver_margins_when_user_requests_zero(qt_app, tmp_path):
    from PySide6.QtCore import QMarginsF
    from PySide6.QtPdf import QPdfDocument
    from PySide6.QtPrintSupport import QPrinter
    from homework_print.printing import preview_page
    class HardwareMargins(QPrinter):
        def pageLayout(self):
            layout = super().pageLayout()
            layout.setUnits(layout.Unit.Millimeter)
            layout.setMinimumMargins(QMarginsF(7, 8, 9, 10))
            return layout
    reference = HardwareMargins(QPrinter.PrinterMode.HighResolution)
    reference.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
    reference.setResolution(300)
    source = tmp_path / "page.png"
    Image.new("RGB", (210, 297), (220, 15, 15)).save(source)
    page = (source, 210, 297, "page")
    options = PrintOptions(margin_mm=0)
    preview = preview_page(reference, page, options, 1000)
    target = tmp_path / "driver-margins.pdf"
    export_pdf(target, [page], options, layout_printer=reference)
    document = QPdfDocument()
    document.load(str(target))
    rendered = document.render(0, preview.size()).convertToFormat(preview.format())
    def bounds(image):
        raw = np.frombuffer(image.constBits(), np.uint8).reshape(image.height(), image.bytesPerLine())
        rgb = raw[:, :image.width() * 3].reshape(image.height(), image.width(), 3)
        y, x = np.where((rgb[:, :, 0] > 150) & (rgb[:, :, 1] < 70))
        return np.array([x.min(), y.min(), x.max(), y.max()])
    assert np.max(np.abs(bounds(preview) - bounds(rendered))) <= 2
    assert bounds(rendered)[0] >= 1000 * 7 / 297 - 2
    assert bounds(rendered)[1] >= 1000 * 8 / 297 - 2
    document.close()


def test_geometry_mouse_interaction(qt_app):
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtTest import QTest
    from homework_print.widgets import GeometryDialog
    image = np.full((500, 400, 3), 230, np.uint8)
    dialog = GeometryDialog(image, "quad")
    dialog.show()
    qt_app.processEvents()
    view = dialog.view
    initial = dialog.selection()[0]
    point = view.mapFromScene(view.scaled_point(view.quad[0]))
    target = view.mapFromScene(QPointF(60, 70))
    QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=point)
    QTest.mouseMove(view.viewport(), target, 20)
    QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=target)
    assert dialog.selection()[0] != initial
    assert abs(dialog.selection()[0][0] - 60 / 399) < .01
    dialog.accept()
    assert dialog.result() == dialog.DialogCode.Accepted
    crop = GeometryDialog(image, "crop")
    crop.show()
    qt_app.processEvents()
    view = crop.view
    a = view.mapFromScene(QPointF(40, 50))
    b = view.mapFromScene(QPointF(350, 430))
    QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=a)
    QTest.mouseMove(view.viewport(), b, 20)
    QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=b)
    assert abs(crop.selection()[0] - .1) < .01
    assert abs(crop.selection()[2] - .875) < .01
    crop.close()


def test_export_is_triggered_only_by_print_click(qt_app, tmp_path, monkeypatch):
    import homework_print.print_dialog as module
    from PySide6.QtPrintSupport import QPrinterInfo
    if not QPrinterInfo.availablePrinterNames():
        import pytest
        pytest.skip("此机器未安装打印机驱动")
    p = tmp_path / "page.png"
    Image.new("RGB", (100, 160), "white").save(p)
    calls = []
    def record(printer, pages, options, indices):
        calls.append((printer.printerName(), list(indices), options.grayscale))
    monkeypatch.setattr(module, "render_pages", record)
    monkeypatch.setattr(module.QMessageBox, "information", lambda *a: None)
    dialog = module.PrintDialog([(p, 100, 160, "test")] * 3, tmp_path,
                                 QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat))
    try:
        dialog.first.setValue(2)
        dialog.last.setValue(3)
        dialog.colors.setCurrentIndex(1)
        dialog.refresh_preview()
        assert calls == []
        dialog.print_document()
        assert calls[0][1] == [1, 2]
        assert calls[0][2]
    finally:
        dialog.refresh_timer.stop()
        dialog.close()
