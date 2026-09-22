from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from uuid import uuid4

import numpy as np


@dataclass(frozen=True)
class EditSettings:
    # Quad uses EXIF-corrected source coordinates, normalized to [0, 1].
    quad: tuple[tuple[float, float], ...] | None = None
    rotation: int = 0
    deskew: float = 0.0
    # Crop is relative to the image AFTER perspective, rotation and deskew.
    crop: tuple[float, float, float, float] | None = None
    whitening: int = 75
    ink: int = 15
    grayscale: bool = False


@dataclass
class Page:
    source: Path
    title: str
    id: str = field(default_factory=lambda: uuid4().hex)
    settings: EditSettings = field(default_factory=EditSettings)
    undo_stack: list[EditSettings] = field(default_factory=list)
    redo_stack: list[EditSettings] = field(default_factory=list)
    original_preview: np.ndarray | None = None
    preview: np.ndarray | None = None
    size: tuple[int, int] = (0, 0)
    note: str = "等待处理"
    error: str = ""
    revision: int = 0
    preview_revision: int = -1

    def change(self, settings: EditSettings) -> bool:
        if settings == self.settings:
            return False
        self.undo_stack.append(self.settings)
        self.undo_stack = self.undo_stack[-50:]
        self.redo_stack.clear()
        self.settings = settings
        self.revision += 1
        return True

    def undo(self) -> bool:
        if not self.undo_stack:
            return False
        self.redo_stack.append(self.settings)
        self.settings = self.undo_stack.pop()
        self.revision += 1
        return True

    def redo(self) -> bool:
        if not self.redo_stack:
            return False
        self.undo_stack.append(self.settings)
        self.settings = self.redo_stack.pop()
        self.revision += 1
        return True

    def reset(self) -> bool:
        return self.change(EditSettings(whitening=0, ink=0))

    def rotate(self, quarters: int) -> bool:
        return self.change(replace(self.settings, rotation=(self.settings.rotation + quarters) % 4, crop=None))


@dataclass(frozen=True)
class PrintOptions:
    orientation: str = "auto"
    margin_mm: float = 5.0
    grayscale: bool = False
