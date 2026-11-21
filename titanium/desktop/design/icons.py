"""Line icons, drawn from inline SVG in any colour (1.6px strokes on a 24px grid)."""
from __future__ import annotations

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

_PATHS = {
    "data": '<ellipse cx="12" cy="5.5" rx="7" ry="2.5"/><path d="M5 5.5v6.5c0 1.4 3.1 2.5 7 2.5s7-1.1 7-2.5V5.5"/>'
            '<path d="M5 12v6.5c0 1.4 3.1 2.5 7 2.5s7-1.1 7-2.5V12"/>',
    "strategies": '<rect x="3" y="4" width="6" height="5" rx="1.5"/><rect x="15" y="4" width="6" height="5" rx="1.5"/>'
                  '<rect x="9" y="15" width="6" height="5" rx="1.5"/><path d="M6 9v2.5a2 2 0 0 0 2 2h1.5M18 9v2.5a2 2 0 0 1-2 2h-1.5M12 13.5V15"/>',
    "compare": '<path d="M3 20h18"/><path d="M4 16l4.5-5 3.5 3 6-7.5"/><path d="M4 18l5-2.5 4 1.5 7-4" stroke-dasharray="2 2.2"/>',
    "backtests": '<path d="M9 3h6M10 3v5.5L5 18a2 2 0 0 0 1.8 3h10.4A2 2 0 0 0 19 18l-5-9.5V3"/><path d="M7.5 14h9"/>',
    "settings": '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
    "chevron": '<path d="M7 10l5 5 5-5"/>',
    "chevron_right": '<path d="M10 7l5 5-5 5"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "play": '<path d="M7 4.5v15l12-7.5z"/>',
    "close": '<path d="M6 6l12 12M18 6L6 18"/>',
    "search": '<circle cx="11" cy="11" r="6.5"/><path d="M20 20l-4.2-4.2"/>',
    "folder": '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    "file": '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/>',
    "module": '<rect x="4" y="6" width="16" height="12" rx="2.5"/><circle cx="4" cy="12" r="1.6"/><circle cx="20" cy="12" r="1.6"/>',
    "code": '<path d="M8.5 7L3.5 12l5 5M15.5 7l5 5-5 5"/>',
    "graph": '<path d="M3 3v18h18"/><path d="M7 15l4-4 3 3 6-7"/>',
    "dock": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M15 4v16"/>',
    "page": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 8.5h18"/>',
    "list": '<path d="M9 6h11M9 12h11M9 18h11"/><circle cx="4.5" cy="6" r=".8"/><circle cx="4.5" cy="12" r=".8"/><circle cx="4.5" cy="18" r=".8"/>',
    "knob": '<path d="M4 7h10M18 7h2M4 17h4M12 17h8"/><circle cx="16" cy="7" r="2"/><circle cx="10" cy="17" r="2"/>',
    "import": '<path d="M12 3v12M7 10l5 5 5-5"/><path d="M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2"/>',
    "library": '<rect x="3" y="4" width="4" height="16" rx="1"/><rect x="9" y="4" width="4" height="16" rx="1"/><path d="M15.5 5.2l3.9-1 3.6 14.6-3.9 1z"/>',
}

NAMES = tuple(sorted(_PATHS))


def svg(name: str, color: str, stroke: float = 1.6) -> str:
    fill = color if name == "play" else "none"
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="{fill}" stroke="{color}" '
            f'stroke-width="{stroke}" stroke-linecap="round" stroke-linejoin="round">{_PATHS[name]}</svg>')


def pixmap(name: str, color: str, size: int = 20, ratio: float = 2.0) -> QPixmap:
    pm = QPixmap(int(size * ratio), int(size * ratio))
    pm.fill(Qt.transparent)
    renderer = QSvgRenderer(QByteArray(svg(name, color).encode()))
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    renderer.render(p, QRectF(0, 0, pm.width(), pm.height()))
    p.end()
    pm.setDevicePixelRatio(ratio)
    return pm


def icon(name: str, color: str, active: str | None = None, size: int = 20) -> QIcon:
    """An icon in ``color``; ``active`` (if given) is used when the button is checked."""
    ic = QIcon()
    ic.addPixmap(pixmap(name, color, size), QIcon.Normal, QIcon.Off)
    ic.addPixmap(pixmap(name, active or color, size), QIcon.Normal, QIcon.On)
    return ic


def file(name: str, color: str) -> str:
    """The icon written to a cache file (Qt style sheets can only load images from files). Returns its path."""
    import tempfile
    from pathlib import Path

    folder = Path(tempfile.gettempdir()) / "titanium-icons"
    folder.mkdir(exist_ok=True)
    path = folder / f"{name}-{color.lstrip('#')}.svg"
    if not path.exists():
        path.write_text(svg(name, color, 2.0), encoding="utf-8")
    return path.as_posix()
