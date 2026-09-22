from dataclasses import replace
from hashlib import sha256
from threading import Event

import cv2
import numpy as np
import pytest
from PIL import Image
from pypdf import PdfReader
from PySide6.QtCore import QPointF, QSettings, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog

from homework_print.models import EditSettings, PrintOptions, WhiteoutRegion
from homework_print.outputs import export_pngs, prepare_pages
from homework_print.printing import export_pdf
from homework_print.processing import (Cancelled, geometry, process, resize_preview,
                                      load_rgb, whiteout_from_rect, whiteout_polygons)
from homework_print.selftest import wait_idle
from homework_print.whiteout import WhiteoutDialog
from homework_print.window import MainWindow


PLAIN = EditSettings(whitening=0, ink=0)
QUAD = ((.05, .03), (.97, .08), (.9, .97), (.02, .88))


def sheet():
    image = np.full((400, 500, 3), 232, np.uint8)
    image[90:130, 120:210] = (220, 20, 20)  # answer
    image[250:290, 340:420] = (20, 20, 220)  # question outside the mask
    return image


def red(image):
    return (image[:, :, 0] > 160) & (image[:, :, 1] < 80)


@pytest.mark.parametrize("gray", [False, True])
def test_multiple_overlap_edges_solid_white_and_unchanged_source(gray):
    source = sheet()
    before = source.copy()
    regions = tuple(whiteout_from_rect(rect, (500, 400), PLAIN)
                    for rect in ((100, 70, 180, 150), (160, 70, 230, 150), (0, 0, 30, 30)))
    settings = replace(PLAIN, whitening=85, ink=30, grayscale=gray, whiteouts=regions)
    result = process(source, settings)
    baseline = process(source, replace(settings, whiteouts=()))
    assert np.all(result[70:151, 100:231] == 255)
    assert np.all(result[:31, :31] == 255)
    assert np.array_equal(result[200:, :], baseline[200:, :])
    assert np.array_equal(source, before)


@pytest.mark.parametrize("changes", [
    {"rotation": 1}, {"rotation": 2}, {"rotation": 3},
    {"deskew": 7}, {"deskew": -6.5}, {"quad": QUAD},
    {"quad": QUAD, "rotation": 1, "deskew": 4, "crop": (.02, .03, .98, .97)},
])
def test_mask_follows_answer_through_geometry(changes):
    image = sheet()
    region = whiteout_from_rect((100, 70, 230, 150), (500, 400), PLAIN)
    settings = replace(PLAIN, **changes)
    baseline = process(image, settings)
    result = process(image, replace(settings, whiteouts=(region,)))
    assert baseline.shape == result.shape
    assert red(baseline).sum() > 100
    assert red(result).sum() == 0
    assert ((result[:, :, 2] > 160) & (result[:, :, 0] < 80)).sum() > 100


def test_rect_drawn_after_geometry_survives_later_changes_and_crop_hiding():
    image = sheet()
    current = replace(PLAIN, quad=QUAD, rotation=1, deskew=5, crop=(.01, .02, .99, .98))
    y, x = np.where(red(process(image, current)))
    region = whiteout_from_rect((x.min() - 6, y.min() - 6, x.max() + 6, y.max() + 6), (500, 400), current)
    for settings in (PLAIN, current, replace(PLAIN, rotation=3, deskew=-4)):
        assert not red(process(image, replace(settings, whiteouts=(region,)))).any()
    hidden = replace(PLAIN, crop=(.6, .1, 1, 1), whiteouts=(region,))
    assert len(whiteout_polygons((500, 400), hidden)[0]) == 0
    assert np.array_equal(process(image, hidden), process(image, replace(hidden, whiteouts=())))
    assert not red(process(image, replace(hidden, crop=None))).any()
    another_paper = replace(PLAIN, quad=((.55, .05), (.98, .10), (.95, .95), (.5, .9)), whiteouts=(region,))
    assert np.array_equal(process(image, another_paper), process(image, replace(another_paper, whiteouts=())))


