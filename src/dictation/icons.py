from __future__ import annotations

from PIL import Image, ImageDraw

COLORS = {
    "idle": (37, 99, 235, 255),
    "recording": (220, 38, 38, 255),
    "transcribing": (217, 119, 6, 255),
    "downloading": (124, 58, 237, 255),
    "loading": (79, 70, 229, 255),
    "error": (107, 114, 128, 255),
    "muted": (156, 163, 175, 255),
}


def tray_icon(state: str, level: float = 0.0) -> Image.Image:
    color = COLORS.get(state, COLORS["idle"])
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((6, 6, 58, 58), fill=color)
    if state == "recording":
        t = max(0.0, min(1.0, float(level)))
        inset = 4 + int((1.0 - t) * 10)
        draw.ellipse((inset, inset, 64 - inset, 64 - inset), outline=(255, 255, 255, 230), width=3)
    draw.ellipse((22, 14, 42, 38), fill=(255, 255, 255, 230))
    draw.rectangle((30, 36, 34, 48), fill=(255, 255, 255, 230))
    draw.rectangle((24, 46, 40, 50), fill=(255, 255, 255, 230))
    return img
