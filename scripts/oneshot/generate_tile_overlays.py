#!/usr/bin/env python3
"""
Generate tile type overlay images for JSW Gorgeous rooms.

This script creates overlay images showing tile type borders for each room,
helping debug tile categorization issues.

Input: TMX files in tmx/_in_progress/jsw-gorgeous/*.tmx
Output: Overlay images in tmx/_in_progress/jsw-gorgeous/rooms_overlay/*.png
"""

import xml.etree.ElementTree as ET
from pathlib import Path
from PIL import Image, ImageDraw

# Tile type definitions based on firstgid values
TILE_TYPES = {
    'empty': {'range': (0, 0), 'color': None},
    'solid': {'range': (1, 2048), 'color': (255, 255, 255, 255)},      # White
    'stairs': {'range': (2049, 4096), 'color': (255, 255, 0, 255)},    # Yellow
    'platform': {'range': (4097, 6144), 'color': (0, 255, 0, 255)},    # Green
    'hazard': {'range': (6145, 8192), 'color': (255, 0, 0, 255)},      # Red
    'decoration': {'range': (8193, 10240), 'color': (0, 0, 255, 255)}, # Blue
    'conveyor': {'range': (10241, 99999), 'color': (0, 255, 255, 255)} # Cyan
}

# Room dimensions
TILE_WIDTH = 8
TILE_HEIGHT = 8
ROOM_WIDTH_TILES = 32
ROOM_HEIGHT_TILES = 16
IMAGE_WIDTH = ROOM_WIDTH_TILES * TILE_WIDTH   # 256
IMAGE_HEIGHT = ROOM_HEIGHT_TILES * TILE_HEIGHT  # 128


def get_tile_type(gid: int) -> str:
    """Determine tile type from GID."""
    for tile_type, info in TILE_TYPES.items():
        min_gid, max_gid = info['range']
        if min_gid <= gid <= max_gid:
            return tile_type
    return 'empty'


def get_tile_color(gid: int):
    """Get border color for a tile GID."""
    tile_type = get_tile_type(gid)
    return TILE_TYPES[tile_type]['color']


def parse_tmx_tiles(tmx_path: Path) -> list:
    """Parse TMX file and extract tile GIDs as a flat list."""
    tree = ET.parse(tmx_path)
    root = tree.getroot()

    # Find the layer with tile data
    layer = root.find(".//layer[@name='Tiles']")
    if layer is None:
        layer = root.find(".//layer")

    if layer is None:
        raise ValueError(f"No layer found in {tmx_path}")

    data = layer.find("data")
    if data is None:
        raise ValueError(f"No data found in layer in {tmx_path}")

    encoding = data.get('encoding', '')
    if encoding != 'csv':
        raise ValueError(f"Unsupported encoding: {encoding}")

    # Parse CSV data
    csv_text = data.text.strip()
    tiles = []
    for line in csv_text.split('\n'):
        line = line.strip().rstrip(',')
        if line:
            for val in line.split(','):
                val = val.strip()
                if val:
                    tiles.append(int(val))

    return tiles


def draw_tile_border(draw: ImageDraw.ImageDraw, x: int, y: int, color, scale: int):
    """Draw a 1px border on top and left edges of a scaled tile."""
    if color is None:
        return

    tile_size = TILE_WIDTH * scale
    px = x * tile_size
    py = y * tile_size

    # Draw only top and left edges
    draw.line([(px, py), (px + tile_size - 1, py)], fill=color)
    draw.line([(px, py), (px, py + tile_size - 1)], fill=color)


SCALE = 4  # Scale factor for output images

# Draw order (first drawn is underneath, last is on top)
DRAW_ORDER = ['decoration', 'platform', 'stairs', 'conveyor', 'solid', 'hazard']


def generate_overlay(tmx_path: Path, room_image_path: Path, output_path: Path):
    """Generate overlay image for a single TMX file by compositing borders onto the room image."""
    tiles = parse_tmx_tiles(tmx_path)

    # Load the room image and convert to RGBA
    room_img = Image.open(room_image_path).convert('RGBA')

    # Scale up 4x using nearest neighbor to preserve pixel art
    scaled_size = (room_img.width * SCALE, room_img.height * SCALE)
    img = room_img.resize(scaled_size, Image.NEAREST)
    draw = ImageDraw.Draw(img)

    # Build list of (x, y, gid, tile_type) for all tiles
    tile_data = []
    for i, gid in enumerate(tiles):
        x = i % ROOM_WIDTH_TILES
        y = i // ROOM_WIDTH_TILES
        tile_type = get_tile_type(gid)
        tile_data.append((x, y, gid, tile_type))

    # Draw borders in specified order
    for draw_type in DRAW_ORDER:
        for x, y, gid, tile_type in tile_data:
            if tile_type == draw_type:
                color = TILE_TYPES[tile_type]['color']
                draw_tile_border(draw, x, y, color, SCALE)

    # Save the overlay image
    img.save(output_path)


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Generate tile type overlay images for TMX rooms')
    parser.add_argument('tmx_directory', type=Path, nargs='?',
                        help='Directory containing TMX files (default: tmx/_in_progress/jsw-gorgeous)')
    args = parser.parse_args()

    # Determine paths
    script_dir = Path(__file__).parent
    if args.tmx_directory:
        tmx_dir = args.tmx_directory
    else:
        # script lives at tmx/scripts/oneshot/ — go up to tmx/ then into _in_progress
        tmx_dir = script_dir.parent.parent / '_in_progress' / 'jsw-gorgeous'

    rooms_dir = tmx_dir / 'rooms'
    output_dir = tmx_dir / 'rooms_overlay'

    # Create output directory if needed
    output_dir.mkdir(parents=True, exist_ok=True)

    # Find all TMX files
    tmx_files = sorted([p for p in tmx_dir.glob('*.tmx') if p.stem.isdigit()])

    if not tmx_files:
        print(f"No TMX files found in {tmx_dir}")
        return

    print(f"Found {len(tmx_files)} TMX files")
    print(f"Room images directory: {rooms_dir}")
    print(f"Output directory: {output_dir}")
    print()

    # Process each TMX file
    generated_count = 0
    for tmx_path in tmx_files:
        room_num = tmx_path.stem  # e.g., "033"
        room_image_path = rooms_dir / f"{room_num}.png"
        output_path = output_dir / f"{room_num}.png"

        # Skip if room image doesn't exist
        if not room_image_path.exists():
            print(f"Skipping {tmx_path.name}: no room image found at {room_image_path.name}")
            continue

        try:
            generate_overlay(tmx_path, room_image_path, output_path)
            print(f"Generated: {output_path.name}")
            generated_count += 1
        except Exception as e:
            print(f"Error processing {tmx_path.name}: {e}")

    print()
    print(f"Done! Generated {generated_count} overlay images.")
    print()
    print("Tile type legend:")
    print("  White  = Solid (GID 1-2048)")
    print("  Yellow = Stairs (GID 2049-4096)")
    print("  Green  = Platform (GID 4097-6144)")
    print("  Red    = Hazard (GID 6145-8192)")
    print("  Blue   = Decoration (GID 8193-10240)")
    print("  Cyan   = Conveyor (GID 10241+)")


if __name__ == '__main__':
    main()