def test_whiteout_uses_exif_corrected_coordinates(tmp_path):
    path = tmp_path / "带方向的试题.jpg"
    image = Image.fromarray(sheet())
    exif = Image.Exif()
    exif[274] = 6
    image.save(path, quality=98, exif=exif)
    digest = sha256(path.read_bytes()).hexdigest()
    source = load_rgb(path)
    assert source.shape[:2] == (500, 400)
    y, x = np.where(red(source))
    region = whiteout_from_rect((x.min() - 4, y.min() - 4, x.max() + 4, y.max() + 4), (400, 500), PLAIN)
    assert not red(process(source, replace(PLAIN, whiteouts=(region,), rotation=1))).any()
    assert sha256(path.read_bytes()).hexdigest() == digest


def test_preview_and_high_resolution_cover_same_area():
    source = np.full((2000, 2500, 3), 90, np.uint8)
    small = resize_preview(source, 1000)
    settings = replace(PLAIN, quad=QUAD, rotation=1, deskew=4, crop=(.03, .04, .98, .97))
    rendered = geometry(small, settings)
    h, w = rendered.shape[:2]
    region = whiteout_from_rect((w * .25, h * .2, w * .5, h * .45), (1000, 800), settings)
    settings = replace(settings, whiteouts=(region,))
    preview = process(small, settings)
    full = process(source, settings)
    scaled = cv2.resize(full, (w, h), interpolation=cv2.INTER_AREA)
    # Compare the interior mask away from the rotation's white padding.
    for result in (preview, scaled):
        assert np.all(result[round(h * .25):round(h * .4), round(w * .3):round(w * .45)] == 255)
    roi = np.s_[round(h * .1):round(h * .6), round(w * .1):round(w * .7)]
    def bounds(result):
        y, x = np.where(np.all(result[roi] > 245, axis=2))
        return np.array((x.min(), y.min(), x.max(), y.max()))
    assert np.max(np.abs(bounds(preview) - bounds(scaled))) <= 2


def test_invalid_and_cancelled_whiteouts():
    with pytest.raises(ValueError):
        whiteout_from_rect((10, 10, 11, 20), (500, 400), PLAIN)
    with pytest.raises(ValueError):
        process(sheet(), replace(PLAIN, whiteouts=(WhiteoutRegion(((float('nan'), 0),) * 4),)))
    event = Event()
    event.set()
    with pytest.raises(Cancelled):
        process(sheet(), replace(PLAIN, whiteouts=(whiteout_from_rect((0, 0, 50, 50), (500, 400), PLAIN),)), cancel=event)


def drag(view, a, b):
    a, b = view.mapFromScene(QPointF(*a)), view.mapFromScene(QPointF(*b))
    QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=a)
    QTest.mouseMove(view.viewport(), b, 20)
    QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=b)
    QApplication.processEvents()


def test_mouse_multi_select_delete_history_zoom_and_edges(qt_app):
    dialog = WhiteoutDialog(sheet(), (500, 400), PLAIN)
    dialog.show()
    qt_app.processEvents()
    view = dialog.view
    try:
        QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=view.mapFromScene(QPointF(70, 50)))
        drag(view, (70, 50), (71, 51))
        assert not dialog.selection()
        drag(view, (100, 70), (230, 150))
        view.zoom(1.3)
        drag(view, (200, 120), (280, 170))
        assert len(dialog.selection()) == 2
        QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=view.mapFromScene(QPointF(110, 80)))
        assert view.selected == 0
        QTest.mouseClick(dialog.delete_button, Qt.MouseButton.LeftButton)
        assert len(dialog.selection()) == 1
        QTest.mouseClick(dialog.undo_button, Qt.MouseButton.LeftButton)
        assert len(dialog.selection()) == 2
        QTest.mouseClick(dialog.redo_button, Qt.MouseButton.LeftButton)
        assert len(dialog.selection()) == 1
        QTest.mouseClick(dialog.clear_button, Qt.MouseButton.LeftButton)
        assert not dialog.selection()
        view.undo()
        view.fit_image()
        qt_app.processEvents()
        drag(view, (0, 0), (35, 40))
        assert len(dialog.selection()) == 2
        assert np.all(view.scene().items()[0].pixmap().toImage().pixelColor(0, 0).getRgb()[:3] == np.array([255] * 3))
        view.setFocus()
        QTest.keyClick(view, Qt.Key.Key_Delete)
        qt_app.processEvents()
        assert len(dialog.selection()) == 1
    finally:
        dialog.close()


