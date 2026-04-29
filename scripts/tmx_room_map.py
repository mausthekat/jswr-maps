#!/usr/bin/env python3
"""Render a TMX room's tile layer as ASCII art for quick inspection.

Tile categories are resolved from each TMX's own <tileset> declarations
(firstgid + source filename), so the script stays correct even if Tiled
reassigns gids. Stair and conveyor tiles also get per-tile direction
lookups via the referenced .tsx files so the glyphs reflect orientation.

Usage:
    uv run python tmx/scripts/tmx_room_map.py <path-to-room.tmx>

Example:
    uv run python tmx/scripts/tmx_room_map.py tmx/content/jsw-gorgeous/047.tmx
"""

from __future__ import annotations

import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


# Tileset-source-basename substring -> (kind_key, default_glyph, description)
# kind_key is our internal category; default_glyph is used when no directional
# override applies; description is emitted in the legend.
TILESET_KIND = {
    'tiles_solid':       ('solid',       '#', 'solid'),
    'tiles_stairs':      ('stairs',      '/', 'stairs (direction from tsx)'),
    'tiles_platform':    ('platform',    '=', 'platform (solid from above only)'),
    'tiles_hazard':      ('hazard',      'X', 'hazard'),
    'tiles_decoration':  ('decoration',  ' ', 'decoration (passable)'),
    'tiles_conveyor':    ('conveyor',    '>', 'conveyor (direction from tsx)'),
    'tiles_collapsible': ('collapsible', '~', 'collapsible floor'),
    'collectibles':      ('collectible', '*', 'collectible'),
    'guardians':         ('guardian',    'g', 'guardian'),
}

# TMX flip flags (stripped before classification).
TMX_FLIP_MASK = 0xE0000000

# Direction enum from archetype.tiled-project: 0=Up, 1=Down, 2=Left, 3=Right.
DIR_UP, DIR_DOWN, DIR_LEFT, DIR_RIGHT = 0, 1, 2, 3

# Glyph per (kind, direction). Defaults fall back to TILESET_KIND entry.
DIRECTIONAL_GLYPH = {
    ('stairs',   DIR_LEFT):  '\\',
    ('stairs',   DIR_RIGHT): '/',
    ('conveyor', DIR_LEFT):  '<',
    ('conveyor', DIR_RIGHT): '>',
}


def match_tileset_kind(source_or_name: str) -> str | None:
    """Return the kind key for a tileset source basename, or None."""
    basename = Path(source_or_name).stem
    for key, (kind, _glyph, _desc) in TILESET_KIND.items():
        if key in basename:
            return kind
    return None


def parse_tsx_directions(tsx_path: Path) -> dict[int, int]:
    """Parse a .tsx file and return {local_tile_id: direction_enum_value}.

    Only tiles with a `Direction` int property are included.
    """
    directions: dict[int, int] = {}
    if not tsx_path.is_file():
        return directions
    try:
        root = ET.parse(tsx_path).getroot()
    except ET.ParseError:
        return directions
    for tile in root.findall('tile'):
        tid_str = tile.get('id')
        if tid_str is None:
            continue
        try:
            tid = int(tid_str)
        except ValueError:
            continue
        for prop in tile.findall('./properties/property'):
            if prop.get('name') == 'Direction':
                val = prop.get('value')
                if val is None:
                    continue
                try:
                    directions[tid] = int(val)
                except ValueError:
                    pass
                break
    return directions


def parse_tilesets(tmx_path: Path) -> list[dict]:
    """Parse <tileset> declarations from a TMX file.

    Each entry: {firstgid, kind, glyph, desc, directions}
    `directions` is a {local_id: enum_val} dict (only populated for stairs
    and conveyors, or any other kind that stores a Direction property).
    """
    text = tmx_path.read_text(encoding='utf-8')
    out: list[dict] = []
    for match in re.finditer(
        r'<tileset\s+firstgid="(\d+)"\s+source="([^"]+)"', text
    ):
        firstgid = int(match.group(1))
        source = match.group(2)
        kind = match_tileset_kind(source)
        if kind is None:
            entry = {'firstgid': firstgid, 'kind': 'unknown', 'glyph': '?',
                     'desc': f'unknown ({source})', 'directions': {}}
        else:
            # Look up the canonical tileset metadata
            for _key, (k, g, d) in TILESET_KIND.items():
                if k == kind:
                    glyph, desc = g, d
                    break
            else:
                glyph, desc = '?', 'unknown'
            tsx_path = (tmx_path.parent / source).resolve()
            directions: dict[int, int] = {}
            if kind in ('stairs', 'conveyor'):
                directions = parse_tsx_directions(tsx_path)
            entry = {'firstgid': firstgid, 'kind': kind, 'glyph': glyph,
                     'desc': desc, 'directions': directions}
        out.append(entry)
    out.sort(key=lambda e: e['firstgid'])
    return out


