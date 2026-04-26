#!/usr/bin/env python3
"""
Render TMX room files to PNG images.

Usage:
    python tmx/scripts/render_tmx_rooms.py <tmx_directory>

Example:
    python tmx/scripts/render_tmx_rooms.py tmx/_in_progress/jsw

This script:
1. Finds all TMX files in the directory
2. Parses each TMX to get tile data and tileset references
3. Loads the tileset images
4. Renders each room to a PNG in a 'rooms' subdirectory
"""

import argparse
import io
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional
from PIL import Image


TILE_WIDTH = 8
TILE_HEIGHT = 8
ROOM_WIDTH = 32   # tiles
ROOM_HEIGHT = 16  # tiles


def parse_tsx(tsx_path: Path) -> tuple[str, int, int]:
    """Parse TSX file to get image source, tile count, and columns."""
    tree = ET.parse(tsx_path)
    root = tree.getroot()

    image = root.find('image')
    if image is None:
        # Collection-of-images tileset (per-tile images, e.g. guardians) — not renderable as a sheet
        return None

    source = image.get('source')
    columns = int(root.get('columns', 16))
    tilecount = int(root.get('tilecount', 0))

    return source, tilecount, columns


def _resolve_variant_image(base_image_path: Path, suffix: str,
                           tmx_dir: Path) -> Path:
    """Return a sibling tileset PNG named with `_<suffix>` if it exists.

    Custom maps can ship multiple tile resolutions side by side in the
    map folder (`tiles_solid.png` + `tiles_solid_2x.png` etc.). When a
    suffix is requested, prefer the variant either next to the original
    image (TSX folder) or directly in the TMX folder; fall back to the
    base path when no variant is on disk.
    """
    if not suffix:
        return base_image_path
    variant_name = f"{base_image_path.stem}_{suffix}{base_image_path.suffix}"
    sibling = base_image_path.with_name(variant_name)
    if sibling.exists():
        return sibling
    in_tmx_dir = tmx_dir / variant_name
    if in_tmx_dir.exists():
        return in_tmx_dir
    return base_image_path


