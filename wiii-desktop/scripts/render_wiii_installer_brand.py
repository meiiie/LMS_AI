"""Render NSIS bitmaps from the canonical transparent Neko Peek mascot."""

from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter, ImageFont


ROOT = Path(__file__).resolve().parents[1]
MASCOT_PATH = ROOT / "public" / "wiii-mascot-full.png"
ICON_DIR = ROOT / "src-tauri" / "icons"
FONT_DIR = Path("C:/Windows/Fonts")

GRAPHITE = (42, 41, 40)
IVORY = (245, 240, 230)
COCOA_LIFT = (69, 66, 65)
SKY = (187, 221, 242)


def font(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT_DIR / name, size)


def cropped_mascot() -> Image.Image:
    mascot = Image.open(MASCOT_PATH).convert("RGBA")
    bounds = mascot.getchannel("A").getbbox()
    if bounds is None:
        raise RuntimeError("Mascot master has no visible pixels")
    return mascot.crop(bounds)


def contain(image: Image.Image, width: int, height: int) -> Image.Image:
    scale = min(width / image.width, height / image.height)
    return image.resize(
        (round(image.width * scale), round(image.height * scale)),
        Image.Resampling.LANCZOS,
    )


def paste_with_shadow(
    canvas: Image.Image,
    image: Image.Image,
    xy: tuple[int, int],
    blur: int,
    opacity: int,
) -> None:
    shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    alpha = image.getchannel("A").point(lambda value: value * opacity // 255)
    black = Image.new("RGBA", image.size, (0, 0, 0, 255))
    shadow.paste(black, (xy[0], xy[1] + max(1, blur // 2)), alpha)
    shadow = shadow.filter(ImageFilter.GaussianBlur(blur))
    canvas.alpha_composite(shadow)
    canvas.alpha_composite(image, xy)


def centered_x(draw: ImageDraw.ImageDraw, text: str, text_font: ImageFont.FreeTypeFont, width: int) -> int:
    box = draw.textbbox((0, 0), text, font=text_font)
    return (width - (box[2] - box[0])) // 2


def render_header(mascot: Image.Image) -> None:
    canvas = Image.new("RGBA", (150, 57), IVORY + (255,))
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((0, 55, 149, 56), fill=COCOA_LIFT + (255,))
    draw.rectangle((101, 55, 149, 56), fill=SKY + (255,))

    character = contain(mascot, 43, 48)
    paste_with_shadow(canvas, character, (6, 4), blur=3, opacity=70)

    draw.text((50, 10), "Wiii", font=font("seguisb.ttf", 13), fill=GRAPHITE)
    draw.text((51, 31), "THE WIII LAB", font=font("segoeui.ttf", 7), fill=(98, 96, 90))
    canvas.convert("RGB").save(ICON_DIR / "nsis-header.bmp")


def render_sidebar(mascot: Image.Image) -> None:
    width, height = 164, 314
    canvas = Image.new("RGBA", (width, height), GRAPHITE + (255,))
    glow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow)
    glow_draw.ellipse((7, -18, 157, 144), fill=SKY + (34,))
    canvas.alpha_composite(glow.filter(ImageFilter.GaussianBlur(30)))

    character = contain(mascot, 124, 130)
    paste_with_shadow(canvas, character, ((width - character.width) // 2, 19), blur=8, opacity=115)

    draw = ImageDraw.Draw(canvas)
    title_font = font("seguisb.ttf", 19)
    workbench_font = font("segoeui.ttf", 10)
    label_font = font("seguisb.ttf", 7)
    small_font = font("segoeui.ttf", 7)

    draw.text((centered_x(draw, "Wiii", title_font, width), 159), "Wiii", font=title_font, fill=IVORY)
    draw.text(
        (centered_x(draw, "WORKBENCH", workbench_font, width), 184),
        "WORKBENCH",
        font=workbench_font,
        fill=(208, 205, 196),
    )
    draw.rounded_rectangle((37, 211, 126, 213), radius=1, fill=COCOA_LIFT)
    draw.rounded_rectangle((96, 211, 126, 213), radius=1, fill=SKY)
    draw.text(
        (centered_x(draw, "DURABLE AI WORKSPACE", label_font, width), 226),
        "DURABLE AI WORKSPACE",
        font=label_font,
        fill=(171, 168, 160),
    )
    draw.text(
        (centered_x(draw, "THE WIII LAB", small_font, width), 271),
        "THE WIII LAB",
        font=small_font,
        fill=(126, 124, 118),
    )
    draw.text(
        (centered_x(draw, "VERSION 1.2.0", small_font, width), 289),
        "VERSION 1.2.0",
        font=small_font,
        fill=(92, 91, 87),
    )
    canvas.convert("RGB").save(ICON_DIR / "nsis-sidebar.bmp")


def main() -> None:
    mascot = cropped_mascot()
    render_header(mascot)
    render_sidebar(mascot)
    print("Rendered Wiii mascot NSIS header and sidebar")


if __name__ == "__main__":
    main()
