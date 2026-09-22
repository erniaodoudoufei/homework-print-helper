from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from threading import Event

import cv2
import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

from .models import EditSettings

cv2.setNumThreads(2)
MAX_PIXELS = 60_000_000


class Cancelled(Exception):
    pass


def checkpoint(cancel: Event | None) -> None:
    if cancel is not None and cancel.is_set():
        raise Cancelled("已取消")


def load_rgb(path: Path) -> np.ndarray:
    try:
        with Image.open(path) as image:
            if image.width * image.height > MAX_PIXELS:
                raise ValueError("图片超过 6000 万像素，请先缩小后导入。")
            image = ImageOps.exif_transpose(image)
            if image.mode in ("RGBA", "LA") or "transparency" in image.info:
                rgba = image.convert("RGBA")
                canvas = Image.new("RGBA", rgba.size, "white")
                canvas.alpha_composite(rgba)
                image = canvas
            result = np.asarray(image.convert("RGB")).copy()
            if min(result.shape[:2]) < 16:
                raise ValueError("图片尺寸太小，无法处理。")
            return result
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError(f"无法读取图片：{path.name}，文件可能损坏或格式不受支持。") from exc


def resize_preview(rgb: np.ndarray, maximum: int = 1500) -> np.ndarray:
    h, w = rgb.shape[:2]
    if max(h, w) <= maximum:
        return rgb.copy()
    scale = maximum / max(h, w)
    return cv2.resize(rgb, (max(1, round(w * scale)), max(1, round(h * scale))), interpolation=cv2.INTER_AREA)


def order_quad(points: np.ndarray) -> np.ndarray:
    points = np.asarray(points, dtype=np.float32).reshape(4, 2)
    center = points.mean(axis=0)
    points = points[np.argsort(np.arctan2(points[:, 1] - center[1], points[:, 0] - center[0]))]
    start = int(np.argmin(points.sum(axis=1)))
    return np.roll(points, -start, axis=0)


def valid_quad(quad: np.ndarray) -> bool:
    quad = np.asarray(quad, np.float32)
    return bool(quad.shape == (4, 2) and np.isfinite(quad).all()
                and (quad >= 0).all() and (quad <= 1).all()
                and cv2.isContourConvex(quad) and abs(cv2.contourArea(quad)) > 0.01
                and min(np.linalg.norm(quad - np.roll(quad, 1, axis=0), axis=1)) > 0.02)


def warp_document(rgb: np.ndarray, normalized_quad) -> np.ndarray:
    quad = np.asarray(normalized_quad, np.float32)
    if not valid_quad(quad):
        raise ValueError("四个角必须围成不交叉的纸张区域，请重新调整。")
    h, w = rgb.shape[:2]
    points = quad * np.array([w - 1, h - 1], np.float32)
    tl, tr, br, bl = points
    width = round(max(np.linalg.norm(tr - tl), np.linalg.norm(br - bl)))
    height = round(max(np.linalg.norm(bl - tl), np.linalg.norm(br - tr)))
    width, height = max(16, width), max(16, height)
    target = np.array([[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]], np.float32)
    matrix = cv2.getPerspectiveTransform(points, target)
    return cv2.warpPerspective(rgb, matrix, (width, height), flags=cv2.INTER_CUBIC,
                               borderMode=cv2.BORDER_CONSTANT, borderValue=(255, 255, 255))


def rotate_expanded(rgb: np.ndarray, angle: float) -> np.ndarray:
    if abs(angle) < 0.03:
        return rgb
    h, w = rgb.shape[:2]
    matrix = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1)
    cosine, sine = abs(matrix[0, 0]), abs(matrix[0, 1])
    new_w, new_h = int(np.ceil(h * sine + w * cosine)), int(np.ceil(h * cosine + w * sine))
    matrix[0, 2] += (new_w - w) / 2
    matrix[1, 2] += (new_h - h) / 2
    return cv2.warpAffine(rgb, matrix, (new_w, new_h), flags=cv2.INTER_CUBIC,
                          borderMode=cv2.BORDER_CONSTANT, borderValue=(255, 255, 255))


def geometry(rgb: np.ndarray, settings: EditSettings, include_crop=True) -> np.ndarray:
    result = warp_document(rgb, settings.quad) if settings.quad is not None else rgb
    if settings.rotation % 4:
        result = np.ascontiguousarray(np.rot90(result, -(settings.rotation % 4)))
    result = rotate_expanded(result, settings.deskew)
    if include_crop and settings.crop is not None:
        left, top, right, bottom = settings.crop
        if not (0 <= left < right <= 1 and 0 <= top < bottom <= 1):
            raise ValueError("裁切范围无效。")
        h, w = result.shape[:2]
        x0, y0 = int(left * w), int(top * h)
        x1, y1 = min(w, round(right * w)), min(h, round(bottom * h))
        if x1 - x0 < 8 or y1 - y0 < 8:
            raise ValueError("裁切区域太小，请扩大范围。")
        result = result[y0:y1, x0:x1].copy()
    return result


def _edge_contrast(gray: np.ndarray, points: np.ndarray) -> float:
    # Page boundaries separate light paper from a darker surround. Grid borders don't.
    h, w = gray.shape
    center = points.mean(axis=0)
    differences = []
    for i in range(4):
        for t in np.linspace(0.15, 0.85, 9):
            point = points[i] * (1 - t) + points[(i + 1) % 4] * t
            inward = center - point
            inward /= max(1, np.linalg.norm(inward))
            inside, outside = point + inward * 12, point - inward * 12
            if 1 <= outside[0] < w - 1 and 1 <= outside[1] < h - 1:
                ix, iy = np.clip(inside.astype(int), [0, 0], [w - 1, h - 1])
                ox, oy = outside.astype(int)
                differences.append(float(gray[iy, ix]) - float(gray[oy, ox]))
    return float(np.median(differences)) if len(differences) >= 15 else 0.0