def load_tilesets(tmx_path: Path, tileset_suffix: str = "") -> list:
    """Load all tilesets referenced by a TMX file.

    Each entry is `(firstgid, tilecount, columns, tile_w, tile_h,
    tileset_img)`. Tile dimensions come from the loaded image
    (`width // columns`, `height // rows`) so variant tilesets at a
    different native resolution (e.g. 2x at 16px) render correctly
    without a separate TSX.

    `tileset_suffix` (when non-empty) substitutes a sibling
    `<base>_<suffix>.png` for any TSX-referenced PNG when the variant
    exists on disk — this is what lets the preview honour the map's
    DefaultTileset.
    """
    tree = ET.parse(tmx_path)
    root = tree.getroot()
    tmx_dir = tmx_path.parent

    tilesets = []

    for tileset_elem in root.findall('tileset'):
        firstgid = int(tileset_elem.get('firstgid', 1))
        source = tileset_elem.get('source')

        if source:
            tsx_path = tmx_dir / source
            if not tsx_path.exists():
                print(f"  Warning: TSX not found: {tsx_path}")
                continue

            try:
                result = parse_tsx(tsx_path)
                if result is None:
                    continue
                image_source, tilecount, columns = result
                image_path = tsx_path.parent / image_source
            except Exception as e:
                print(f"  Warning: Error parsing {tsx_path}: {e}")
                continue
        else:
            image = tileset_elem.find('image')
            if image is None:
                continue
            image_path = tmx_dir / image.get('source')
            columns = int(tileset_elem.get('columns', 16))
            tilecount = int(tileset_elem.get('tilecount', 0))

        image_path = _resolve_variant_image(image_path, tileset_suffix, tmx_dir)

        if not image_path.exists():
            print(f"  Warning: Image not found: {image_path}")
            continue

        try:
            tileset_img = Image.open(image_path).convert('RGBA')
            tile_w = tileset_img.width // max(columns, 1)
            rows = max((tilecount + columns - 1) // columns, 1) if columns else 1
            tile_h = tileset_img.height // rows if rows else tile_w
            if tile_w <= 0 or tile_h <= 0:
                tile_w = tile_h = TILE_WIDTH
            tilesets.append((firstgid, tilecount, columns, tile_w, tile_h, tileset_img))
        except Exception as e:
            print(f"  Warning: Error loading {image_path}: {e}")
            continue

    tilesets.sort(key=lambda x: x[0])
    return tilesets


def get_tile_from_gid(gid: int, tilesets: list) -> Image.Image | None:
    """Get the tile image for a given GID."""
    if gid == 0:
        return None

    for i, (firstgid, tilecount, columns, tile_w, tile_h, tileset_img) in enumerate(tilesets):
        next_firstgid = tilesets[i + 1][0] if i + 1 < len(tilesets) else float('inf')

        if firstgid <= gid < next_firstgid:
            local_id = gid - firstgid
            tile_x = (local_id % columns) * tile_w
            tile_y = (local_id // columns) * tile_h

            if tile_x + tile_w <= tileset_img.width and tile_y + tile_h <= tileset_img.height:
                return tileset_img.crop((tile_x, tile_y, tile_x + tile_w, tile_y + tile_h))

    return None


def parse_tmx_tiles(tmx_path: Path) -> list[list[int]]:
    """Parse TMX file and return 16x32 grid of GIDs."""
    tree = ET.parse(tmx_path)
    root = tree.getroot()

    layer = root.find(".//layer[@name='Tiles']")
    if layer is None:
        layer = root.find(".//layer")

    if layer is None:
        raise ValueError(f"No layer found in {tmx_path}")

    data = layer.find('data')
    if data is None or data.text is None:
        raise ValueError(f"No tile data in {tmx_path}")

    width = int(layer.get('width', ROOM_WIDTH))

    # Parse CSV data — handle both single-line and multi-line formats
    csv_text = data.text.strip()
    all_gids = [int(g) for g in csv_text.replace('\n', ',').split(',') if g.strip()]

    # Chunk flat list into rows using the layer width
    rows = [all_gids[i:i + width] for i in range(0, len(all_gids), width)]

    return rows


def get_background_color(tmx_path: Path) -> tuple:
    """Get background color from TMX file."""
    tree = ET.parse(tmx_path)
    root = tree.getroot()

    bg_color = root.get('backgroundcolor', '#000000')

    # Parse hex color
    if bg_color.startswith('#'):
        bg_color = bg_color[1:]

    if len(bg_color) == 6:
        r = int(bg_color[0:2], 16)
        g = int(bg_color[2:4], 16)
        b = int(bg_color[4:6], 16)
        return (r, g, b, 255)

    return (0, 0, 0, 255)


def render_room_to_image(tmx_path: Path, tileset_suffix: str = "") -> Optional[Image.Image]:
    """Render a TMX room to a PIL Image. Returns None on error.

    Output dimensions follow the (first) loaded tileset's tile size:
    32x16 tiles × 8px = 256x128 for the base set, 32x16 × 16px = 512x256
    for a 2x variant, etc.
    """
    try:
        tilesets = load_tilesets(tmx_path, tileset_suffix=tileset_suffix)
        if not tilesets:
            print(f"  No tilesets loaded for {tmx_path.name}")
            return None

        tile_rows = parse_tmx_tiles(tmx_path)
        bg_color = get_background_color(tmx_path)

        # Pick the dominant tile dimensions from the first tile-bearing
        # tileset (in practice all variant tilesets in a single map are
        # the same scale; the first entry is the lowest firstgid which
        # is always one of the room tile sets).
        out_tile_w, out_tile_h = tilesets[0][3], tilesets[0][4]
        img_width = ROOM_WIDTH * out_tile_w
        img_height = ROOM_HEIGHT * out_tile_h
        img = Image.new('RGBA', (img_width, img_height), bg_color)

        for y, row in enumerate(tile_rows):
            for x, gid in enumerate(row):
                if gid == 0:
                    continue
                tile_img = get_tile_from_gid(gid, tilesets)
                if tile_img:
                    img.paste(tile_img, (x * out_tile_w, y * out_tile_h), tile_img)

        return img

    except Exception as e:
        print(f"  Error rendering {tmx_path.name}: {e}")
        return None


def render_room_to_png_bytes(tmx_path: Path, tileset_suffix: str = "") -> Optional[bytes]:
    """Render a TMX room to PNG bytes. Returns None on error."""
    img = render_room_to_image(tmx_path, tileset_suffix=tileset_suffix)
    if img is None:
        return None
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return buf.getvalue()


def render_room(tmx_path: Path, output_path: Path, tileset_suffix: str = "") -> bool:
    """Render a TMX room to PNG file."""
    img = render_room_to_image(tmx_path, tileset_suffix=tileset_suffix)
    if img is None:
        return False
    try:
        img.save(output_path)
        return True
    except Exception as e:
        print(f"  Error saving {output_path}: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description='Render TMX room files to PNG images')
    parser.add_argument('tmx_directory', type=Path, help='Directory containing TMX files')
    args = parser.parse_args()

    tmx_dir = args.tmx_directory

    if not tmx_dir.exists():
        print(f"Error: Directory not found: {tmx_dir}")
        return 1

    # Create output directory
    output_dir = tmx_dir / 'rooms'
    output_dir.mkdir(parents=True, exist_ok=True)

    # Find all TMX files
    tmx_files = sorted([p for p in tmx_dir.glob('*.tmx') if p.stem.isdigit()])

    if not tmx_files:
        print(f"No TMX files found in {tmx_dir}")
        return 1

    print(f"Found {len(tmx_files)} TMX files")
    print(f"Output directory: {output_dir}")
    print()

    success = 0
    failed = 0

    for tmx_path in tmx_files:
        room_num = tmx_path.stem
        output_path = output_dir / f"{room_num}.png"

        if render_room(tmx_path, output_path):
            print(f"Rendered: {output_path.name}")
            success += 1
        else:
            failed += 1

    print()
    print(f"Done! Rendered {success} rooms, {failed} failed.")

    return 0 if failed == 0 else 1


if __name__ == '__main__':
    exit(main())
