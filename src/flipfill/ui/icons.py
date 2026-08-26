from __future__ import annotations

from collections.abc import Callable

from PIL import Image, ImageDraw, ImageTk

_SCALE = 4


def _new(size: int) -> tuple[Image.Image, ImageDraw.ImageDraw, int]:
    px = size * _SCALE
    image = Image.new("RGBA", (px, px), (0, 0, 0, 0))
    return image, ImageDraw.Draw(image), px


def _finish(image: Image.Image, size: int) -> Image.Image:
    return image.resize((size, size), Image.LANCZOS)


def _width(px: int) -> int:
    return max(3, round(px / 11))


def _draw_new(draw: ImageDraw.ImageDraw, px: int, color: str, w: int) -> None:
    m = px * 0.24
    fold = px * 0.24
    draw.rounded_rectangle((m, px * 0.08, px - m, px - px * 0.08), radius=px * 0.05, outline=color, width=w)
    draw.line((px - m - fold, px * 0.08, px - m - fold, px * 0.08 + fold), fill=color, width=w)
    draw.line((px - m - fold, px * 0.08 + fold, px - m, px * 0.08 + fold), fill=color, width=w)
    cx = px / 2
    draw.line((cx, px * 0.5, cx, px * 0.78), fill=color, width=w)
    draw.line((cx - px * 0.14, px * 0.64, cx + px * 0.14, px * 0.64), fill=color, width=w)


def _draw_open(draw: ImageDraw.ImageDraw, px: int, color: str, w: int) -> None:
    top = px * 0.32
    draw.line((px * 0.12, top, px * 0.4, px * 0.16), fill=color, width=w)
    draw.line((px * 0.4, px * 0.16, px * 0.68, px * 0.16), fill=color, width=w)
    draw.line((px * 0.68, px * 0.16, px * 0.78, top), fill=color, width=w)
    draw.rounded_rectangle(
        (px * 0.1, top, px * 0.9, px * 0.84), radius=px * 0.06, outline=color, width=w
    )
    draw.line((px * 0.1, px * 0.46, px * 0.9, px * 0.46), fill=color, width=max(2, w - 1))


def _draw_save(draw: ImageDraw.ImageDraw, px: int, color: str, w: int) -> None:
    m = px * 0.14
    draw.rounded_rectangle((m, m, px - m, px - m), radius=px * 0.08, outline=color, width=w)
    draw.rectangle((px * 0.32, m, px * 0.68, px * 0.34), outline=color, width=w)
    draw.rounded_rectangle(
        (px * 0.26, px * 0.54, px * 0.74, px - m), radius=px * 0.04, outline=color, width=w
    )


def _draw_import(draw: ImageDraw.ImageDraw, px: int, color: str, w: int) -> None:
    cx = px / 2
    draw.line((cx, px * 0.14, cx, px * 0.62), fill=color, width=w)
    draw.line((cx - px * 0.2, px * 0.42, cx, px * 0.64), fill=color, width=w)
    draw.line((cx + px * 0.2, px * 0.42, cx, px * 0.64), fill=color, width=w)
    draw.line((px * 0.16, px * 0.82, px * 0.84, px * 0.82), fill=color, width=w)


def _draw_export(draw: ImageDraw.ImageDraw, px: int, color: str, w: int) -> None:
    cx = px / 2
    draw.line((cx, px * 0.7, cx, px * 0.2), fill=color, width=w)
    draw.line((cx - px * 0.2, px * 0.4, cx, px * 0.18), fill=color, width=w)
    draw.line((cx + px * 0.2, px * 0.4, cx, px * 0.18), fill=color, width=w)
    draw.line((px * 0.16, px * 0.82, px * 0.84, px * 0.82), fill=color, width=w)


