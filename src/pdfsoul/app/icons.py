"""Line icons drawn from inline SVG, tinted to any colour at any size."""

from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QByteArray, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

_FILE = ('<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/>'
         '<path d="M14 3v5h5"/>')


PATHS: dict[str, str] = {
    "home": '<path d="M3 11 12 3.5 21 11"/><path d="M5.5 9.5V20h13V9.5"/>'
            '<path d="M10 20v-5.5h4V20"/>',
    "grid": '<rect x="3.5" y="3.5" width="7" height="7" rx="1.5"/>'
            '<rect x="13.5" y="3.5" width="7" height="7" rx="1.5"/>'
            '<rect x="3.5" y="13.5" width="7" height="7" rx="1.5"/>'
            '<rect x="13.5" y="13.5" width="7" height="7" rx="1.5"/>',
    "merge": '<path d="m8 6 4-4 4 4"/><path d="M12 2v10.3a4 4 0 0 1-1.17 2.87L4 22"/>'
             '<path d="m20 22-5-5"/>',
    "split": '<path d="M16 3h5v5"/><path d="M8 3H3v5"/>'
             '<path d="M12 22v-8.3a4 4 0 0 0-1.17-2.87L3 3"/><path d="m15 9 6-6"/>',
    "compress": '<path d="M4 14h6v6"/><path d="M20 10h-6V4"/><path d="m14 10 7-7"/>'
                '<path d="m3 21 7-7"/>',
    "scan": '<path d="M3 7V5a2 2 0 0 1 2-2h2"/><path d="M17 3h2a2 2 0 0 1 2 2v2"/>'
            '<path d="M21 17v2a2 2 0 0 1-2 2h-2"/><path d="M7 21H5a2 2 0 0 1-2-2v-2"/>'
            '<path d="M7.5 8.5h9"/><path d="M7.5 12h9"/><path d="M7.5 15.5h5.5"/>',
    "archive": '<rect x="3" y="4" width="18" height="5" rx="1.5"/>'
               '<path d="M5 9v9.5A1.5 1.5 0 0 0 6.5 20h11a1.5 1.5 0 0 0 1.5-1.5V9"/>'
               '<path d="M10 13h4"/>',
    "contrast": '<circle cx="12" cy="12" r="9"/>'
                '<path d="M12 3a9 9 0 0 1 0 18z" fill="{c}"/>',
    "file": _FILE,
    "file-text": _FILE + '<path d="M9 13h6"/><path d="M9 17h6"/><path d="M9 9h1.5"/>',
    "file-plus": _FILE + '<path d="M12 11.5v6"/><path d="M9 14.5h6"/>',
    "file-out": _FILE + '<path d="M12 11v7"/><path d="m9 15 3 3 3-3"/>',
    "image": '<rect x="3" y="3" width="18" height="18" rx="2.5"/><circle cx="9" cy="9" r="2"/>'
             '<path d="m21 15-3.1-3.1a2 2 0 0 0-2.8 0L6 21"/>',
    "images": '<rect x="7" y="7" width="14" height="14" rx="2"/>'
              '<path d="M3 16.5V5a2 2 0 0 1 2-2h11.5"/><circle cx="11.5" cy="11.5" r="1.5"/>'
              '<path d="m21 16-3-3-6.5 6.5"/>',
    "code": '<path d="m16 18 6-6-6-6"/><path d="m8 6-6 6 6 6"/>',
    "briefcase": '<rect x="3" y="7" width="18" height="13" rx="2"/>'
                 '<path d="M8.5 7V5.5A1.5 1.5 0 0 1 10 4h4a1.5 1.5 0 0 1 1.5 1.5V7"/>'
                 '<path d="M3 13h18"/>',
    "globe": '<circle cx="12" cy="12" r="9"/><path d="M3 12h18"/>'
             '<path d="M12 3a14 14 0 0 1 0 18a14 14 0 0 1 0-18z"/>',
    "droplet": '<path d="M12 3s6 6.4 6 11a6 6 0 0 1-12 0c0-4.6 6-11 6-11z"/>',
    "hash": '<path d="M5 9h14"/><path d="M5 15h14"/><path d="M10 4 8 20"/>'
            '<path d="m16 4-2 16"/>',
    "lock": '<rect x="4.5" y="10.5" width="15" height="10" rx="2"/>'
            '<path d="M8 10.5V7a4 4 0 0 1 8 0v3.5"/>',
    "unlock": '<rect x="4.5" y="10.5" width="15" height="10" rx="2"/>'
              '<path d="M8 10.5V7a4 4 0 0 1 7.8-1.2"/>',
    "sliders": '<path d="M4 6h9"/><path d="M19 6h1"/><circle cx="16" cy="6" r="2.5"/>'
               '<path d="M4 12h1"/><path d="M11 12h9"/><circle cx="8" cy="12" r="2.5"/>'
               '<path d="M4 18h9"/><path d="M19 18h1"/><circle cx="16" cy="18" r="2.5"/>',
    "search": '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
    "plus": '<path d="M12 5v14"/><path d="M5 12h14"/>',
    "minus": '<path d="M5 12h14"/>',
    "rotate-cw": '<path d="M20 12a8 8 0 1 1-2.34-5.66"/><path d="M20 4v5h-5"/>',
    "rotate-ccw": '<path d="M4 12a8 8 0 1 0 2.34-5.66"/><path d="M4 4v5h5"/>',
    "chevron-left": '<path d="m15 18-6-6 6-6"/>',
    "chevron-right": '<path d="m9 18 6-6-6-6"/>',
    "chevron-up": '<path d="m18 15-6-6-6 6"/>',
    "chevron-down": '<path d="m6 9 6 6 6-6"/>',
    "sidebar": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16"/>',
    "undo": '<path d="M9 14 4 9l5-5"/><path d="M4 9h10.5a5.5 5.5 0 0 1 0 11H11"/>',
    "redo": '<path d="m15 14 5-5-5-5"/><path d="M20 9H9.5a5.5 5.5 0 0 0 0 11H13"/>',
    "trash": '<path d="M4 7h16"/><path d="M10 11v6"/><path d="M14 11v6"/>'
             '<path d="m6 7 1 12.5A1.5 1.5 0 0 0 8.5 21h7a1.5 1.5 0 0 0 1.5-1.5L18 7"/>'
             '<path d="M9 7V4.5A1.5 1.5 0 0 1 10.5 3h3A1.5 1.5 0 0 1 15 4.5V7"/>',
    "copy": '<rect x="8" y="8" width="13" height="13" rx="2"/>'
            '<path d="M4 16V5a2 2 0 0 1 2-2h11"/>',
    "x": '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
    "folder": '<path d="M3 7.5A1.5 1.5 0 0 1 4.5 6H9l2 2h8.5A1.5 1.5 0 0 1 21 9.5V18a1.5 1.5 0 '
              '0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 18z"/>',
    "upload": '<path d="M12 15V4"/><path d="m7 9 5-5 5 5"/>'
              '<path d="M20 15v3.5a2.5 2.5 0 0 1-2.5 2.5h-11A2.5 2.5 0 0 1 4 18.5V15"/>',
    "check-circle": '<circle cx="12" cy="12" r="9"/><path d="m8 12.5 2.8 2.8L16.5 9.5"/>',
    "check": '<path d="M5 12.5 9.5 17 19 7.5"/>',
    "dot": '<circle cx="12" cy="12" r="5" fill="{c}" stroke="none"/>',
    "alert": '<circle cx="12" cy="12" r="9"/><path d="M12 7.5v5.5"/><path d="M12 16.5h.01"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v5.5"/><path d="M12 7.5h.01"/>',
    "heart": '<path d="M12 20s-7.5-4.6-7.5-10.2A4.3 4.3 0 0 1 12 7.2a4.3 4.3 0 0 1 7.5 2.6'
             'C19.5 15.4 12 20 12 20Z" fill="{c}"/>',
    "arrow-right": '<path d="M5 12h14"/><path d="m13 6 6 6-6 6"/>',
    "fit-width": '<path d="M3 12h18"/><path d="m7 8-4 4 4 4"/><path d="m17 8 4 4-4 4"/>',
    "external": '<path d="M14 4h6v6"/><path d="M20 4 11 13"/>'
                '<path d="M19 14v4.5a1.5 1.5 0 0 1-1.5 1.5h-12A1.5 1.5 0 0 1 4 18.5v-12A1.5 1.5 0 '
                '0 1 5.5 5H10"/>',
    "sparkle": '<path d="M12 3v4"/><path d="M12 17v4"/><path d="M3 12h4"/><path d="M17 12h4"/>'
               '<path d="m6 6 2.5 2.5"/><path d="m15.5 15.5 2.5 2.5"/><path d="m6 18 2.5-2.5"/>'
               '<path d="m15.5 8.5 2.5-2.5"/>',
}


