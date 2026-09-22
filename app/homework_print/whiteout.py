from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QKeySequence, QPen, QPolygonF, QShortcut
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHBoxLayout, QLabel,
                              QPushButton, QVBoxLayout)

from .processing import apply_whiteouts, whiteout_from_rect, whiteout_polygons
from .widgets import ImageView


class WhiteoutView(ImageView):
    state_changed = Signal()
    notice = Signal(str)

    def __init__(self, image, source_size, settings):
        super().__init__("whiteout")
        self.base_image = image
        self.source_size = source_size
        self.settings = settings
        self.regions = settings.whiteouts
        self.undo_stack = []
        self.redo_stack = []
        self.selected = -1
        self.start = self.end = self.press_position = self.pan_position = None
        self.polygons = []
        self.refresh()

    def refresh(self):
        settings = replace(self.settings, whiteouts=self.regions)
        self.polygons = whiteout_polygons(self.source_size, settings)
        self.set_image(apply_whiteouts(self.base_image, self.source_size, settings), fit=False)
        self.viewport().update()
        self.state_changed.emit()

    def change(self, regions, selected=-1):
        regions = tuple(regions)
        if regions == self.regions:
            return
        self.undo_stack.append(self.regions)
        self.undo_stack = self.undo_stack[-50:]
        self.redo_stack.clear()
        self.regions, self.selected = regions, selected
        self.refresh()

    def add_rect(self, rect):
        try:
            region = whiteout_from_rect(rect, self.source_size, self.settings)
            # Validate projection before committing to the local undo history.
            whiteout_polygons(self.source_size, replace(self.settings, whiteouts=(region,)))
        except ValueError as exc:
            self.notice.emit(str(exc))
            return
        self.change(self.regions + (region,), len(self.regions))

    def delete_selected(self):
        if 0 <= self.selected < len(self.regions):
            self.change(self.regions[:self.selected] + self.regions[self.selected + 1:])

    def clear_regions(self):
        self.change(())

    def undo(self):
        if self.undo_stack:
            self.redo_stack.append(self.regions)
            self.regions = self.undo_stack.pop()
            self.selected = -1
            self.refresh()

    def redo(self):
        if self.redo_stack:
            self.undo_stack.append(self.regions)
            self.regions = self.redo_stack.pop()
            self.selected = -1
            self.refresh()

    def image_position(self, event):
        point = self.mapToScene(event.position().toPoint())
        return QPointF(min(max(point.x(), 0), self.image_width - 1),
                       min(max(point.y(), 0), self.image_height - 1))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton:
            self.pan_position = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            if self.sceneRect().contains(self.mapToScene(event.position().toPoint())):
                self.start = self.end = self.image_position(event)
                self.press_position = event.position()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.pan_position is not None:
            delta = event.position() - self.pan_position
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - round(delta.x()))
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - round(delta.y()))
            self.pan_position = event.position()
        elif self.start is not None:
            self.end = self.image_position(event)
            self.viewport().update()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton:
            self.pan_position = None
            self.unsetCursor()
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self.start is not None:
            self.end = self.image_position(event)
            rect = QRectF(self.start, self.end).normalized()
            moved = (event.position() - self.press_position).manhattanLength()
            point = self.end
            self.start = self.end = self.press_position = None
            if moved >= 5 and rect.width() >= 2 and rect.height() >= 2:
                self.add_rect((rect.left(), rect.top(), rect.right(), rect.bottom()))
            else:
                self.selected = -1
                for index in reversed(range(len(self.polygons))):
                    polygon = QPolygonF([QPointF(float(x), float(y)) for x, y in self.polygons[index]])
                    if polygon.containsPoint(point, Qt.FillRule.OddEvenFill):
                        self.selected = index
                        break
                self.state_changed.emit()
            self.viewport().update()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def drawForeground(self, painter, rect):
        painter.save()
        painter.setClipRect(self.sceneRect())
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for index, points in enumerate(self.polygons):
            pen = QPen(QColor("#087f72" if index == self.selected else "#718994"),
                       2 if index == self.selected else 1)
            pen.setCosmetic(True)
            pen.setStyle(Qt.PenStyle.SolidLine if index == self.selected else Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.drawPolygon(QPolygonF([QPointF(float(x), float(y)) for x, y in points]))
        if self.start is not None and self.end is not None:
            pen = QPen(QColor("#087f72"), 2)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.setBrush(QColor("white"))
            painter.drawRect(QRectF(self.start, self.end).normalized())
        painter.restore()


class WhiteoutDialog(QDialog):
    def __init__(self, image, source_size, settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("遮挡答案 · 拖出矩形盖成白色")
        self.resize(1060, 800)
        layout = QVBoxLayout(self)
        hint = QLabel("按住左键框住答案，可连续添加。单击遮挡后按 Delete 删除；修改范围请删除后重画。")
        hint.setWordWrap(True)
        hint.setObjectName("hint")
        layout.addWidget(hint)
        self.view = WhiteoutView(image, source_size, settings)
        toolbar = QHBoxLayout()
        self.fit_button = QPushButton("适合窗口")
        self.undo_button = QPushButton("撤销")
        self.redo_button = QPushButton("重做")
        self.delete_button = QPushButton("删除选中")
        self.clear_button = QPushButton("清空遮挡")
        for button, callback in ((self.fit_button, self.view.fit_image), (self.undo_button, self.view.undo),
                                 (self.redo_button, self.view.redo), (self.delete_button, self.view.delete_selected),
                                 (self.clear_button, self.view.clear_regions)):
            button.setAutoDefault(False)
            button.clicked.connect(callback)
            toolbar.addWidget(button)
        toolbar.addStretch()
        self.count = QLabel()
        toolbar.addWidget(self.count)
        layout.addLayout(toolbar)
        layout.addWidget(self.view, 1)
        self.hint = QLabel("框内文字和格线都会遮白。滚轮缩放，中键拖动画面；边框不会打印。")
        self.hint.setWordWrap(True)
        self.hint.setObjectName("hint")
        layout.addWidget(self.hint)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.apply_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.apply_button.setText("应用")
        self.apply_button.setObjectName("primary")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.view.state_changed.connect(self.update_controls)
        self.view.notice.connect(self.hint.setText)
        for key, callback in (("Delete", self.view.delete_selected), ("Ctrl+Z", self.view.undo),
                              ("Ctrl+Y", self.view.redo), ("Ctrl+Shift+Z", self.view.redo)):
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.activated.connect(callback)
        self.update_controls()

    def update_controls(self):
        self.undo_button.setEnabled(bool(self.view.undo_stack))
        self.redo_button.setEnabled(bool(self.view.redo_stack))
        self.delete_button.setEnabled(self.view.selected >= 0)
        self.clear_button.setEnabled(bool(self.view.regions))
        hidden = sum(len(polygon) == 0 for polygon in self.view.polygons)
        self.count.setText(f"共 {len(self.view.regions)} 处" + (f" · {hidden} 处在当前画面外" if hidden else ""))

    def selection(self):
        return self.view.regions
