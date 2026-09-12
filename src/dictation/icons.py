from __future__ import annotations

from PIL import Image, ImageDraw

COLORS = {
    "idle": (37, 99, 235, 255),
    "recording": (220, 38, 38, 255),
    "transcribing": (217, 119, 6, 255),
    "downloading": (124, 58, 237, 255),
    "loading": (79, 70, 229, 255),
    "error": (107, 114, 128, 255),
}


def tray_icon(state: str) -> Image.Image:
    color = COLORS.get(state, COLORS["idle"])
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((6, 6, 58, 58), fill=color)
    draw.ellipse((22, 14, 42, 38), fill=(255, 255, 255, 230))
    draw.rectangle((30, 36, 34, 48), fill=(255, 255, 255, 230))
    draw.rectangle((24, 46, 40, 50), fill=(255, 255, 255, 230))
    return img