def test_main_dialog_transaction_cancel_reopen_and_page_isolation(qt_app, tmp_path, monkeypatch):
    import homework_print.window as module
    paths = []
    for i in range(2):
        path = tmp_path / f"试题{i}.png"
        Image.fromarray(sheet()).save(path)
        paths.append(path)
    window = MainWindow(QSettings(str(tmp_path / 'settings.ini'), QSettings.Format.IniFormat))
    try:
        window.import_files(paths)
        wait_idle(window)
        before = window.current_page().settings
        def cancel(dialog):
            dialog.view.add_rect((80, 60, 250, 170))
            return QDialog.DialogCode.Rejected
        monkeypatch.setattr(module.WhiteoutDialog, 'exec', cancel)
        window.edit_whiteouts()
        wait_idle(window)
        assert window.current_page().settings == before
        def apply(dialog):
            assert not dialog.selection()
            dialog.view.add_rect((80, 60, 250, 170))
            dialog.view.add_rect((20, 300, 60, 350))
            return QDialog.DialogCode.Accepted
        monkeypatch.setattr(module.WhiteoutDialog, 'exec', apply)
        window.edit_whiteouts()
        wait_idle(window)
        covered = window.current_page().settings
        assert len(covered.whiteouts) == 2
        window.undo()
        wait_idle(window)
        assert window.current_page().settings == before
        window.redo()
        wait_idle(window)
        assert window.current_page().settings == covered
        def reopen(dialog):
            assert dialog.selection() == covered.whiteouts
            dialog.view.clear_regions()
            return QDialog.DialogCode.Rejected
        monkeypatch.setattr(module.WhiteoutDialog, 'exec', reopen)
        window.edit_whiteouts()
        wait_idle(window)
        assert window.current_page().settings == covered
        window.auto_current()
        wait_idle(window)
        assert window.current_page().settings.whiteouts == covered.whiteouts
        window.reset_current()
        wait_idle(window)
        assert not window.current_page().settings.whiteouts
        window.undo()
        wait_idle(window)
        assert window.current_page().settings.whiteouts == covered.whiteouts
        window.list.setCurrentRow(1)
        wait_idle(window)
        assert not window.current_page().settings.whiteouts
    finally:
        wait_idle(window)
        window.close()


@pytest.mark.parametrize("gray", [False, True])
def test_png_print_preparation_pdf_flattened_pixels_and_source_integrity(qt_app, tmp_path, gray):
    source = tmp_path / "试题原图.png"
    Image.fromarray(sheet()).save(source)
    checksum = sha256(source.read_bytes()).hexdigest()
    region = whiteout_from_rect((100, 70, 230, 150), (500, 400), PLAIN)
    settings = replace(PLAIN, grayscale=gray, whiteouts=(region,))
    snapshots = [(source, source.name, settings)]
    exported = export_pngs(snapshots, tmp_path, lambda *_: None, Event())
    pages = prepare_pages(snapshots, tmp_path / 'print', lambda *_: None, Event())
    result = np.asarray(Image.open(exported[0]))
    assert np.all(result[70:151, 100:231] == 255)
    assert np.array_equal(result, np.asarray(Image.open(pages[0][0])))
    pdf = tmp_path / "练习题.pdf"
    export_pdf(pdf, pages, PrintOptions())
    reader = PdfReader(pdf)
    assert len(reader.pages) == 1 and len(reader.pages[0].images) == 1
    embedded = np.asarray(reader.pages[0].images[0].image.convert('RGB'))
    assert np.all(embedded[75:145, 105:225] == 255)
    assert not red(embedded).any()
    assert sha256(source.read_bytes()).hexdigest() == checksum
