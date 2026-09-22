from __future__ import annotations

import os
from pathlib import Path
from threading import Event

import numpy as np
from PIL import Image
from PySide6.QtGui import QImage

from .processing import checkpoint, load_rgb, process


def to_qimage(rgb: np.ndarray) -> QImage:
    rgb = np.ascontiguousarray(rgb)
    h, w = rgb.shape[:2]
    return QImage(rgb.data, w, h, rgb.strides[0], QImage.Format.Format_RGB888).copy()


def unique_path(directory: Path, stem: str, suffix: str) -> Path:
    target = directory / f"{stem}{suffix}"
    number = 2
    while target.exists():
        target = directory / f"{stem} ({number}){suffix}"
        number += 1
    return target


def save_png(rgb: np.ndarray, target: Path):
    # Never overwrite another export, even if another application creates it meanwhile.
    with target.open("xb") as file:
        Image.fromarray(rgb).save(file, format="PNG", dpi=(300, 300))


def prepare_pages(snapshots, directory: Path, progress, cancel: Event):
    """Full-resolution print/PDF preparation, on worker; each page is stored on disk."""
    prepared = []
    directory.mkdir(parents=True, exist_ok=True)
    for index, (source, title, settings) in enumerate(snapshots):
        checkpoint(cancel)
        progress(round(index / len(snapshots) * 100), f"正在生成高清页面 {index + 1}/{len(snapshots)}")
        rgb = process(load_rgb(source), settings, cancel=cancel)
        checkpoint(cancel)
        path = directory / f"page-{index:04d}.png"
        Image.fromarray(rgb).save(path, format="PNG")
        prepared.append((path, rgb.shape[1], rgb.shape[0], title))
    progress(100, "高清页面已就绪")
    return prepared


def export_pngs(snapshots, directory: Path, progress, cancel: Event):
    directory.mkdir(parents=True, exist_ok=True)
    saved = []
    # Only this batch's newly-created files are rolled back on cancellation/error.
    try:
        for index, (source, title, settings) in enumerate(snapshots):
            checkpoint(cancel)
            progress(round(index / len(snapshots) * 100), f"正在保存图片 {index + 1}/{len(snapshots)}")
            rgb = process(load_rgb(source), settings, cancel=cancel)
            checkpoint(cancel)
            target = unique_path(directory, Path(title).stem + "_已处理", ".png")
            # Reserve a new file exclusively before writing, and track it immediately.
            with target.open("xb") as file:
                saved.append(target)
                Image.fromarray(rgb).save(file, format="PNG", dpi=(300, 300))
        checkpoint(cancel)
    except Exception:
        for path in saved:
            path.unlink(missing_ok=True)
        raise
    return saved
