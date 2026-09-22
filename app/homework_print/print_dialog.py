from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QSettings, QTimer, Signal
from PySide6.QtGui import QPageSize
from PySide6.QtPrintSupport import QPrinter, QPrinterInfo
from PySide6.QtWidgets import (QComboBox, QDialog, QFileDialog, QFormLayout,
                              QHBoxLayout, QLabel, QMessageBox, QPushButton,
                              QSpinBox, QVBoxLayout, QWidget)

from .models import PrintOptions
from .outputs import unique_path
from .printing import export_pdf, make_printer, render_pages, preview_page
from .widgets import ImageView


class PagePreview(QWidget):
    previewChanged = Signal()

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.view = ImageView()
        layout.addWidget(self.view)
        self.pages = []
        self.current = 1
        self.printer = None
        self.options = None

    def set_pages(self, pages, printer, options):
        self.pages, self.printer, self.options = pages, printer, options
        self.current = min(max(1, self.current), len(pages))
        self.show_page()

    def show_page(self):
        if self.pages:
            self.view.set_image(preview_page(self.printer, self.pages[self.current - 1], self.options))
        self.previewChanged.emit()

    def currentPage(self):
        return self.current

    def pageCount(self):
        return len(self.pages)

    def setCurrentPage(self, value):
        self.current = min(max(1, value), len(self.pages))
        self.show_page()

    def fitInView(self):
        self.view.fit_image()

    def zoomIn(self):
        self.view.zoom(1.2)

    def zoomOut(self):
        self.view.zoom(1 / 1.2)


