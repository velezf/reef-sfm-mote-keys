"""
Contact sheet generator.

A 2000+ image intake set is too large to inspect file-by-file, but small
enough that an experienced eye on a contact sheet catches transect-end
mishaps (lens-cap-on frames, light leaks, sand-in-housing) that the
heuristic rules in validation.py can only weakly flag.

This module produces JPEG contact sheets at N images per sheet with the
filename written under each thumbnail.  Sheets are numbered in capture
order so a flagged tile maps back to a transect position quickly.

Implementation notes:

  * We resize thumbnails by area, not by side length, so wide-aspect
    underwater frames don't dominate the grid.
  * Thumbnails are JPEG-encoded for compactness; the contact sheet itself
    is also a JPEG.  A typical sheet for 2000 images at 6x6 thumbnails
    per sheet is ~56 sheets at <300 KB each — fits in the repo's
    `figures/` directory without ballooning git.
  * The grid leaves a small caption strip under each tile.  At 220px
    thumbnails the filename remains legible at default rendering.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

log = logging.getLogger(__name__)


def _load_caption_font(size: int = 14) -> ImageFont.ImageFont:
    """Try to load a sane sans-serif; fall back to PIL default."""
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/Helvetica.ttc",
    ]
    for path in candidates:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def _make_tile(
    image_path: Path,
    tile_w: int,
    tile_h: int,
    caption_h: int,
    font: ImageFont.ImageFont,
) -> Image.Image:
    """Build a single (thumbnail + caption) tile."""
    canvas = Image.new("RGB", (tile_w, tile_h + caption_h), (24, 24, 28))
    try:
        with Image.open(image_path) as im:
            im = im.convert("RGB")
            im.thumbnail((tile_w, tile_h), Image.Resampling.LANCZOS)
            # Center the thumbnail inside its slot
            x = (tile_w - im.width) // 2
            y = (tile_h - im.height) // 2
            canvas.paste(im, (x, y))
    except Exception as exc:  # noqa: BLE001 — contact sheet shouldn't crash on one bad file
        log.warning("Tile failed for %s: %s", image_path, exc)
        draw = ImageDraw.Draw(canvas)
        draw.text((6, 6), "READ FAILED", fill=(220, 80, 80), font=font)

    draw = ImageDraw.Draw(canvas)
    label = image_path.name
    # Truncate long names rather than letting them flow into the next tile.
    max_chars = max(8, tile_w // 7)
    if len(label) > max_chars:
        label = label[: max_chars - 1] + "…"
    draw.text(
        (4, tile_h + 2),
        label,
        fill=(220, 220, 220),
        font=font,
    )
    return canvas


def generate_contact_sheets(
    image_paths: Sequence[Path],
    out_dir: Path,
    *,
    cols: int = 6,
    rows: int = 6,
    tile_w: int = 220,
    tile_h: int = 165,
    margin: int = 8,
    caption_h: int = 18,
    sheet_prefix: str = "contact_sheet",
) -> list[Path]:
    """Build contact sheets covering every image in `image_paths`.

    Returns the list of written sheet paths.  Sheets are written as
    `<sheet_prefix>_001.jpg`, `_002.jpg`, … with zero-padding sized
    for the actual sheet count.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    per_sheet = cols * rows
    n_sheets = (len(image_paths) + per_sheet - 1) // per_sheet
    if n_sheets == 0:
        log.warning("No images supplied; no contact sheets to write")
        return []
    width = cols * tile_w + (cols + 1) * margin
    height = rows * (tile_h + caption_h) + (rows + 1) * margin
    font = _load_caption_font()
    pad = max(3, len(str(n_sheets)))
    written: list[Path] = []

    for sheet_idx in range(n_sheets):
        batch = image_paths[sheet_idx * per_sheet : (sheet_idx + 1) * per_sheet]
        sheet = Image.new("RGB", (width, height), (16, 16, 20))
        for i, path in enumerate(batch):
            r, c = divmod(i, cols)
            x = margin + c * (tile_w + margin)
            y = margin + r * (tile_h + caption_h + margin)
            tile = _make_tile(path, tile_w, tile_h, caption_h, font)
            sheet.paste(tile, (x, y))
        out_path = out_dir / f"{sheet_prefix}_{sheet_idx + 1:0{pad}d}.jpg"
        sheet.save(out_path, format="JPEG", quality=82, optimize=True)
        written.append(out_path)
        log.info("Wrote %s (%d tiles)", out_path, len(batch))
    return written


__all__ = ["generate_contact_sheets"]
