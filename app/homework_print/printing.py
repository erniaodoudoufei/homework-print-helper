from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QMarginsF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPageLayout, QPageSize, QPainter
from PySide6.QtPrintSupport import QPrinter, QPrinterInfo

from .models import PrintOptions


def landscape_for(width: int, height: int, orientation: str) -> bool:
    return orientation == "landscape" or (orientation == "auto" and width > height)


def fit_rect(width: int, height: int, area: QRectF) -> QRectF:
    scale = min(area.width() / width, area.height() / height)
    w, h = width * scale, height * scale
    return QRectF(area.x() + (area.width() - w) / 2, area.y() + (area.height() - h) / 2, w, h)


def make_printer(name: str = "", pdf_path: Path | None = None) -> QPrinter:
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    if pdf_path is not None:
        printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
        printer.setOutputFileName(str(pdf_path))
        printer.setResolution(300)
    elif name:
        printer.setPrinterName(name)
    elif QPrinterInfo.defaultPrinter().isNull():
        printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
    printer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    printer.setDuplex(QPrinter.DuplexMode.DuplexNone)
    printer.setCopyCount(1)
    printer.setDocName("作业图片打印助手")
    return printer


def configure_page(printer: QPrinter, width: int, height: int, options: PrintOptions,
                   layout_printer: QPrinter | None = None) -> QRectF:
    orientation = QPageLayout.Orientation.Landscape if landscape_for(width, height, options.orientation) else QPageLayout.Orientation.Portrait
    printer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    printer.setPageOrientation(orientation)
    layout = printer.pageLayout()
    layout.setUnits(QPageLayout.Unit.Millimeter)
    minimum = layout.minimumMargins()
    if layout_printer is not None:
        # PDF saved from a printer preview must use that driver's safe margins
        # too, including when the user's requested margin is zero.
        layout_printer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
        layout_printer.setPageOrientation(orientation)
        reference = layout_printer.pageLayout()
        reference.setUnits(QPageLayout.Unit.Millimeter)
        hardware = reference.minimumMargins()
        minimum = QMarginsF(max(minimum.left(), hardware.left()), max(minimum.top(), hardware.top()),
                            max(minimum.right(), hardware.right()), max(minimum.bottom(), hardware.bottom()))
    margins = QMarginsF(max(options.margin_mm, minimum.left()), max(options.margin_mm, minimum.top()),
                        max(options.margin_mm, minimum.right()), max(options.margin_mm, minimum.bottom()))
    printer.setFullPage(True)
    # Origin is the physical paper corner. Explicitly inset from that corner,
    # accounting for BOTH user margins and the printer's hardware margins.
    page = printer.pageLayout().fullRectPixels(printer.resolution())
    factor = printer.resolution() / 25.4
    return QRectF(page).adjusted(margins.left() * factor, margins.top() * factor,
                                -margins.right() * factor, -margins.bottom() * factor)


def paint_page(painter: QPainter, path: Path, width: int, height: int,
               area: QRectF, options: PrintOptions, preview: bool = False):
    image = QImage(str(path))
    if image.isNull():
        raise ValueError(f"无法读取待打印的页面：{path.name}")
    if options.grayscale:
        image = image.convertToFormat(QImage.Format.Format_Grayscale8)
    if preview and max(image.width(), image.height()) > 2200:
        image = image.scaled(2200, 2200, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    painter.drawImage(fit_rect(width, height, area), image)


def preview_page(printer: QPrinter, page, options: PrintOptions, long_edge=1500) -> QImage:
    """Per-page canvas avoids QPrintPreviewWidget's single page-orientation limit."""
    path, width, height, _ = page
    area = configure_page(printer, width, height, options)
    full = printer.pageLayout().fullRectPixels(printer.resolution())
    scale = long_edge / max(full.width(), full.height())
    canvas = QImage(round(full.width() * scale), round(full.height() * scale), QImage.Format.Format_RGB888)
    canvas.fill(QColor("white"))
    painter = QPainter(canvas)
    try:
        scaled_area = QRectF(area.x() * scale, area.y() * scale, area.width() * scale, area.height() * scale)
        paint_page(painter, path, width, height, scaled_area, options, preview=True)
    finally:
        painter.end()
    return canvas


def render_pages(printer: QPrinter, pages, options: PrintOptions,
                 indices=None, preview: bool = False, layout_printer: QPrinter | None = None):
    indices = list(range(len(pages))) if indices is None else list(indices)
    if not indices:
        raise ValueError("没有可打印的页面。")
    _, width, height, _ = pages[indices[0]]
    first_area = configure_page(printer, width, height, options, layout_printer)
    painter = QPainter()
    if not painter.begin(printer):
        raise RuntimeError("无法开始输出，请检查打印机或文件保存位置。")
    try:
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        for output_index, page_index in enumerate(indices):
            path, width, height, _ = pages[page_index]
            if output_index:
                area = configure_page(printer, width, height, options, layout_printer)
                if not printer.newPage():
                    raise RuntimeError("无法创建下一页，打印任务可能已取消。")
            else:
                area = first_area
            painter.fillRect(QRectF(printer.pageLayout().fullRectPixels(printer.resolution())), QColor("white"))
            paint_page(painter, path, width, height, area, options, preview)
    finally:
        painter.end()


def export_pdf(target: Path, pages, options: PrintOptions, layout_printer: QPrinter | None = None):
    # Write to a sibling temporary file, commit exclusively; incomplete PDFs never
    # appear at the intended destination and existing files are not replaced.
    import tempfile
    import os
    import shutil
    handle, name = tempfile.mkstemp(prefix=".作业打印-", suffix=".pdf", dir=str(target.parent))
    os.close(handle)
    temporary = Path(name)
    try:
        printer = make_printer(pdf_path=temporary)
        render_pages(printer, pages, options, layout_printer=layout_printer)
        created = False
        try:
            with target.open("xb") as dst, temporary.open("rb") as src:
                created = True
                shutil.copyfileobj(src, dst)
        except Exception:
            if created:
                target.unlink(missing_ok=True)
            raise
    finally:
        temporary.unlink(missing_ok=True)