def svg(name: str, color: str, stroke: float = 1.8) -> str:
    body = PATHS[name].replace("{c}", color)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
            f'stroke="{color}" stroke-width="{stroke}" stroke-linecap="round" '
            f'stroke-linejoin="round">{body}</svg>')


@lru_cache(maxsize=512)
def _pixmap(name: str, color: str, size: int, dpr: float, stroke: float) -> QPixmap:
    renderer = QSvgRenderer(QByteArray(svg(name, color, stroke).encode()))
    pix = QPixmap(int(size * dpr), int(size * dpr))
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter, QRectF(0, 0, size * dpr, size * dpr))
    painter.end()
    pix.setDevicePixelRatio(dpr)
    return pix


def pixmap(name: str, color: QColor | str, size: int = 18, dpr: float = 2.0,
           stroke: float = 1.8) -> QPixmap:
    return _pixmap(name, QColor(color).name(), size, dpr, stroke)


def icon(name: str, color: QColor | str, selected: QColor | str | None = None,
         disabled: QColor | str | None = None, size: int = 18) -> QIcon:
    """A crisp icon; optional colours for the selected and disabled states."""
    result = QIcon()
    for mode, tint in ((QIcon.Mode.Normal, color), (QIcon.Mode.Active, color),
                       (QIcon.Mode.Selected, selected or color),
                       (QIcon.Mode.Disabled, disabled or QColor(color).lighter(160))):
        for scale in (1.0, 2.0):
            result.addPixmap(pixmap(name, tint, size, scale), mode)
    return result


