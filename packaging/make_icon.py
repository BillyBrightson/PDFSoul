"""Draw the PDFSoul icon: packaging/pdfsoul.png (512 px) and packaging/pdfsoul.ico.

Run: uv run python packaging/make_icon.py
"""

from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).parent
SIZE = 1024


def _gradient(size: int, top: tuple[int, int, int], bottom: tuple[int, int, int]) -> Image.Image:
    img = Image.new("RGB", (size, size))
    draw = ImageDraw.Draw(img)
    for y in range(size):
        t = y / (size - 1)
        draw.line([(0, y), (size, y)], fill=tuple(round(a + (b - a) * t)
                                                 for a, b in zip(top, bottom, strict=True)))
    return img


def draw() -> Image.Image:
    s = SIZE
    background = _gradient(s, (138, 107, 255), (88, 52, 230))
    mask = Image.new("L", (s, s), 0)
    ImageDraw.Draw(mask).rounded_rectangle([40, 40, s - 40, s - 40], radius=220, fill=255)
    icon = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    icon.paste(background, (0, 0), mask)

    d = ImageDraw.Draw(icon)
    # Page with a folded corner.
    left, top, right, bottom, fold = 290, 210, 734, 814, 150
    d.polygon([(left, top), (right - fold, top), (right, top + fold), (right, bottom),
               (left, bottom)], fill=(255, 255, 255, 255))
    d.polygon([(right - fold, top), (right - fold, top + fold), (right, top + fold)],
              fill=(214, 204, 255, 255))
    # Text lines.
    for i, width in enumerate((300, 340, 260)):
        y = 470 + i * 70
        d.rounded_rectangle([left + 60, y, left + 60 + width, y + 26], radius=13,
                            fill=(196, 184, 255, 255))
    # The "soul": a four-point sparkle near the top of the page.
    cx, cy, r, w = left + 120, top + 150, 82, 22
    d.polygon([(cx, cy - r), (cx + w, cy - w), (cx + r, cy), (cx + w, cy + w), (cx, cy + r),
               (cx - w, cy + w), (cx - r, cy), (cx - w, cy - w)], fill=(109, 74, 255, 255))
    return icon


def main() -> None:
    icon = draw()
    icon.resize((512, 512), Image.Resampling.LANCZOS).save(HERE / "pdfsoul.png")
    icon.save(HERE / "pdfsoul.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64),
                                          (128, 128), (256, 256)])
    icon.save(HERE / "pdfsoul.icns")  # macOS app icon; Pillow writes every size up to 1024
    print("Wrote", HERE / "pdfsoul.png", HERE / "pdfsoul.ico", "and", HERE / "pdfsoul.icns")


if __name__ == "__main__":
    main()
