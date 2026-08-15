"""Deterministically export the approved Neko family brand assets.

The script only writes inside docs/assets/brand/neko-family-v1. It never
updates shipping application icons.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps


ROOT = Path(__file__).resolve().parents[1]
BOARD = ROOT / "source" / "neko-family-approved-board-v5.png"
MASTER = ROOT / "mascot" / "neko-peek-master.png"
CONCEPTS = ROOT / "concepts"
PNG_DIR = ROOT / "logo" / "png"
PREVIEWS = ROOT / "previews"
MANIFEST = ROOT / "manifest.json"

ICON_SIZES = (16, 20, 24, 32, 48, 64, 128, 180, 192, 256, 512, 1024)


def _ensure_inputs() -> None:
    missing = [str(path) for path in (BOARD, MASTER) if not path.is_file()]
    if missing:
        raise SystemExit("Missing required source files: " + ", ".join(missing))
    CONCEPTS.mkdir(parents=True, exist_ok=True)
    PNG_DIR.mkdir(parents=True, exist_ok=True)
    PREVIEWS.mkdir(parents=True, exist_ok=True)


def _split_approved_board() -> None:
    with Image.open(BOARD) as image:
        image = image.convert("RGB")
        half_w = image.width // 2
        half_h = image.height // 2
        crops = {
            "neko-peek-concept.png": (0, 0, half_w, half_h),
            "neko-mochi-concept.png": (half_w, 0, image.width, half_h),
            "neko-nap-concept.png": (0, half_h, half_w, image.height),
            "neko-tilt-concept.png": (half_w, half_h, image.width, image.height),
        }
        for name, box in crops.items():
            image.crop(box).save(CONCEPTS / name, optimize=True)


def _vertical_gradient(size: int, top: tuple[int, int, int], bottom: tuple[int, int, int]) -> Image.Image:
    image = Image.new("RGB", (size, size), top)
    draw = ImageDraw.Draw(image)
    for y in range(size):
        t = y / max(size - 1, 1)
        color = tuple(round(a + (b - a) * t) for a, b in zip(top, bottom))
        draw.line((0, y, size, y), fill=color)
    return image.convert("RGBA")


def _trim_and_fit(image: Image.Image, target: tuple[int, int]) -> Image.Image:
    rgba = image.convert("RGBA")
    bbox = rgba.getchannel("A").getbbox()
    if bbox is None:
        raise ValueError("Neko Peek master has no visible pixels")
    crop = rgba.crop(bbox)
    crop.thumbnail(target, Image.Resampling.LANCZOS)
    return crop


def _render_app_icon() -> Image.Image:
    size = 1024
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))

    shadow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle(
        (44, 58, 980, 994), radius=226, fill=(30, 29, 29, 72)
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(28))
    canvas.alpha_composite(shadow)

    tile_mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(tile_mask).rounded_rectangle((32, 32, 992, 992), radius=226, fill=255)
    tile = _vertical_gradient(size, (238, 235, 230), (174, 171, 171))

    highlight = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(highlight).ellipse((92, 30, 790, 650), fill=(255, 255, 255, 74))
    highlight = highlight.filter(ImageFilter.GaussianBlur(95))
    tile.alpha_composite(highlight)
    tile.putalpha(tile_mask)
    canvas.alpha_composite(tile)

    border = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(border).rounded_rectangle(
        (33, 33, 991, 991), radius=225, outline=(42, 41, 40, 34), width=3
    )
    canvas.alpha_composite(border)

    with Image.open(MASTER) as source:
        mascot = _trim_and_fit(source, (810, 735))

    mascot_shadow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    shadow_shape = Image.new("RGBA", mascot.size, (20, 19, 19, 0))
    shadow_shape.putalpha(mascot.getchannel("A"))
    x = (size - mascot.width) // 2
    y = (size - mascot.height) // 2 + 28
    mascot_shadow.alpha_composite(shadow_shape, (x, y + 22))
    mascot_shadow = mascot_shadow.filter(ImageFilter.GaussianBlur(18))
    canvas.alpha_composite(mascot_shadow)
    canvas.alpha_composite(mascot, (x, y))
    return canvas


def _render_preview(background: tuple[int, int, int], name: str) -> None:
    canvas = Image.new("RGBA", (1200, 900), (*background, 255))
    with Image.open(MASTER) as source:
        mascot = _trim_and_fit(source, (800, 680))
    x = (canvas.width - mascot.width) // 2
    y = (canvas.height - mascot.height) // 2

    shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    shadow_shape = Image.new("RGBA", mascot.size, (18, 17, 17, 0))
    shadow_shape.putalpha(mascot.getchannel("A").point(lambda alpha: round(alpha * 0.30)))
    shadow.alpha_composite(shadow_shape, (x, y + 26))
    shadow = shadow.filter(ImageFilter.GaussianBlur(24))
    canvas.alpha_composite(shadow)
    canvas.alpha_composite(mascot, (x, y))
    canvas.convert("RGB").save(PREVIEWS / name, optimize=True)


def _write_icons() -> None:
    icon = _render_app_icon()
    for size in ICON_SIZES:
        resized = icon.resize((size, size), Image.Resampling.LANCZOS)
        resized.save(PNG_DIR / f"neko-peek-icon-{size}.png", optimize=True)

    icon.save(PNG_DIR / "neko-peek-app-icon-master.png", optimize=True)
    icon.save(
        ROOT / "logo" / "neko-peek.ico",
        format="ICO",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )

    _render_preview((235, 232, 227), "neko-peek-on-light.png")
    _render_preview((35, 35, 36), "neko-peek-on-dark.png")
    _render_small_size_strip()
    _render_brand_overview()


def _render_small_size_strip() -> None:
    scale = 4
    sizes = (16, 20, 24, 32, 48, 64)
    cell_width = 300
    strip = Image.new("RGB", (cell_width * len(sizes), 700), (238, 235, 231))
    draw = ImageDraw.Draw(strip)
    draw.rectangle((0, 350, strip.width, strip.height), fill=(36, 35, 36))

    for index, size in enumerate(sizes):
        with Image.open(PNG_DIR / f"neko-peek-icon-{size}.png") as source:
            icon = source.convert("RGBA")
        display = icon.resize((size * scale, size * scale), Image.Resampling.NEAREST)
        x = index * cell_width + (cell_width - display.width) // 2
        top_y = 160 - display.height // 2
        bottom_y = 510 - display.height // 2
        strip.paste(display, (x, top_y), display)
        strip.paste(display, (x, bottom_y), display)
        label_x = index * cell_width + cell_width // 2 - 6
        draw.text((label_x, 310), str(size), fill=(67, 65, 64))
        draw.text((label_x, 660), str(size), fill=(229, 226, 222))

    strip.save(PREVIEWS / "neko-peek-small-size-strip.png", optimize=True)


def _font(size: int, semibold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        Path("C:/Windows/Fonts/seguisb.ttf") if semibold else Path("C:/Windows/Fonts/segoeui.ttf"),
        Path("C:/Windows/Fonts/arialbd.ttf") if semibold else Path("C:/Windows/Fonts/arial.ttf"),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


def _render_brand_overview() -> None:
    canvas = Image.new("RGB", (1800, 1200), (28, 28, 29))
    draw = ImageDraw.Draw(canvas)
    title_font = _font(54, semibold=True)
    section_font = _font(24, semibold=True)
    body_font = _font(23)
    small_font = _font(18)

    draw.text((52, 40), "Wiii × Neko", font=title_font, fill=(247, 243, 235))
    draw.text((52, 103), "One companion. Four poses.", font=body_font, fill=(170, 167, 166))

    hero_box = (48, 160, 700, 1152)
    family_box = (728, 160, 1752, 738)
    system_box = (728, 766, 1752, 1152)
    draw.rounded_rectangle(hero_box, radius=30, fill=(231, 227, 222))
    draw.rounded_rectangle(family_box, radius=30, fill=(239, 236, 231))
    draw.rounded_rectangle(system_box, radius=30, fill=(37, 37, 38))

    with Image.open(PNG_DIR / "neko-peek-app-icon-master.png") as source:
        icon = source.convert("RGBA").resize((560, 560), Image.Resampling.LANCZOS)
    canvas.paste(icon, (94, 218), icon)
    draw.text((88, 815), "PRIMARY MARK", font=small_font, fill=(101, 98, 97))
    draw.text((88, 852), "NEKO PEEK", font=_font(46, semibold=True), fill=(42, 41, 40))
    draw.text((88, 922), "Present · listening · ready", font=body_font, fill=(91, 88, 87))
    draw.line((88, 980, 660, 980), fill=(190, 185, 181), width=2)
    draw.text((88, 1015), "Warm. Curious. Capable.", font=_font(30), fill=(42, 41, 40))

    draw.text((772, 202), "ONE NEKO / FOUR POSES", font=section_font, fill=(42, 41, 40))
    roles = [
        ("PEEK", "ready"),
        ("MOCHI", "complete"),
        ("NAP", "idle"),
        ("TILT", "thinking"),
    ]
    for index, (pose, state) in enumerate(roles):
        y = 280 + index * 68
        draw.text((772, y), pose, font=section_font, fill=(42, 41, 40))
        draw.text((910, y + 3), state, font=body_font, fill=(118, 114, 112))
    with Image.open(BOARD) as source:
        board = ImageOps.fit(source.convert("RGB"), (520, 520), method=Image.Resampling.LANCZOS)
    canvas.paste(board, (1190, 190))

    draw.text((772, 808), "PALETTE", font=section_font, fill=(238, 234, 228))
    swatches = [
        ("MILK", (245, 240, 230)),
        ("COCOA", (42, 41, 40)),
        ("LIFT", (69, 66, 65)),
        ("FOG", (169, 166, 166)),
        ("SKY", (187, 221, 242)),
    ]
    for index, (label, color) in enumerate(swatches):
        x = 772 + index * 126
        draw.rounded_rectangle((x, 866, x + 94, 960), radius=18, fill=color)
        draw.text((x, 978), label, font=small_font, fill=(185, 181, 177))

    draw.text((772, 1044), "PEEK IS THE LOGO. THE OTHER POSES ARE BEHAVIOR.", font=section_font, fill=(245, 240, 230))
    draw.text((772, 1090), "No mouth · no fur · no sad/error face · state always has text", font=body_font, fill=(164, 160, 157))

    canvas.save(PREVIEWS / "neko-family-overview.png", optimize=True)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_manifest() -> None:
    assets = []
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file() or path == MANIFEST or "__pycache__" in path.parts:
            continue
        assets.append(
            {
                "path": path.relative_to(ROOT).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )

    payload = {
        "schema_version": "wiii.neko.brand.v1",
        "status": "approved_visual_direction",
        "primary_mark": "Neko Peek",
        "supporting_poses": ["Neko Mochi", "Neko Nap", "Neko Tilt"],
        "generated_with": "OpenAI built-in imagegen plus deterministic Pillow export",
        "assets": assets,
    }
    MANIFEST.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    _ensure_inputs()
    _split_approved_board()
    _write_icons()
    _write_manifest()
    print(f"Exported Neko family assets to {ROOT}")


if __name__ == "__main__":
    main()