def chip(name: str, color: QColor | str, size: int = 40, dark: bool = False,
         dpr: float = 2.0) -> QPixmap:
    """The tool's icon on a rounded, softly tinted square — used for cards and headers."""
    base = QColor(color)
    pix = QPixmap(int(size * dpr), int(size * dpr))
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    fill = QColor(base)
    fill.setAlphaF(0.22 if dark else 0.12)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(fill)
    s = size * dpr
    painter.drawRoundedRect(QRectF(0, 0, s, s), s * 0.28, s * 0.28)
    glyph = base.lighter(135) if dark else base
    inner = int(size * 0.55)
    offset = (size - inner) / 2 * dpr
    painter.drawPixmap(QRectF(offset, offset, inner * dpr, inner * dpr).toRect(),
                       pixmap(name, glyph, inner, dpr, 2.0))
    painter.end()
    pix.setDevicePixelRatio(dpr)
    return pix


BADGES: dict[str, tuple[str, str]] = {
    # name: (label, colour) — the coloured file icons used for every format conversion
    "img": ("IMG", "#f0912f"),
    "word": ("W", "#4b8df2"),
    "excel": ("XLS", "#5bab4f"),
    "powerpoint": ("PPT", "#e8693c"),
    "pdf": ("PDF", "#e5463f"),
    "txt": ("TXT", "#8d93a3"),
    "html": ("WEB", "#1aa3a0"),
    "pdfa": ("PDF/A", "#b05de8"),
    "epub": ("EPUB", "#d6578f"),
}