class PrintDialog(QDialog):
    def __init__(self, pages, default_directory: Path, settings: QSettings, parent=None):
        super().__init__(parent)
        self.pages = pages
        self.default_directory = default_directory
        self.settings = settings
        self.setWindowTitle("A4 打印预览 · 作业图片打印助手")
        self.resize(1160, 830)
        self.preview_error = ""
        self.preview_printer = make_printer()
        layout = QHBoxLayout(self)
        sidebar = QWidget()
        sidebar.setFixedWidth(248)
        controls = QVBoxLayout(sidebar)
        heading = QLabel("打印与保存")
        heading.setObjectName("sectionTitle")
        controls.addWidget(heading)
        hint = QLabel("A4 · 一张图片一页\n等比例排版，完整保留内容")
        hint.setObjectName("hint")
        controls.addWidget(hint)
        form = QFormLayout()
        form.setVerticalSpacing(16)
        self.orientation = QComboBox()
        for label, value in [("自动横竖版", "auto"), ("全部纵向", "portrait"), ("全部横向", "landscape")]:
            self.orientation.addItem(label, value)
        self.margin = QSpinBox()
        self.margin.setRange(0, 30)
        self.margin.setValue(5)
        self.margin.setSuffix(" mm")
        self.colors = QComboBox()
        self.colors.addItems(["保留页面颜色", "全部黑白打印"])
        form.addRow("纸张方向", self.orientation)
        form.addRow("页面留白", self.margin)
        form.addRow("打印颜色", self.colors)
        self.first = QSpinBox()
        self.last = QSpinBox()
        for spin in (self.first, self.last):
            spin.setRange(1, len(pages))
        self.last.setValue(len(pages))
        form.addRow("起始页", self.first)
        form.addRow("结束页", self.last)
        self.copies = QSpinBox()
        self.copies.setRange(1, 99)
        form.addRow("打印份数", self.copies)
        controls.addLayout(form)
        controls.addSpacing(12)
        controls.addWidget(QLabel("打印机"))
        self.printers = QComboBox()
        self.printers.addItems(QPrinterInfo.availablePrinterNames())
        saved_name = settings.value("printer", QPrinterInfo.defaultPrinterName(), str)
        found = self.printers.findText(saved_name)
        if found < 0:
            found = self.printers.findText(QPrinterInfo.defaultPrinterName())
        if found >= 0:
            self.printers.setCurrentIndex(found)
        self.printers.setToolTip("使用 Windows 中已经安装的打印机驱动")
        controls.addWidget(self.printers)
        printer_hint = QLabel("单面打印。实际留白会兼顾打印机的不可打印区域。")
        printer_hint.setWordWrap(True)
        printer_hint.setObjectName("hint")
        controls.addWidget(printer_hint)
        controls.addStretch()
        self.status = QLabel(f"共 {len(pages)} 页")
        self.status.setWordWrap(True)
        self.status.setObjectName("hint")
        controls.addWidget(self.status)
        self.print_button = QPushButton("打印")
        self.print_button.setObjectName("primary")
        self.print_button.setMinimumHeight(40)
        self.print_button.setEnabled(self.printers.count() > 0)
        self.print_button.clicked.connect(self.print_document)
        controls.addWidget(self.print_button)
        self.pdf_button = QPushButton("保存为 PDF")
        self.pdf_button.clicked.connect(self.save_pdf)
        controls.addWidget(self.pdf_button)
        close = QPushButton("返回调整")
        close.clicked.connect(self.reject)
        controls.addWidget(close)
        layout.addWidget(sidebar)
        right = QVBoxLayout()
        toolbar = QHBoxLayout()
        for text, callback in [("适合整页", self.fit_preview), ("放大", lambda: self.preview.zoomIn()),
                               ("缩小", lambda: self.preview.zoomOut()), ("上一页", self.previous_page),
                               ("下一页", self.next_page)]:
            button = QPushButton(text)
            button.clicked.connect(callback)
            toolbar.addWidget(button)
        toolbar.addStretch()
        self.page_label = QLabel()
        toolbar.addWidget(self.page_label)
        right.addLayout(toolbar)
        self.preview = PagePreview()
        self.preview.previewChanged.connect(self.preview_changed)
        right.addWidget(self.preview, 1)
        layout.addLayout(right, 1)
        self.refresh_timer = QTimer(self)
        self.refresh_timer.setSingleShot(True)
        self.refresh_timer.setInterval(150)
        self.refresh_timer.timeout.connect(self.refresh_preview)
        for combo in (self.orientation, self.colors, self.printers):
            combo.currentIndexChanged.connect(lambda: self.refresh_timer.start())
        self.printers.currentTextChanged.connect(self.remember_printer)
        for spin in (self.margin, self.first, self.last):
            spin.valueChanged.connect(lambda: self.refresh_timer.start())
        QTimer.singleShot(0, self.refresh_preview)

    def options(self):
        return PrintOptions(self.orientation.currentData(), self.margin.value(), self.colors.currentIndex() == 1)

    def remember_printer(self, name):
        if name:
            self.settings.setValue("printer", name)

    def selected_indices(self):
        return list(range(self.first.value() - 1, self.last.value()))

    def selected_pages(self):
        return [self.pages[i] for i in self.selected_indices()]

    def refresh_preview(self):
        if self.first.value() > self.last.value():
            self.last.setValue(self.first.value())
        if self.printers.count():
            self.preview_printer.setOutputFormat(QPrinter.OutputFormat.NativeFormat)
            self.preview_printer.setPrinterName(self.printers.currentText())
        else:
            self.preview_printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
        self.preview_error = ""
        try:
            self.preview.set_pages(self.selected_pages(), self.preview_printer, self.options())
        except Exception as exc:
            self.preview_error = str(exc)
        self.fit_preview()
        self.status.setText(self.preview_error or f"已选 {len(self.selected_indices())} 页 · 单面打印")

    def preview_changed(self):
        self.page_label.setText(f"{self.preview.currentPage()} / {self.preview.pageCount()}")

    def fit_preview(self):
        self.preview.fitInView()

    def previous_page(self):
        self.preview.setCurrentPage(max(1, self.preview.currentPage() - 1))

    def next_page(self):
        self.preview.setCurrentPage(min(self.preview.pageCount(), self.preview.currentPage() + 1))

    def print_document(self):
        if not self.printers.currentText():
            return
        if self.first.value() > self.last.value():
            QMessageBox.information(self, "页码范围", "结束页不能小于起始页。")
            return
        name = self.printers.currentText()
        printer = make_printer(name)
        if not printer.isValid():
            QMessageBox.warning(self, "打印机不可用", "请检查打印机驱动，或先保存为 PDF。")
            return
        printer.setCopyCount(self.copies.value())
        printer.setCollateCopies(True)
        printer.setColorMode(QPrinter.ColorMode.GrayScale if self.options().grayscale else QPrinter.ColorMode.Color)
        self.print_button.setEnabled(False)
        try:
            indices = self.selected_indices()
            if not printer.supportsMultipleCopies():
                printer.setCopyCount(1)
                indices = indices * self.copies.value()
            render_pages(printer, self.pages, self.options(), indices)
            if printer.printerState() in (QPrinter.PrinterState.Error, QPrinter.PrinterState.Aborted):
                raise RuntimeError("驱动报告打印失败或任务已取消，请检查 Windows 打印队列。")
            self.settings.setValue("printer", name)
            self.settings.sync()
            QMessageBox.information(self, "已提交打印任务", f"已提交到 {name}。\n实际出纸状态请查看打印机或 Windows 打印队列。")
        except Exception as exc:
            QMessageBox.warning(self, "打印未完成", str(exc))
        finally:
            self.print_button.setEnabled(True)

    def save_pdf(self):
        self.refresh_preview()
        try:
            self.default_directory.mkdir(parents=True, exist_ok=True)
            directory = self.default_directory
        except OSError:
            directory = Path.home()
        initial = unique_path(directory, "作业图片", ".pdf")
        name, _ = QFileDialog.getSaveFileName(self, "保存 PDF", str(initial), "PDF 文件 (*.pdf)",
                                             options=QFileDialog.Option.DontConfirmOverwrite)
        if not name:
            return
        target = Path(name)
        if target.suffix.lower() != ".pdf":
            target = target.with_suffix(".pdf")
        target = unique_path(target.parent, target.stem, ".pdf")
        self.pdf_button.setEnabled(False)
        try:
            export_pdf(target, self.selected_pages(), self.options(), layout_printer=self.preview_printer)
            QMessageBox.information(self, "PDF 已保存", str(target))
        except Exception as exc:
            QMessageBox.warning(self, "保存未完成", str(exc))
        finally:
            self.pdf_button.setEnabled(True)