def detect_quad(rgb: np.ndarray):
    small = resize_preview(rgb, 1100)
    h, w = small.shape[:2]
    gray = cv2.cvtColor(small, cv2.COLOR_RGB2GRAY)
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    _, binary = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    edges = cv2.Canny(blur, 35, 110)
    edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    candidates = []
    for mask in (binary, edges):
        contours, _ = cv2.findContours(mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        for contour in sorted(contours, key=cv2.contourArea, reverse=True)[:15]:
            ratio = cv2.contourArea(contour) / (w * h)
            if not 0.45 <= ratio <= 0.985:
                continue
            polygon = cv2.approxPolyDP(contour, 0.018 * cv2.arcLength(contour, True), True)
            if len(polygon) != 4 or not cv2.isContourConvex(polygon):
                continue
            points = order_quad(polygon)
            normalized = points / np.array([w - 1, h - 1], np.float32)
            if not valid_quad(normalized):
                continue
            # Reject paper cut off at the photograph boundary: manual review is safer.
            if np.any(normalized < 0.006) or np.any(normalized > 0.994):
                continue
            contrast = _edge_contrast(gray, points)
            if contrast < 18:
                continue
            candidates.append((ratio + min(contrast, 100) / 500, normalized))
    if not candidates:
        return None
    quad = max(candidates, key=lambda item: item[0])[1]
    return tuple(tuple(float(v) for v in point) for point in quad)


def detect_skew(rgb: np.ndarray) -> float:
    small = resize_preview(rgb, 1200)
    gray = cv2.cvtColor(small, cv2.COLOR_RGB2GRAY)
    edges = cv2.Canny(gray, 45, 135)
    h, w = gray.shape
    lines = cv2.HoughLinesP(edges, 1, np.pi / 1800, threshold=70,
                            minLineLength=max(80, w // 7), maxLineGap=20)
    if lines is None:
        return 0.0
    values = []
    for x1, y1, x2, y2 in lines[:, 0]:
        angle = np.degrees(np.arctan2(float(y2 - y1), float(x2 - x1)))
        angle = (angle + 90) % 180 - 90
        if abs(angle) <= 6:
            values.append(angle)
    if len(values) < 5:
        return 0.0
    median = float(np.median(values))
    if np.median(np.abs(np.asarray(values) - median)) > 1.0 or abs(median) < 0.15:
        return 0.0
    return round(median, 2)


def suggest_settings(rgb: np.ndarray, cancel: Event | None = None) -> tuple[EditSettings, str]:
    checkpoint(cancel)
    quad = detect_quad(rgb)
    checkpoint(cancel)
    corrected = warp_document(resize_preview(rgb), quad) if quad else resize_preview(rgb)
    angle = detect_skew(corrected)
    note = "已自动识别纸张，可拖动四角微调" if quad else "已保留完整范围；如有桌面或透视，请使用「四角拉正」"
    if angle:
        note += f" · 纠偏 {angle:+.2f}°"
    return EditSettings(quad=quad, deskew=angle), note


def enhance(rgb: np.ndarray, whitening: int, ink: int, grayscale: bool,
            cancel: Event | None = None) -> np.ndarray:
    if whitening == 0 and ink == 0 and not grayscale:
        return rgb.copy()
    checkpoint(cancel)
    result = rgb.astype(np.float32)
    if whitening:
        # Closing removes dark strokes from the paper estimate. Work at a fixed
        # scale so sliders behave consistently in preview and full-resolution export.
        sample = resize_preview(rgb, 1100)
        kernel_size = max(15, round(max(sample.shape[:2]) / 28)) | 1
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel_size, kernel_size))
        background = cv2.morphologyEx(sample, cv2.MORPH_CLOSE, kernel)
        background = cv2.GaussianBlur(background, (0, 0), kernel_size / 3)
        background = cv2.resize(background, (rgb.shape[1], rgb.shape[0]), interpolation=cv2.INTER_LINEAR)
        checkpoint(cancel)
        normalized = np.clip(result / np.maximum(background.astype(np.float32), 35.0) * 255, 0, 255)
        strength = np.clip(whitening / 75, 0, 1)
        result = result * (1 - strength) + normalized * strength
        # A small white-point adjustment removes JPEG residue without hard thresholding.
        white_point = 255 - whitening * 0.085
        result = np.clip(result * 255 / white_point, 0, 255)
    checkpoint(cancel)
    if ink:
        darkness = (255 - result) / 255
        result = 255 * (1 - np.clip(darkness * (1 + ink / 90), 0, 1))
    result = np.clip(result, 0, 255).astype(np.uint8)
    if grayscale:
        result = cv2.cvtColor(cv2.cvtColor(result, cv2.COLOR_RGB2GRAY), cv2.COLOR_GRAY2RGB)
    return result


def process(rgb: np.ndarray, settings: EditSettings, maximum: int | None = None,
            cancel: Event | None = None) -> np.ndarray:
    checkpoint(cancel)
    if maximum:
        rgb = resize_preview(rgb, maximum)
    result = geometry(rgb, settings)
    checkpoint(cancel)
    result = enhance(result, settings.whitening, settings.ink, settings.grayscale, cancel)
    checkpoint(cancel)
    return np.ascontiguousarray(result)