@lru_cache(maxsize=256)
def _badge(name: str, size: int, dpr: float) -> QPixmap:
    from PySide6.QtGui import QFont, QPainterPath

    label, color = BADGES[name]
    s = size * dpr
    pix = QPixmap(int(s), int(s))
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    single = len(label) == 1
    # A single letter (W) sits on a rounded square; longer labels on a folded page.
    w = s * (0.86 if single else 0.74)
    h = s * (0.86 if single else 0.92)
    x, y = (s - w) / 2, (s - h) / 2
    r = s * 0.12
    base = QColor(color)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(base)
    if single:
        painter.drawRoundedRect(QRectF(x, y, w, h), r, r)
    else:
        fold = w * 0.34
        page = QPainterPath()
        page.moveTo(x + r, y)
        page.lineTo(x + w - fold, y)
        page.lineTo(x + w, y + fold)
        page.lineTo(x + w, y + h - r)
        page.quadTo(x + w, y + h, x + w - r, y + h)
        page.lineTo(x + r, y + h)
        page.quadTo(x, y + h, x, y + h - r)
        page.lineTo(x, y + r)
        page.quadTo(x, y, x + r, y)
        painter.drawPath(page)
        flap = QPainterPath()
        flap.moveTo(x + w - fold, y)
        flap.lineTo(x + w - fold, y + fold - r * 0.4)
        flap.quadTo(x + w - fold, y + fold, x + w - fold + r * 0.4, y + fold)
        flap.lineTo(x + w, y + fold)
        flap.closeSubpath()
        painter.setBrush(base.lighter(135))
        painter.drawPath(flap)
    font = QFont("Helvetica Neue")
    font.setStyleHint(QFont.StyleHint.SansSerif)
    font.setBold(True)
    font.setPixelSize(int(s * (0.56 if single else 0.24 if len(label) <= 3 else 0.19)))
    painter.setFont(font)
    painter.setPen(QColor("#ffffff"))
    text_box = QRectF(x, y, w, h) if single else QRectF(x, y + h * 0.42, w, h * 0.5)
    painter.drawText(text_box, Qt.AlignmentFlag.AlignCenter, label)
    painter.end()
    pix.setDevicePixelRatio(dpr)
    return pix


def badge(name: str, size: int = 20, dpr: float = 2.0) -> QPixmap:
    return _badge(name, size, dpr)


def badge_icon(name: str, size: int = 20) -> QIcon:
    result = QIcon()
    for scale in (1.0, 2.0):
        result.addPixmap(_badge(name, size, scale))
    return result


def app_mark(size: int = 28, dpr: float = 2.0, accent: str = "#6d4aff") -> QPixmap:
    """The PDFSoul mark: a gradient tile with a folded page and a spark."""
    from PySide6.QtGui import QLinearGradient

    s = size * dpr
    pix = QPixmap(int(s), int(s))
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    gradient = QLinearGradient(0, 0, s, s)
    gradient.setColorAt(0, QColor(accent).lighter(125))
    gradient.setColorAt(1, QColor("#e5322d"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(gradient)
    painter.drawRoundedRect(QRectF(0, 0, s, s), s * 0.26, s * 0.26)
    inner = int(size * 0.62)
    offset = (size - inner) / 2 * dpr
    painter.drawPixmap(QRectF(offset, offset, inner * dpr, inner * dpr).toRect(),
                       pixmap("file", "#ffffff", inner, dpr, 2.2))
    painter.end()
    pix.setDevicePixelRatio(dpr)
    return pix


def size(n: int) -> QSize:
    return QSize(n, n)