def classify(gid: int, tilesets: list[dict]) -> str:
    """Return the ASCII glyph for a TMX gid."""
    if gid == 0:
        return '.'
    gid &= ~TMX_FLIP_MASK  # strip TMX flip flags
    match = None
    for ts in tilesets:
        if gid >= ts['firstgid']:
            match = ts
        else:
            break
    if match is None:
        return '?'
    kind = match['kind']
    local = gid - match['firstgid']
    direction = match['directions'].get(local)
    if direction is not None:
        key = (kind, direction)
        if key in DIRECTIONAL_GLYPH:
            return DIRECTIONAL_GLYPH[key]
    return match['glyph']


def load_tile_grid(tmx_path: Path) -> list[list[int]]:
    text = tmx_path.read_text(encoding='utf-8')
    layer_match = re.search(
        r'<layer\b([^>]*)>.*?<data encoding="csv">\s*(.*?)\s*</data>',
        text,
        re.DOTALL,
    )
    if layer_match is None:
        raise ValueError("No CSV tile data found in layer")

    attrs = layer_match.group(1)
    width_m = re.search(r'\bwidth="(\d+)"', attrs)
    height_m = re.search(r'\bheight="(\d+)"', attrs)
    layer_w = int(width_m.group(1)) if width_m else None
    layer_h = int(height_m.group(1)) if height_m else None

    raw = layer_match.group(2)
    values = [int(v) for v in raw.replace('\n', ',').split(',') if v.strip()]

    if layer_w and layer_h:
        expected = layer_w * layer_h
        if len(values) != expected:
            raise ValueError(
                f"{tmx_path.name}: CSV has {len(values)} values, "
                f"expected {expected} ({layer_w}x{layer_h})"
            )
        return [values[r * layer_w:(r + 1) * layer_w] for r in range(layer_h)]

    # Fallback: reshape based on newline-separated rows (legacy formatting).
    grid: list[list[int]] = []
    for line in raw.strip().split('\n'):
        line = line.strip().rstrip(',')
        if not line:
            continue
        grid.append([int(v) for v in line.split(',') if v.strip()])
    return grid


def render(grid: list[list[int]], tilesets: list[dict]) -> str:
    if not grid:
        return '(empty grid)\n'
    width = len(grid[0])
    header = '    ' + ''.join(str(c % 10) for c in range(width))
    lines = [header]
    for r, row in enumerate(grid):
        lines.append(f"{r:2}: " + ''.join(classify(v, tilesets) for v in row))
    return '\n'.join(lines) + '\n'


def print_legend() -> None:
    print('Legend:')
    print("  '.'  empty")
    seen: set[str] = set()
    for _key, (_kind, glyph, desc) in TILESET_KIND.items():
        if glyph in seen:
            continue
        seen.add(glyph)
        print(f"  {glyph!r:4} {desc}")
    print("  '<'  conveyor moving left")
    print("  '>'  conveyor moving right")
    print("  '/'  stairs going up-right")
    print("  '\\\\' stairs going up-left")
    print("  '?'  unknown tileset")


def main() -> int:
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <path-to-room.tmx>", file=sys.stderr)
        return 2
    tmx_path = Path(sys.argv[1])
    if not tmx_path.is_file():
        print(f"error: {tmx_path} not found", file=sys.stderr)
        return 1

    tilesets = parse_tilesets(tmx_path)
    if not tilesets:
        print(f"warning: {tmx_path} has no <tileset> declarations", file=sys.stderr)
    grid = load_tile_grid(tmx_path)

    print(f"{tmx_path.name}: {len(grid)} rows x {len(grid[0]) if grid else 0} cols")
    print()
    print('Tilesets (firstgid -> kind -> default glyph, direction count):')
    for ts in tilesets:
        n_dirs = len(ts['directions'])
        print(f"  {ts['firstgid']:6}  {ts['kind']:<12}  {ts['glyph']!r}"
              f"  (directional tiles: {n_dirs})")
    print()
    print(render(grid, tilesets))
    print_legend()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
