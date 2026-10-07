"""Read this window's physical origin and filter premultiplied subpixel motion."""

import ctypes
import math
from ctypes import wintypes

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QImage, QPainter


class MonitorInfo(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("monitor", wintypes.RECT),
                ("work", wintypes.RECT), ("flags", wintypes.DWORD)]


_user32 = ctypes.WinDLL("user32", use_last_error=True)
_user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
_user32.ClientToScreen.restype = wintypes.BOOL
_user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
_user32.MonitorFromWindow.restype = wintypes.HANDLE
_user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MonitorInfo)]
_user32.GetMonitorInfoW.restype = wintypes.BOOL


def map_native_origin(point, native_screen, logical_screen, ratio):
    return (logical_screen[0] + (point[0] - native_screen[0]) / ratio,
            logical_screen[1] + (point[1] - native_screen[1]) / ratio)


def native_client_origin(hwnd, logical_screen, ratio):
    """No input injection: query only the calling pet's own client window."""
    point = wintypes.POINT(0, 0)
    info = MonitorInfo()
    info.size = ctypes.sizeof(info)
    if not _user32.ClientToScreen(hwnd, ctypes.byref(point)):
        return None
    monitor = _user32.MonitorFromWindow(hwnd, 2)
    if not monitor or not _user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
        return None
    return map_native_origin((point.x, point.y), (info.monitor.left, info.monitor.top), logical_screen, ratio)


def quantized_origin(position, screen_origin, ratio):
    """Qt-compatible fallback before a native window exists (including tests)."""
    def qround(value):
        return math.floor(value + 0.5) if value >= 0 else -math.floor(-value + 0.5)
    return tuple(origin + qround((value - origin) * ratio) / ratio
                 for value, origin in zip(position, screen_origin))


def presentation_offset(offset, ratio, interpolate=True):
    """Align stationary raster pixels without rounding the world-space anchor."""
    if not math.isfinite(ratio) or ratio <= 0:
        raise ValueError("Device pixel ratio must be finite and positive")
    if interpolate:
        return tuple(offset)
    def nearest(value):
        return math.floor(value + 0.5) if value >= 0 else math.ceil(value - 0.5)
    return tuple(nearest(value * ratio) / ratio for value in offset)


def shift_layer(image, offset, ratio, interpolate=True):
    """Separable bilinear filtering, including glyphs, on the physical pixel grid.

    Qt's 1:1 image blit rounds fractional translations. Source-mode opacity
    interpolates premultiplied RGBA instead; opaque overlaps remain opaque and
    dark artwork is not keyed or recolored. Transparent margins absorb clipping.
    Stationary presentation uses integer physical displacement, not interpolation;
    it must not soften captions or quantize saved/continuous movement coordinates.
    """
    if image.isNull():
        return image
    offset = presentation_offset(offset, ratio, interpolate)
    result = image
    for horizontal, displacement in ((True, offset[0] * ratio), (False, offset[1] * ratio)):
        if abs(displacement) < 1e-7:
            continue
        integer = math.floor(displacement)
        fraction = displacement - integer
        output = QImage(image.size(), QImage.Format_ARGB32_Premultiplied)
        output.fill(Qt.transparent)
        painter = QPainter(output)
        painter.setCompositionMode(QPainter.CompositionMode_Source)
        width, height = result.width(), result.height()
        left, top = (integer, 0) if horizontal else (0, integer)
        source = QRectF(0, 0, width, height)
        painter.drawImage(QRectF(left, top, width, height), result, source)
        if fraction > 1e-7:
            painter.setOpacity(fraction)
            painter.drawImage(QRectF(left + int(horizontal), top + int(not horizontal), width, height), result, source)
        painter.end()
        result = output
    result.setDevicePixelRatio(ratio)
    return result
