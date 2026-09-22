from pathlib import Path
from dataclasses import replace
from threading import Event

import cv2
import numpy as np
import pytest
from PIL import Image

from homework_print.models import EditSettings, Page
from homework_print.outputs import export_pngs, unique_path
from homework_print.processing import (Cancelled, detect_quad, detect_skew, enhance, geometry,
                                       load_rgb, process, rotate_expanded, valid_quad)


def test_noop_and_original_intact():
    rgb = np.random.default_rng(4).integers(0, 256, (150, 100, 3), dtype=np.uint8)
    before = rgb.copy()
    assert np.array_equal(process(rgb, EditSettings(whitening=0, ink=0)), before)
    process(rgb, EditSettings())
    assert np.array_equal(rgb, before)


def test_whitening_preserves_color_and_thin_lines():
    rgb = np.full((800, 600, 3), (220, 210, 180), np.uint8)
    rgb[:, 150:151] = (50, 90, 60)
    rgb[200:202, 80:520] = (160, 30, 20)
    out = enhance(rgb, 75, 15, False)
    assert np.min(out[30:100, 30:100]) >= 250
    assert np.max(out[250:650, 150].mean(axis=0)) < 140
    red = out[200, 250].astype(int)
    assert red[0] > red[1] + 70
    gray = enhance(rgb, 75, 15, True)
    assert np.array_equal(gray[:, :, 0], gray[:, :, 1])
    assert np.array_equal(gray[:, :, 1], gray[:, :, 2])


def test_rotation_and_crop_order():
    rgb = np.full((100, 200, 3), 255, np.uint8)
    rgb[:30, :30] = (200, 0, 0)
    out = geometry(rgb, EditSettings(rotation=1, crop=(.5, 0, 1, .5)))
    assert out.shape == (100, 50, 3)
    assert (out[:30, -30:] == (200, 0, 0)).all()


def test_invalid_geometry():
    assert not valid_quad(np.array([[0, 0], [1, 1], [1, 0], [0, 1]], np.float32))
    with pytest.raises(ValueError):
        geometry(np.zeros((100, 100, 3), np.uint8), EditSettings(crop=(.5, .5, .4, .8)))


def test_document_detection_avoids_internal_grid():
    image = np.full((800, 1000, 3), 240, np.uint8)
    cv2.rectangle(image, (80, 70), (920, 730), (20, 60, 40), 2)
    assert detect_quad(image) is None
    image[:] = 40
    cv2.fillConvexPoly(image, np.array([[100, 60], [920, 110], [900, 720], [70, 740]]), (240, 230, 210))
    quad = detect_quad(image)
    assert quad is not None
    assert np.max(np.abs(np.array(quad) - np.array([[.1, .075], [.92, .1375], [.9, .9], [.07, .925]]))) < .025


def test_cropped_off_paper_requires_manual_review():
    image = np.full((800, 1000, 3), 40, np.uint8)
    cv2.fillConvexPoly(image, np.array([[100, 60], [920, 110], [900, 800], [70, 800]]), (240, 230, 210))
    assert detect_quad(image) is None


def test_deskew_and_expansion():
    image = np.full((900, 700, 3), 255, np.uint8)
    for y in range(100, 800, 60):
        cv2.line(image, (70, y), (630, y), (0, 0, 0), 2)
    rotated = rotate_expanded(image, 2)
    assert rotated.shape[0] >= image.shape[0] and rotated.shape[1] >= image.shape[1]
    assert abs(detect_skew(rotated) + 2) < .3


def test_exif_alpha_and_unicode(tmp_path):
    p = tmp_path / "中文旋转.jpg"
    image = Image.new("RGB", (60, 100), "red")
    exif = Image.Exif()
    exif[274] = 6
    image.save(p, exif=exif)
    assert load_rgb(p).shape == (60, 100, 3)
    transparent = tmp_path / "透明.png"
    Image.new("RGBA", (50, 50), (0, 0, 0, 0)).save(transparent)
    assert load_rgb(transparent).min() == 255
    invalid = tmp_path / "坏图片.jpg"
    invalid.write_bytes(b"not an image")
    with pytest.raises(ValueError, match="无法读取"):
        load_rgb(invalid)


def test_history_branching_and_reset():
    page = Page(Path("x.png"), "x")
    original = page.settings
    page.change(replace(original, whitening=40))
    assert page.undo() and page.settings == original
    assert page.redo() and page.settings.whitening == 40
    page.undo()
    page.change(replace(original, grayscale=True))
    assert not page.redo()
    page.reset()
    assert page.settings == EditSettings(whitening=0, ink=0)
    assert page.undo() and page.settings.grayscale


def test_cancel_and_unique_export(tmp_path):
    source = tmp_path / "老师图片.png"
    Image.new("RGB", (100, 100), (220, 200, 180)).save(source)
    snapshots = [(source, source.name, EditSettings())]
    cancel = Event()
    first = export_pngs(snapshots, tmp_path, lambda *_: None, cancel)
    second = export_pngs(snapshots, tmp_path, lambda *_: None, cancel)
    assert first[0] != second[0]
    before = set(tmp_path.iterdir())
    def cancel_after_first(progress, message):
        if progress >= 50:
            cancel.set()
    with pytest.raises(Cancelled):
        export_pngs(snapshots * 2, tmp_path, cancel_after_first, cancel)
    assert set(tmp_path.iterdir()) == before
    with pytest.raises(Cancelled):
        process(load_rgb(source), EditSettings(), cancel=cancel)
