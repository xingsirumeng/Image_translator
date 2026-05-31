from __future__ import annotations

from io import BytesIO

from PIL import Image
from PySide6.QtCore import QBuffer, QIODevice, QRect
from PySide6.QtGui import QGuiApplication, QPixmap


def qimage_to_pil(qimage) -> Image.Image:
    """把 QImage 转成 PIL Image。"""
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.ReadWrite)
    try:
        if not qimage.save(buffer, "PNG"):
            raise RuntimeError("QImage 转换失败")
        data = bytes(buffer.data())
    finally:
        buffer.close()

    return Image.open(BytesIO(data)).convert("RGBA")


def qpixmap_to_pil(pixmap: QPixmap) -> Image.Image:
    """把 QPixmap 转成 PIL Image。"""
    if pixmap.isNull():
        raise RuntimeError("空截图，无法转换")
    return qimage_to_pil(pixmap.toImage())


def pil_to_qpixmap(image: Image.Image) -> QPixmap:
    """把 PIL Image 转成 QPixmap。"""
    buffer = BytesIO()
    image.save(buffer, format="PNG")

    pixmap = QPixmap()
    if not pixmap.loadFromData(buffer.getvalue(), "PNG"):
        raise RuntimeError("PIL 图片转 QPixmap 失败")
    return pixmap


def _intersecting_screens(rect: QRect):
    """返回与选区相交的屏幕列表。"""
    normalized = QRect(rect).normalized()
    return [
        screen
        for screen in QGuiApplication.screens()
        if normalized.intersects(screen.geometry())
    ]


def capture_rect_with_screen_info(rect: QRect) -> tuple[Image.Image, dict]:
    """抓取屏幕上的指定区域，并返回 PIL 图片和截图元数据。"""
    normalized = QRect(rect).normalized()
    if normalized.width() <= 0 or normalized.height() <= 0:
        raise ValueError("截图区域无效")

    screens = _intersecting_screens(normalized)
    if len(screens) > 1:
        raise ValueError("暂不支持跨屏截图，请在单个显示器内选择区域")

    screen = screens[0] if screens else QGuiApplication.screenAt(normalized.center())
    screen = screen or QGuiApplication.primaryScreen()
    if screen is None:
        raise RuntimeError("未找到可用屏幕")

    geometry = screen.geometry()
    local_rect = normalized.translated(-geometry.topLeft())
    pixmap = screen.grabWindow(
        0,
        local_rect.x(),
        local_rect.y(),
        local_rect.width(),
        local_rect.height(),
    )

    if pixmap.isNull():
        raise RuntimeError("屏幕截图失败")

    image = qpixmap_to_pil(pixmap)
    device_pixel_ratio = float(pixmap.devicePixelRatio() or screen.devicePixelRatio() or 1.0)
    capture_info = {
        "screen_name": screen.name(),
        "device_pixel_ratio": device_pixel_ratio,
        "logical_rect": (
            normalized.x(),
            normalized.y(),
            normalized.width(),
            normalized.height(),
        ),
        "image_size": image.size,
    }
    return image, capture_info


def capture_rect(rect: QRect) -> Image.Image:
    """兼容旧接口，只返回截图图像。"""
    image, _ = capture_rect_with_screen_info(rect)
    return image