def _draw_box_add(draw: ImageDraw.ImageDraw, px: int, color: str, w: int, accent: str | None) -> None:
    a = accent or color
    top = px * 0.16
    mid = px * 0.4
    bot = px * 0.7
    left = px * 0.14
    right = px * 0.62
    cx = (left + right) / 2
    draw.line((left, mid, cx, top), fill=color, width=w)
    draw.line((cx, top, right, mid), fill=color, width=w)
    draw.line((left, mid, left, bot), fill=color, width=w)
    draw.line((right, mid, right, bot), fill=color, width=w)
    draw.line((left, bot, cx, top + (bot - top) * 0.42 + (mid - top)), fill=color, width=w)
    draw.line((cx, mid + (bot - mid) * 0.02, right, bot), fill=color, width=w)
    draw.line((cx, mid, cx, bot), fill=color, width=w)
    badge_r = px * 0.2
    bx, by = px * 0.78, px * 0.78
    draw.ellipse((bx - badge_r, by - badge_r, bx + badge_r, by + badge_r), fill=a)
    plus_w = max(2, w - 1)
    draw.line((bx - badge_r * 0.5, by, bx + badge_r * 0.5, by), fill="#0b0d10", width=plus_w)
    draw.line((bx, by - badge_r * 0.5, bx, by + badge_r * 0.5), fill="#0b0d10", width=plus_w)


def _draw_fit(draw: ImageDraw.ImageDraw, px: int, color: str, w: int) -> None:
    arm = px * 0.22
    m = px * 0.14
    corners = [(m, m), (px - m, m), (m, px - m), (px - m, px - m)]
    for x, y in corners:
        dx = arm if x == m else -arm
        dy = arm if y == m else -arm
        draw.line((x, y, x + dx, y), fill=color, width=w)
        draw.line((x, y, x, y + dy), fill=color, width=w)


def _draw_generate(draw: ImageDraw.ImageDraw, px: int, color: str, w: int) -> None:
    draw.polygon(
        [(px * 0.28, px * 0.16), (px * 0.28, px * 0.84), (px * 0.82, px * 0.5)],
        fill=color,
    )


def _draw_validate(draw: ImageDraw.ImageDraw, px: int, color: str, w: int) -> None:
    draw.ellipse((px * 0.12, px * 0.12, px * 0.88, px * 0.88), outline=color, width=w)
    draw.line((px * 0.32, px * 0.52, px * 0.46, px * 0.68), fill=color, width=w)
    draw.line((px * 0.46, px * 0.68, px * 0.72, px * 0.34), fill=color, width=w)


def _draw_duplicate(draw: ImageDraw.ImageDraw, px: int, color: str, w: int) -> None:
    draw.rounded_rectangle(
        (px * 0.12, px * 0.3, px * 0.62, px * 0.8), radius=px * 0.06, outline=color, width=w
    )
    draw.rounded_rectangle(
        (px * 0.38, px * 0.14, px * 0.88, px * 0.64), radius=px * 0.06, outline=color, width=w
    )


def _draw_delete(draw: ImageDraw.ImageDraw, px: int, color: str, w: int) -> None:
    draw.line((px * 0.2, px * 0.28, px * 0.8, px * 0.28), fill=color, width=w)
    draw.line((px * 0.38, px * 0.28, px * 0.4, px * 0.16), fill=color, width=w)
    draw.line((px * 0.4, px * 0.16, px * 0.6, px * 0.16), fill=color, width=w)
    draw.line((px * 0.6, px * 0.16, px * 0.62, px * 0.28), fill=color, width=w)
    draw.rounded_rectangle(
        (px * 0.28, px * 0.28, px * 0.72, px * 0.86), radius=px * 0.04, outline=color, width=w
    )
    draw.line((px * 0.42, px * 0.4, px * 0.42, px * 0.74), fill=color, width=max(2, w - 1))
    draw.line((px * 0.58, px * 0.4, px * 0.58, px * 0.74), fill=color, width=max(2, w - 1))


def _draw_eye(draw: ImageDraw.ImageDraw, px: int, color: str, w: int) -> None:
    draw.arc((px * 0.08, px * 0.16, px * 0.92, px * 0.86), 200, 340, fill=color, width=w)
    draw.arc((px * 0.08, px * 0.14, px * 0.92, px * 0.84), 20, 160, fill=color, width=w)
    r = px * 0.13
    draw.ellipse((px / 2 - r, px * 0.5 - r, px / 2 + r, px * 0.5 + r), outline=color, width=w)


