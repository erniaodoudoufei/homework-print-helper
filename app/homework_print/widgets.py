from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QDialogButtonBox,
                              QGraphicsScene, QGraphicsView, QHBoxLayout, QLabel,
                              QListWidget, QMessageBox, QPushButton, QVBoxLayout)

from .outputs import to_qimage
from .processing import valid_quad


class PageList(QListWidget):
    files_dropped = Signal(list)

    def __init__(self):
        super().__init__()
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            self.files_dropped.emit([url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()])
            event.acceptProposedAction()
        else:
            super().dropEvent(event)


class ImageView(QGraphicsView):
    zoom_changed = Signal(str)

    def __init__(self, mode: str = "view"):
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        self.setBackgroundBrush(QColor("#e7ecef"))
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag if mode == "view" else QGraphicsView.DragMode.NoDrag)
        self.mode = mode
        self.image_width = self.image_height = 0
        self.fit_mode = True
        self.quad = [QPointF(.02, .02), QPointF(.98, .02), QPointF(.98, .98), QPointF(.02, .98)]
        self.crop = QRectF(0, 0, 1, 1)
        self.active_handle = -1
        self.crop_start = None
        self.setMinimumSize(180, 180)

    def set_image(self, image, fit=True):
        transform = self.transform()
        center = self.mapToScene(self.viewport().rect().center())
        self.scene().clear()
        if image is None:
            self.image_width = self.image_height = 0
            return
        qimage = to_qimage(image) if isinstance(image, np.ndarray) else image
        self.image_width, self.image_height = qimage.width(), qimage.height()
        item = self.scene().addPixmap(QPixmap.fromImage(qimage))
        # QGraphicsPixmapItem defaults to fast sampling and overrides the view's
        # render hint; smooth sampling keeps fine grid lines visible when zoomed out.
        item.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
        self.setSceneRect(QRectF(0, 0, self.image_width, self.image_height))
        if fit or self.fit_mode:
            self.fit_image()
        else:
            self.setTransform(transform)
            self.centerOn(center)

    def fit_image(self):
        self.fit_mode = True
        if self.image_width:
            self.fitInView(self.sceneRect().adjusted(-18, -18, 18, 18), Qt.AspectRatioMode.KeepAspectRatio)
            self.zoom_changed.emit(f"{self.transform().m11() * 100:.0f}%")

    def actual_size(self):
        self.fit_mode = False
        self.resetTransform()
        self.zoom_changed.emit("100%")

    def zoom(self, factor):
        scale = self.transform().m11() * factor
        if .02 <= scale <= 12:
            self.fit_mode = False
            self.scale(factor, factor)
            self.zoom_changed.emit(f"{scale * 100:.0f}%")

    def wheelEvent(self, event):
        self.zoom(1.18 if event.angleDelta().y() > 0 else 1 / 1.18)
        event.accept()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.fit_mode:
            self.fit_image()

    def normalized_position(self, event):
        point = self.mapToScene(event.position().toPoint())
        return QPointF(np.clip(point.x() / max(1, self.image_width - 1), 0, 1),
                       np.clip(point.y() / max(1, self.image_height - 1), 0, 1))

    def scaled_point(self, point):
        return QPointF(point.x() * (self.image_width - 1), point.y() * (self.image_height - 1))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.image_width:
            position = self.normalized_position(event)
            if self.mode == "quad":
                distances = [np.hypot(self.scaled_point(p).x() - self.scaled_point(position).x(),
                                      self.scaled_point(p).y() - self.scaled_point(position).y()) for p in self.quad]
                nearest = int(np.argmin(distances))
                if distances[nearest] < 24 / max(.01, self.transform().m11()):
                    self.active_handle = nearest
                    event.accept()
                    return
            elif self.mode == "crop":
                self.crop_start = position
                self.crop = QRectF(position, position)
                self.viewport().update()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.active_handle >= 0:
            self.quad[self.active_handle] = self.normalized_position(event)
            self.viewport().update()
            event.accept()
        elif self.crop_start is not None:
            self.crop = QRectF(self.crop_start, self.normalized_position(event)).normalized()
            self.viewport().update()
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self.active_handle = -1
        self.crop_start = None
        super().mouseReleaseEvent(event)

    def drawForeground(self, painter, rect):
        if not self.image_width or self.mode == "view":
            return
        painter.save()
        shape = QPainterPath()
        if self.mode == "quad":
            polygon = QPolygonF([self.scaled_point(p) for p in self.quad])
            shape.addPolygon(polygon)
            shape.closeSubpath()
        else:
            shape.addRect(QRectF(self.crop.x() * self.image_width, self.crop.y() * self.image_height,
                                 self.crop.width() * self.image_width, self.crop.height() * self.image_height))
        outer = QPainterPath()
        outer.addRect(self.sceneRect())
        painter.fillPath(outer.subtracted(shape), QColor(15, 23, 42, 125))
        pen = QPen(QColor("#0db89b"), 2)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(shape)
        if self.mode == "quad":
            radius = 8 / max(.01, self.transform().m11())
            painter.setBrush(QColor("white"))
            for point in self.quad:
                painter.drawEllipse(self.scaled_point(point), radius, radius)
        painter.restore()


class GeometryDialog(QDialog):
    def __init__(self, image, mode: str, initial=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("四角拉正" if mode == "quad" else "裁切图片")
        self.resize(960, 760)
        self.mode = mode
        layout = QVBoxLayout(self)
        label = QLabel("把四个圆点拖到纸张四个角上，再点击应用。滚轮可放大查看。" if mode == "quad"
                       else "按住鼠标左键，拖出要保留的矩形范围。滚轮可放大查看。")
        label.setObjectName("hint")
        layout.addWidget(label)
        self.view = ImageView(mode)
        self.view.set_image(image)
        if initial is not None:
            if mode == "quad":
                self.view.quad = [QPointF(x, y) for x, y in initial]
            else:
                l, t, r, b = initial
                self.view.crop = QRectF(l, t, r - l, b - t)
        layout.addWidget(self.view, 1)
        row = QHBoxLayout()
        fit = QPushButton("适合窗口")
        fit.clicked.connect(self.view.fit_image)
        reset = QPushButton("选择完整图片")
        reset.clicked.connect(self.reset_selection)
        row.addWidget(fit)
        row.addWidget(reset)
        row.addStretch()
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("应用")
        buttons.button(QDialogButtonBox.StandardButton.Ok).setObjectName("primary")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        row.addWidget(buttons)
        layout.addLayout(row)

    def reset_selection(self):
        self.view.quad = [QPointF(0, 0), QPointF(1, 0), QPointF(1, 1), QPointF(0, 1)]
        self.view.crop = QRectF(0, 0, 1, 1)
        self.view.viewport().update()

    def selection(self):
        if self.mode == "quad":
            return tuple((p.x(), p.y()) for p in self.view.quad)
        r = self.view.crop
        return r.left(), r.top(), r.right(), r.bottom()

    def accept(self):
        if self.mode == "quad":
            if not valid_quad(np.asarray(self.selection(), np.float32)):
                QMessageBox.information(self, "请调整四个角", "四个角不能交叉，也不能挤在一起。请沿纸张边缘顺序调整。")
                return
        elif self.view.crop.width() < .02 or self.view.crop.height() < .02:
            QMessageBox.information(self, "请扩大范围", "保留的区域太小，请重新拖出一个更大的矩形。")
            return
        super().accept()
