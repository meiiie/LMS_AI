"""Validate the canonical Neko family asset package."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from xml.etree import ElementTree

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
PNG_DIR = ROOT / "logo" / "png"
EXPECTED_SIZES = (16, 20, 24, 32, 48, 64, 128, 180, 192, 256, 512, 1024)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _verify_master() -> None:
    path = ROOT / "mascot" / "neko-peek-master.png"
    with Image.open(path) as image:
        rgba = image.convert("RGBA")
        _require(rgba.width >= 1024 and rgba.height >= 1024, "master must be at least 1024 px")
        alpha = rgba.getchannel("A")
        _require(alpha.getbbox() is not None, "master alpha is empty")
        transparent = sum(1 for value in alpha.getdata() if value == 0)
        coverage = 1 - transparent / (rgba.width * rgba.height)
        _require(0.20 < coverage < 0.75, f"unexpected mascot coverage: {coverage:.3f}")
        corners = [rgba.getpixel(point)[3] for point in ((0, 0), (rgba.width - 1, 0), (0, rgba.height - 1), (rgba.width - 1, rgba.height - 1))]
        _require(corners == [0, 0, 0, 0], f"master corners are not transparent: {corners}")

        visible = [pixel for pixel in rgba.getdata() if pixel[3] > 32]
        green_fringe = sum(1 for red, green, blue, _ in visible if green > red + 70 and green > blue + 70)
        _require(green_fringe / max(len(visible), 1) < 0.0001, "green chroma fringe detected")


def _verify_icons() -> None:
    for size in EXPECTED_SIZES:
        path = PNG_DIR / f"neko-peek-icon-{size}.png"
        with Image.open(path) as image:
            _require(image.size == (size, size), f"wrong dimensions for {path.name}: {image.size}")
            _require(image.mode in {"RGBA", "LA", "P"}, f"{path.name} must preserve alpha")

    ico_path = ROOT / "logo" / "neko-peek.ico"
    with Image.open(ico_path) as image:
        sizes = image.ico.sizes()
    required = {(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)}
    _require(required.issubset(sizes), f"ICO missing frames: {sorted(required - sizes)}")


def _verify_concepts() -> None:
    paths = [
        ROOT / "concepts" / "neko-peek-concept.png",
        ROOT / "concepts" / "neko-mochi-concept.png",
        ROOT / "concepts" / "neko-nap-concept.png",
        ROOT / "concepts" / "neko-tilt-concept.png",
    ]
    dimensions = set()
    for path in paths:
        with Image.open(path) as image:
            dimensions.add(image.size)
    _require(len(dimensions) == 1, f"concept crops differ in size: {sorted(dimensions)}")


def _verify_svg() -> None:
    for name in (
        "neko-peek-mark.svg",
        "neko-peek-mark-on-dark.svg",
        "neko-peek-mark-mono.svg",
        "neko-peek-wordmark.svg",
    ):
        path = ROOT / "logo" / name
        root = ElementTree.parse(path).getroot()
        _require(root.tag.endswith("svg"), f"{name} root is not SVG")
        _require("viewBox" in root.attrib, f"{name} has no viewBox")


def _verify_manifest() -> int:
    manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    _require(manifest["schema_version"] == "wiii.neko.brand.v1", "unexpected manifest schema")
    for asset in manifest["assets"]:
        path = ROOT / asset["path"]
        _require(path.is_file(), f"manifest asset missing: {asset['path']}")
        _require(path.stat().st_size == asset["bytes"], f"size mismatch: {asset['path']}")
        _require(_sha256(path) == asset["sha256"], f"hash mismatch: {asset['path']}")
    return len(manifest["assets"])


def main() -> None:
    _verify_master()
    _verify_icons()
    _verify_concepts()
    _verify_svg()
    asset_count = _verify_manifest()
    print(f"Neko family verification passed: {asset_count} manifested assets")


if __name__ == "__main__":
    main()