def _cube_axes(draw: ImageDraw.ImageDraw, px: int, color: str, w: int, faces: tuple[str, ...], fill: str) -> None:
    cx, cy = px * 0.5, px * 0.56
    s = px * 0.32
    top = (cx, cy - s)
    left = (cx - s * 0.87, cy - s * 0.5)
    right = (cx + s * 0.87, cy - s * 0.5)
    bottom = (cx, cy + s)
    bl = (cx - s * 0.87, cy + s * 0.5)
    br = (cx + s * 0.87, cy + s * 0.5)
    if "top" in faces:
        draw.polygon([top, left, (cx, cy), right], fill=fill)
    if "left" in faces:
        draw.polygon([left, bl, bottom, (cx, cy)], fill=fill)
    if "right" in faces:
        draw.polygon([right, (cx, cy), bottom, br], fill=fill)
    for a, b in ((top, left), (top, right), (left, bl), (right, br), (bl, bottom), (br, bottom), (left, (cx, cy)), (right, (cx, cy)), ((cx, cy), bottom)):
        draw.line((*a, *b), fill=color, width=max(2, w - 1))


def _draw_view_iso(draw: ImageDraw.ImageDraw, px: int, color: str, w: int, accent: str) -> None:
    _cube_axes(draw, px, color, w, ("top", "left", "right"), accent)


def _draw_view_top(draw: ImageDraw.ImageDraw, px: int, color: str, w: int, accent: str) -> None:
    _cube_axes(draw, px, color, w, ("top",), accent)


def _draw_view_front(draw: ImageDraw.ImageDraw, px: int, color: str, w: int, accent: str) -> None:
    _cube_axes(draw, px, color, w, ("left",), accent)


def _draw_view_side(draw: ImageDraw.ImageDraw, px: int, color: str, w: int, accent: str) -> None:
    _cube_axes(draw, px, color, w, ("right",), accent)


def _draw_chevron_up(draw: ImageDraw.ImageDraw, px: int, color: str, w: int) -> None:
    draw.line((px * 0.24, px * 0.62, px * 0.5, px * 0.36), fill=color, width=w)
    draw.line((px * 0.5, px * 0.36, px * 0.76, px * 0.62), fill=color, width=w)


def _draw_chevron_down(draw: ImageDraw.ImageDraw, px: int, color: str, w: int) -> None:
    draw.line((px * 0.24, px * 0.38, px * 0.5, px * 0.64), fill=color, width=w)
    draw.line((px * 0.5, px * 0.64, px * 0.76, px * 0.38), fill=color, width=w)


_SIMPLE: dict[str, Callable[[ImageDraw.ImageDraw, int, str, int], None]] = {
    "new": _draw_new,
    "open": _draw_open,
    "save": _draw_save,
    "import": _draw_import,
    "export": _draw_export,
    "fit": _draw_fit,
    "generate": _draw_generate,
    "validate": _draw_validate,
    "duplicate": _draw_duplicate,
    "delete": _draw_delete,
    "eye": _draw_eye,
    "chevron_up": _draw_chevron_up,
    "chevron_down": _draw_chevron_down,
}

_ACCENTED: dict[str, Callable[[ImageDraw.ImageDraw, int, str, int, str], None]] = {
    "box_add": _draw_box_add,
    "view_iso": _draw_view_iso,
    "view_top": _draw_view_top,
    "view_front": _draw_view_front,
    "view_side": _draw_view_side,
}


class IconStore:
    """Renders small flat-line icons with Pillow and caches them per (name, color, accent, size).

    Icons are vector-drawn at 4x and downsampled, so they stay crisp at any
    toolbar size without shipping bitmap assets.
    """

    def __init__(self) -> None:
        self._cache: dict[tuple, ImageTk.PhotoImage] = {}

    def get(self, name: str, color: str, size: int = 16, accent: str | None = None) -> ImageTk.PhotoImage:
        key = (name, color, accent, size)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        image, draw, px = _new(size)
        w = _width(px)
        if name in _ACCENTED:
            _ACCENTED[name](draw, px, color, w, accent or color)
        elif name in _SIMPLE:
            _SIMPLE[name](draw, px, color, w)
        else:
            raise KeyError(f"Unknown icon: {name}")
        photo = ImageTk.PhotoImage(_finish(image, size))
        self._cache[key] = photo
        return photo
