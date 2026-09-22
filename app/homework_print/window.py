from __future__ import annotations

import shutil
import tempfile
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from PIL import Image
from PySide6.QtCore import QSettings, QSize, QStandardPaths, Qt, QThreadPool, QTimer
from PySide6.QtGui import QIcon, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (QApplication, QComboBox, QDialog, QDoubleSpinBox,
                              QFileDialog, QHBoxLayout, QLabel, QListWidgetItem,
                              QMainWindow, QMessageBox, QProgressBar, QPushButton,
                              QSlider, QSplitter, QStackedWidget, QVBoxLayout, QWidget)

from .jobs import Job
from . import __version__
from .models import EditSettings, Page
from .outputs import export_pngs, prepare_pages, to_qimage
from .print_dialog import PrintDialog
from .processing import checkpoint, geometry, load_rgb, process, resize_preview, suggest_settings
from .style import STYLE
from .widgets import GeometryDialog, ImageView, PageList
from .whiteout import WhiteoutDialog


class MainWindow(QMainWindow):
    def __init__(self, settings: QSettings | None = None):
        super().__init__()
        self.setWindowTitle(f"作业图片打印助手 {__version__}")
        self.resize(1380, 880)
        self.setMinimumSize(1100, 700)
        self.setAcceptDrops(True)
        self.setStyleSheet(STYLE)
        self.settings = settings or QSettings("HomeworkPrint", "作业图片打印助手")
        self.pages: dict[str, Page] = {}
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)
        self.job: Job | None = None
        self.job_kind = ""
        self.loading_controls = False
        self.pending_preview = False
        self.last_shown_id = ""
        self._closing = False
        self._temp = tempfile.TemporaryDirectory(prefix="HomeworkPrint-")
        self.temp_path = Path(self._temp.name)
        self.preview_timer = QTimer(self)
        self.preview_timer.setSingleShot(True)
        self.preview_timer.setInterval(220)
        self.preview_timer.timeout.connect(self.request_preview)
        self.edit_timer = QTimer(self)
        self.edit_timer.setSingleShot(True)
        self.edit_timer.setInterval(250)
        self.edit_timer.timeout.connect(self.commit_controls)
        self.make_ui()
        self.make_shortcuts()
        self.update_enabled()

    def button(self, text, callback, parent_layout=None, primary=False):
        button = QPushButton(text)
        button.clicked.connect(callback)
        if primary:
            button.setObjectName("primary")
        if parent_layout is not None:
            parent_layout.addWidget(button)
        return button

    def make_ui(self):
        base = QWidget()
        self.setCentralWidget(base)
        root = QVBoxLayout(base)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        header = QWidget()
        header.setObjectName("header")
        row = QHBoxLayout(header)
        row.setContentsMargins(24, 18, 24, 18)
        brand = QVBoxLayout()
        eyebrow = QLabel("HOMEWORK PRINT  /  离线图片处理")
        eyebrow.setObjectName("eyebrow")
        brand.addWidget(eyebrow)
        title = QLabel("作业图片打印助手")
        title.setObjectName("appTitle")
        brand.addWidget(title)
        row.addLayout(brand)
        row.addStretch()
        self.add_button = self.button("＋ 添加图片", self.choose_files, row)
        self.paste_button = self.button("粘贴图片", self.paste_image, row)
        self.save_button = self.button("保存处理图片", self.save_images, row)
        self.print_button = self.button("打印 / 保存 PDF", self.open_print, row, True)
        root.addWidget(header)
        body = QHBoxLayout()
        body.setContentsMargins(0, 1, 0, 0)
        body.setSpacing(1)
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(218)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(12, 16, 12, 12)
        self.count_label = QLabel("图片  0")
        self.count_label.setObjectName("sectionTitle")
        side.addWidget(self.count_label)
        hint = QLabel("拖动调整打印顺序")
        hint.setObjectName("hint")
        side.addWidget(hint)
        self.list = PageList()
        self.list.setIconSize(QSize(70, 88))
        self.list.setSpacing(3)
        self.list.currentItemChanged.connect(self.selection_changed)
        self.list.files_dropped.connect(self.import_files)
        self.list.model().rowsMoved.connect(lambda: self.refresh_numbering())
        side.addWidget(self.list, 1)
        reorder = QHBoxLayout()
        self.up_button = self.button("上移", lambda: self.move_current(-1), reorder)
        self.down_button = self.button("下移", lambda: self.move_current(1), reorder)
        side.addLayout(reorder)
        self.remove_button = self.button("移除当前图片", self.remove_current, side)
        body.addWidget(sidebar)
        middle = QWidget()
        center = QVBoxLayout(middle)
        center.setContentsMargins(16, 14, 16, 12)
        toolbar = QHBoxLayout()
        self.compare = QComboBox()
        self.compare.addItems(["处理效果", "查看原图", "左右对比"])
        self.compare.currentIndexChanged.connect(self.show_current)
        toolbar.addWidget(self.compare)
        toolbar.addStretch()
        self.button("适合窗口", self.fit_views, toolbar)
        self.button("100%", self.actual_views, toolbar)
        self.zoom_label = QLabel("滚轮缩放")
        self.zoom_label.setObjectName("hint")
        toolbar.addWidget(self.zoom_label)
        center.addLayout(toolbar)
        self.stack = QStackedWidget()
        empty = QWidget()
        empty_box = QVBoxLayout(empty)
        empty_box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon = QLabel("▤")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet("font-size: 66px; color: #4a9e91; padding: 12px;")
        empty_box.addWidget(icon)
        label = QLabel("把老师发的图片拖到这里")
        label.setObjectName("emptyTitle")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_box.addWidget(label)
        label = QLabel("去灰底 · 拉正裁切 · 保留彩色笔迹\n\n支持 JPG、PNG，也可以按 Ctrl + V 粘贴图片")
        label.setObjectName("emptyText")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_box.addWidget(label)
        self.stack.addWidget(empty)
        self.compare_split = QSplitter(Qt.Orientation.Horizontal)
        self.original_box, self.original_view = self.view_panel("原图")
        self.result_box, self.result_view = self.view_panel("处理效果")
        self.compare_split.addWidget(self.original_box)
        self.compare_split.addWidget(self.result_box)
        self.stack.addWidget(self.compare_split)
        self.result_view.zoom_changed.connect(self.zoom_label.setText)
        center.addWidget(self.stack, 1)
        self.notice = QLabel("图片在本机处理，原文件始终保留。")
        self.notice.setWordWrap(True)
        self.notice.setObjectName("notice")
        center.addWidget(self.notice)
        body.addWidget(middle, 1)
        self.adjustments = QWidget()
        self.adjustments.setObjectName("adjustments")
        self.adjustments.setFixedWidth(256)
        adjust = QVBoxLayout(self.adjustments)
        adjust.setContentsMargins(18, 18, 18, 16)
        title = QLabel("调整图片")
        title.setObjectName("sectionTitle")
        adjust.addWidget(title)
        self.auto_button = self.button("重新自动处理", self.auto_current, adjust)
        adjust.addSpacing(16)
        label = QLabel("01  拉正与裁切")
        label.setObjectName("sectionTitle")
        adjust.addWidget(label)
        rotate = QHBoxLayout()
        self.button("左转 90°", lambda: self.rotate_current(-1), rotate)
        self.button("右转 90°", lambda: self.rotate_current(1), rotate)
        adjust.addLayout(rotate)
        self.button("四角拉正", lambda: self.edit_geometry("quad"), adjust)
        self.button("裁切范围", lambda: self.edit_geometry("crop"), adjust)
        self.whiteout_button = self.button("遮挡答案", self.edit_whiteouts, adjust)
        angle_row = QHBoxLayout()
        angle_row.addWidget(QLabel("倾斜微调"))
        self.angle = QDoubleSpinBox()
        self.angle.setRange(-15, 15)
        self.angle.setDecimals(2)
        self.angle.setSingleStep(.1)
        self.angle.setSuffix(" °")
        self.angle.setKeyboardTracking(False)
        self.angle.valueChanged.connect(self.controls_edited)
        angle_row.addWidget(self.angle)
        adjust.addLayout(angle_row)
        adjust.addSpacing(20)
        label = QLabel("02  纸面与笔迹")
        label.setObjectName("sectionTitle")
        adjust.addWidget(label)
        self.mode = QComboBox()
        self.mode.addItems(["保留彩色", "黑白"])
        self.mode.currentIndexChanged.connect(self.controls_edited)
        adjust.addWidget(self.mode)
        self.white_slider, self.white_value = self.make_slider("去灰底强度", 0, 100, 75, adjust)
        self.ink_slider, self.ink_value = self.make_slider("文字深浅", -30, 60, 15, adjust)
        tip = QLabel("细线变淡时，减小去灰底强度。\n文字过粗时，降低文字深浅。")
        tip.setWordWrap(True)
        tip.setObjectName("hint")
        adjust.addWidget(tip)
        adjust.addStretch()
        history = QHBoxLayout()
        self.undo_button = self.button("撤销", self.undo, history)
        self.redo_button = self.button("重做", self.redo, history)
        adjust.addLayout(history)
        self.reset_button = self.button("恢复原图", self.reset_current, adjust)
        body.addWidget(self.adjustments)
        root.addLayout(body, 1)
        footer = QWidget()
        bottom = QHBoxLayout(footer)
        bottom.setContentsMargins(20, 6, 20, 6)
        self.activity = QLabel("准备就绪 · 所有处理均在本机完成")
        self.activity.setObjectName("hint")
        bottom.addWidget(self.activity, 1)
        self.progress = QProgressBar()
        self.progress.setFixedWidth(170)
        self.progress.setTextVisible(False)
        self.progress.hide()
        bottom.addWidget(self.progress)
        self.cancel_button = self.button("取消处理", self.cancel_job, bottom)
        self.cancel_button.hide()
        root.addWidget(footer)

    def view_panel(self, title):
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        label = QLabel(title)
        label.setObjectName("hint")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(label)
        view = ImageView()
        layout.addWidget(view, 1)
        return box, view

    def make_slider(self, title, minimum, maximum, value, layout):
        row = QHBoxLayout()
        row.addWidget(QLabel(title))
        row.addStretch()
        value_label = QLabel(str(value))
        value_label.setObjectName("hint")
        row.addWidget(value_label)
        layout.addSpacing(12)
        layout.addLayout(row)
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(minimum, maximum)
        slider.setValue(value)
        slider.valueChanged.connect(lambda v: value_label.setText(str(v)))
        slider.valueChanged.connect(self.controls_edited)
        slider.sliderReleased.connect(self.commit_controls)
        layout.addWidget(slider)
        return slider, value_label

    def make_shortcuts(self):
        for key, callback in [("Ctrl+O", self.choose_files), ("Ctrl+V", self.paste_image),
                              ("Ctrl+Z", self.undo), ("Ctrl+Y", self.redo),
                              ("Ctrl+Shift+Z", self.redo), ("Ctrl+P", self.open_print)]:
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.activated.connect(callback)
        self.list.setToolTip("拖动排序；按 Delete 移除选中的图片")
        delete = QShortcut(QKeySequence("Delete"), self.list)
        delete.setContext(Qt.ShortcutContext.WidgetShortcut)
        delete.activated.connect(self.remove_current)

    def ordered_pages(self):
        return [self.pages[self.list.item(i).data(Qt.ItemDataRole.UserRole)] for i in range(self.list.count())]

    def current_page(self):
        item = self.list.currentItem()
        return self.pages.get(item.data(Qt.ItemDataRole.UserRole)) if item else None

    def is_blocked(self):
        return self.job is not None and self.job_kind != "preview"

    def choose_files(self):
        if self.job:
            self.activity.setText("请先等待当前处理完成，或点击取消处理。")
            return
        folder = self.settings.value("last_folder", str(Path.cwd()), str)
        paths, _ = QFileDialog.getOpenFileNames(self, "选择老师发的图片", folder, "图片 (*.jpg *.jpeg *.png)")
        if paths:
            self.settings.setValue("last_folder", str(Path(paths[0]).parent))
            self.import_files(paths)

    def import_files(self, paths):
        if self.job:
            self.activity.setText("请先等待当前处理完成，或点击取消处理。")
            return
        paths = [Path(path) for path in paths if Path(path).suffix.lower() in (".jpg", ".jpeg", ".png") and Path(path).is_file()]
        if not paths:
            self.activity.setText("请选择 JPG 或 PNG 图片文件。")
            return
        self.commit_controls()
        self.preview_timer.stop()
        def work(progress, cancel):
            loaded, errors = [], []
            for i, path in enumerate(paths):
                checkpoint(cancel)
                progress(round(i / len(paths) * 100), f"正在处理 {i + 1}/{len(paths)} · {path.name}")
                try:
                    rgb = load_rgb(path)
                    settings, note = suggest_settings(rgb, cancel)
                    original = resize_preview(rgb)
                    preview = process(original, settings, cancel=cancel)
                    loaded.append(Page(path, path.name, settings=settings, original_preview=original,
                                       preview=preview, size=(rgb.shape[1], rgb.shape[0]), note=note, preview_revision=0))
                except ValueError as exc:
                    errors.append(str(exc))
            checkpoint(cancel)
            return loaded, errors
        def completed(value):
            loaded, errors = value
            for page in loaded:
                self.pages[page.id] = page
                item = QListWidgetItem()
                item.setData(Qt.ItemDataRole.UserRole, page.id)
                item.setSizeHint(QSize(186, 108))
                self.list.addItem(item)
                self.update_thumbnail(page)
            self.refresh_numbering()
            if loaded:
                self.list.setCurrentRow(self.list.count() - len(loaded))
            self.activity.setText(f"已导入 {len(loaded)} 张图片" + (f"，{len(errors)} 张未能读取" if errors else ""))
            if errors:
                QMessageBox.warning(self, "部分图片未导入", "\n\n".join(errors[:8]))
        self.start_job("import", work, completed)

    def paste_image(self):
        if self.job:
            return
        clipboard = QApplication.clipboard()
        mime = clipboard.mimeData()
        if mime.hasImage():
            image = clipboard.image()
            if not image.isNull():
                path = self.temp_path / f"粘贴图片-{len(self.pages) + 1}-{uuid4().hex[:4]}.png"
                if image.save(str(path), "PNG"):
                    self.import_files([path])
                return
        if mime.hasUrls():
            self.import_files([u.toLocalFile() for u in mime.urls() if u.isLocalFile()])
        else:
            self.activity.setText("剪贴板里没有图片。请先复制图片，再按 Ctrl + V。")

    def selection_changed(self, current=None, previous=None):
        # A pending control edit belongs to the OLD selection.
        if previous is not None and self.edit_timer.isActive():
            old = self.pages.get(previous.data(Qt.ItemDataRole.UserRole))
            self.commit_controls(page=old)
        self.show_current()
        self.sync_controls()
        page = self.current_page()
        if page and page.preview_revision != page.revision:
            self.preview_timer.start()

    def show_current(self, *_):
        page = self.current_page()
        if page is None:
            self.stack.setCurrentIndex(0)
            self.notice.setText("图片在本机处理，原文件始终保留。")
            self.update_enabled()
            return
        self.stack.setCurrentIndex(1)
        fit = page.id != self.last_shown_id
        self.last_shown_id = page.id
        self.original_view.set_image(page.original_preview, fit)
        self.result_view.set_image(page.preview, fit)
        view_mode = self.compare.currentIndex()
        self.original_box.setVisible(view_mode in (1, 2))
        self.result_box.setVisible(view_mode in (0, 2))
        self.notice.setText(page.error or page.note)
        self.notice.setToolTip(f"{page.source}\n原始尺寸：{page.size[0]} × {page.size[1]}")
        self.update_enabled()

    def sync_controls(self):
        page = self.current_page()
        if not page:
            return
        self.loading_controls = True
        self.angle.setValue(page.settings.deskew)
        self.mode.setCurrentIndex(int(page.settings.grayscale))
        self.white_slider.setValue(page.settings.whitening)
        self.ink_slider.setValue(page.settings.ink)
        self.loading_controls = False
        self.update_enabled()

    def controls_edited(self, *_):
        if not self.loading_controls:
            self.edit_timer.start()

    def commit_controls(self, page=None):
        if self.loading_controls:
            return
        page = page or self.current_page()
        self.edit_timer.stop()
        if not page:
            return
        angle = self.angle.value()
        settings = replace(page.settings, whitening=self.white_slider.value(), ink=self.ink_slider.value(),
                           grayscale=self.mode.currentIndex() == 1, deskew=angle,
                           crop=None if angle != page.settings.deskew else page.settings.crop)
        if page.change(settings):
            page.error = ""
            self.preview_timer.start()
            self.update_enabled()

    def request_preview(self):
        page = self.current_page()
        if not page or self._closing:
            return
        if self.job:
            self.pending_preview = True
            if self.job_kind == "preview":
                self.job.cancel()
            return
        if page.preview_revision == page.revision:
            return
        identifier, revision, settings, source = page.id, page.revision, page.settings, page.original_preview
        def work(progress, cancel):
            progress(25, "正在更新处理效果…")
            return identifier, revision, process(source, settings, cancel=cancel)
        def completed(result):
            identifier, revision, rgb = result
            found = self.pages.get(identifier)
            if found is not None and revision == found.revision:
                found.preview = rgb
                found.preview_revision = revision
                found.error = ""
                self.update_thumbnail(found)
                if found is self.current_page():
                    self.show_current()
                self.activity.setText("效果已更新 · 可继续微调或打印")
        self.start_job("preview", work, completed)

    def start_job(self, kind, function, completed):
        if self.job:
            return False
        job = Job(function)
        self.job, self.job_kind = job, kind
        self.progress.setValue(0)
        self.progress.show()
        self.cancel_button.show()
        job.signals.progress.connect(self.job_progress)
        job.signals.result.connect(completed)
        job.signals.failed.connect(self.job_failed)
        job.signals.cancelled.connect(lambda: self.activity.setText("已取消处理，原文件未改动。"))
        job.signals.finished.connect(self.job_finished)
        self.update_enabled()
        self.pool.start(job)
        return True

    def job_progress(self, value, message):
        self.progress.setValue(value)
        self.activity.setText(message)

    def job_failed(self, message, details):
        self.activity.setText("处理未完成：" + message)
        if self.job_kind == "preview":
            page = self.current_page()
            if page:
                page.error = "处理未完成，请撤销或调整参数：" + message
                self.notice.setText(page.error)
        else:
            box = QMessageBox(QMessageBox.Icon.Warning, "处理未完成", message, parent=self)
            box.setDetailedText(details)
            box.exec()

    def job_finished(self):
        self.job = None
        self.job_kind = ""
        self.progress.hide()
        self.cancel_button.hide()
        self.update_enabled()
        if self._closing:
            QTimer.singleShot(0, self.close)
        elif self.pending_preview:
            self.pending_preview = False
            self.preview_timer.start()

    def cancel_job(self):
        self.pending_preview = False
        self.preview_timer.stop()
        if self.job:
            self.job.cancel()
            self.activity.setText("正在取消，请稍候…")

    def change_page(self, settings, note=None):
        page = self.current_page()
        if page and page.change(settings):
            page.error = ""
            if note:
                page.note = note
            self.sync_controls()
            self.preview_timer.start()

    def rotate_current(self, quarters):
        if self.is_blocked():
            return
        self.commit_controls()
        page = self.current_page()
        if page:
            self.change_page(replace(page.settings, rotation=(page.settings.rotation + quarters) % 4, crop=None))

    def edit_geometry(self, mode):
        if self.is_blocked():
            return
        self.commit_controls()
        page = self.current_page()
        if not page:
            return
        if mode == "quad":
            image, initial = page.original_preview, page.settings.quad
        else:
            try:
                image, initial = geometry(page.original_preview, page.settings, include_crop=False), page.settings.crop
            except ValueError as exc:
                QMessageBox.warning(self, "无法裁切", str(exc))
                return
        dialog = GeometryDialog(image, mode, initial, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            if mode == "quad":
                self.change_page(replace(page.settings, quad=dialog.selection(), deskew=0, crop=None), "已手动校正四角，可继续调整去灰底效果")
            else:
                self.change_page(replace(page.settings, crop=dialog.selection()), "已手动裁切，可撤销恢复")

    def auto_current(self):
        if self.job:
            return
        self.commit_controls()
        self.preview_timer.stop()
        page = self.current_page()
        if not page:
            return
        source = page.original_preview
        def work(progress, cancel):
            progress(30, "正在重新识别纸张…")
            settings, note = suggest_settings(source, cancel)
            return settings, note
        def completed(result):
            settings, note = result
            self.change_page(replace(settings, whiteouts=page.settings.whiteouts), note)
            self.pending_preview = True
        self.start_job("auto", work, completed)

    def edit_whiteouts(self):
        if self.job or not self.current_page():
            return
        self.commit_controls()
        self.preview_timer.stop()
        page = self.current_page()
        settings, source = page.settings, page.original_preview
        def work(progress, cancel):
            progress(25, "正在准备遮挡答案画面…")
            return process(source, replace(settings, whiteouts=()), cancel=cancel)
        def completed(image):
            if self._closing:
                return
            dialog = WhiteoutDialog(image, (source.shape[1], source.shape[0]), settings, self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                regions = dialog.selection()
                self.change_page(replace(settings, whiteouts=regions),
                                 f"已遮挡 {len(regions)} 处答案；可继续调整或打印" if regions else "已清空遮挡")
            dialog.deleteLater()
            self.preview_timer.start()
        self.start_job("whiteout", work, completed)

    def undo(self):
        if self.is_blocked():
            return
        self.commit_controls()
        page = self.current_page()
        if page and page.undo():
            page.error = ""
            self.sync_controls()
            self.preview_timer.start()

    def redo(self):
        if self.is_blocked():
            return
        self.commit_controls()
        page = self.current_page()
        if page and page.redo():
            page.error = ""
            self.sync_controls()
            self.preview_timer.start()

    def reset_current(self):
        if self.is_blocked():
            return
        self.commit_controls()
        self.change_page(EditSettings(whitening=0, ink=0), "已恢复原图；可点击「重新自动处理」")

    def remove_current(self):
        if self.is_blocked():
            return
        self.edit_timer.stop()
        row = self.list.currentRow()
        if row >= 0:
            item = self.list.takeItem(row)
            self.pages.pop(item.data(Qt.ItemDataRole.UserRole), None)
            self.refresh_numbering()
            self.show_current()

    def move_current(self, delta):
        if self.is_blocked():
            return
        self.commit_controls()
        row = self.list.currentRow()
        destination = row + delta
        if 0 <= destination < self.list.count():
            self.list.blockSignals(True)
            item = self.list.takeItem(row)
            self.list.insertItem(destination, item)
            self.list.setCurrentRow(destination)
            self.list.blockSignals(False)
            self.refresh_numbering()

    def refresh_numbering(self):
        for i, page in enumerate(self.ordered_pages()):
            item = self.list.item(i)
            short = page.title if len(page.title) < 15 else page.title[:11] + "…"
            item.setText(f"{i + 1:02d}  {short}\n{page.size[0]} × {page.size[1]}")
            item.setToolTip(page.title)
        self.count_label.setText(f"图片  {self.list.count()}")
        self.update_enabled()

    def update_thumbnail(self, page):
        pixmap = QPixmap.fromImage(to_qimage(page.preview))
        icon = QIcon(pixmap.scaled(70, 88, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        for i in range(self.list.count()):
            item = self.list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == page.id:
                item.setIcon(icon)
                break

    def update_enabled(self):
        page = self.current_page()
        blocked = self.is_blocked()
        self.adjustments.setEnabled(page is not None and not blocked)
        self.list.setEnabled(not blocked)
        self.add_button.setEnabled(self.job is None)
        self.paste_button.setEnabled(self.job is None)
        for button in (self.save_button, self.print_button):
            button.setEnabled(bool(self.pages) and self.job is None)
        for button in (self.remove_button, self.up_button, self.down_button):
            button.setEnabled(page is not None and not blocked)
        self.undo_button.setEnabled(page is not None and bool(page.undo_stack) and not blocked)
        self.redo_button.setEnabled(page is not None and bool(page.redo_stack) and not blocked)
        self.auto_button.setEnabled(page is not None and self.job is None)
        self.whiteout_button.setEnabled(page is not None and self.job is None)
        self.whiteout_button.setText(f"遮挡答案（{len(page.settings.whiteouts)}）" if page and page.settings.whiteouts else "遮挡答案")

    def fit_views(self):
        self.original_view.fit_image()
        self.result_view.fit_image()

    def actual_views(self):
        self.original_view.actual_size()
        self.result_view.actual_size()

    def default_output_directory(self):
        pages = self.ordered_pages()
        if pages and pages[0].source.parent != self.temp_path:
            return pages[0].source.parent / "已处理"
        return Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.PicturesLocation)) / "作业图片打印助手"

    def writable_initial_directory(self):
        directory = self.default_output_directory()
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError:
            directory = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.PicturesLocation))
        return directory

    def snapshots(self):
        return [(page.source, page.title, page.settings) for page in self.ordered_pages()]

    def save_images(self):
        if self.job or not self.pages:
            return
        self.commit_controls()
        self.preview_timer.stop()
        default = self.writable_initial_directory()
        directory = QFileDialog.getExistingDirectory(self, "选择保存位置（保存列表中的全部图片）", str(default))
        if not directory:
            self.preview_timer.start()
            return
        snapshots = self.snapshots()
        def work(progress, cancel):
            return export_pngs(snapshots, Path(directory), progress, cancel)
        def completed(paths):
            self.activity.setText(f"已保存 {len(paths)} 张处理图片")
            QMessageBox.information(self, "图片已保存", f"已保存 {len(paths)} 张图片到：\n{directory}\n\n原始文件保留。")
            self.preview_timer.start()
        self.start_job("export", work, completed)

    def open_print(self):
        if self.job or not self.pages:
            return
        self.commit_controls()
        self.preview_timer.stop()
        snapshots = self.snapshots()
        directory = self.temp_path / ("print-" + uuid4().hex)
        def work(progress, cancel):
            try:
                return prepare_pages(snapshots, directory, progress, cancel)
            except Exception:
                shutil.rmtree(directory, ignore_errors=True)
                raise
        def completed(pages):
            dialog = PrintDialog(pages, self.default_output_directory(), self.settings, self)
            dialog.exec()
            dialog.refresh_timer.stop()
            dialog.deleteLater()
            shutil.rmtree(directory, ignore_errors=True)
            self.activity.setText("准备就绪 · 可继续调整图片")
            self.preview_timer.start()
        self.start_job("prepare", work, completed)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and not self.job:
            event.acceptProposedAction()

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            self.import_files([url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()])
            event.acceptProposedAction()

    def closeEvent(self, event):
        if self.job:
            self._closing = True
            self.cancel_job()
            event.ignore()
            return
        self.preview_timer.stop()
        self.edit_timer.stop()
        self.settings.sync()
        self.pool.waitForDone(2000)
        self._temp.cleanup()
        event.accept()
