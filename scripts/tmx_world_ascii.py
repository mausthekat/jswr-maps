#!/usr/bin/env python3
"""Render an entire TMX map as ASCII text files.

Reads the map folder's `<name>.world` file (the Tiled world layout used by
`tools/bfs_builder` to produce composite PNGs), ASCII-renders each listed
room via `tmx_room_map.py`, and writes:
  * one `room_NNN.txt` per room
  * one `map_composite.txt` stamping every room at its world position (each
    tile is 8 px, so one character per tile).

Default output directory mirrors the bfs_builder PNG output:
    analysis/reachability_debug/<map-name>/text/

Usage:
    uv run python tmx/scripts/tmx_world_ascii.py <map-folder> [--out <dir>]

Examples:
    uv run python tmx/scripts/tmx_world_ascii.py tmx/content/main
    uv run python tmx/scripts/tmx_world_ascii.py tmx/content/jsw-gorgeous
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from tmx_room_map import classify, load_tile_grid, parse_tilesets

TILE_PX = 8
ROOM_COLS = 32
ROOM_ROWS = 16


def parse_world_file(world_path: Path) -> list[tuple[str, int, int]]:
    """Return a list of (tmx_filename, world_x_px, world_y_px)."""
    data = json.loads(world_path.read_text(encoding='utf-8'))
    out: list[tuple[str, int, int]] = []
    for m in data.get('maps', []):
        fn = m.get('fileName')
        x = m.get('x')
        y = m.get('y')
        if fn is None or x is None or y is None:
            continue
        out.append((fn, int(x), int(y)))
    return out


def render_room_ascii(tmx_path: Path) -> list[str] | None:
    """Render a single room as a list of raw ASCII row strings (no headers)."""
    if not tmx_path.is_file():
        return None
    tilesets = parse_tilesets(tmx_path)
    grid = load_tile_grid(tmx_path)
    if not grid:
        return None
    return [''.join(classify(v, tilesets) for v in row) for row in grid]


def render_all(map_folder: Path) -> tuple[list[tuple[str, list[str]]], str]:
    """Render every room listed in the world file.

    Returns ``(per_room, composite)`` where ``per_room`` is a list of
    ``(room_filename_stem, ascii_rows)`` and ``composite`` is the full
    world-assembled ASCII string (with trailing newline).
    """
    world_path = map_folder / f"{map_folder.name}.world"
    if not world_path.is_file():
        print(f"error: no world file at {world_path}", file=sys.stderr)
        return [], ''

    entries = parse_world_file(world_path)
    if not entries:
        print(f"error: world file {world_path} has no maps", file=sys.stderr)
        return [], ''

    min_x = min(x for _, x, _ in entries)
    min_y = min(y for _, _, y in entries)

    per_room: list[tuple[str, list[str]]] = []
    stamped: list[tuple[int, int, list[str]]] = []
    missing: list[str] = []
    for fn, wx, wy in entries:
        room = render_room_ascii(map_folder / fn)
        if room is None:
            missing.append(fn)
            continue
        per_room.append((Path(fn).stem, room))
        col = (wx - min_x) // TILE_PX
        row = (wy - min_y) // TILE_PX
        stamped.append((col, row, room))

    if not stamped:
        print("error: no rooms rendered", file=sys.stderr)
        return per_room, ''

    total_cols = max(col + len(r[0]) for col, _, r in stamped)
    total_rows = max(row + len(r) for _, row, r in stamped)
    canvas: list[list[str]] = [[' '] * total_cols for _ in range(total_rows)]
    for col, row, r in stamped:
        for dy, line in enumerate(r):
            target = canvas[row + dy]
            for dx, ch in enumerate(line):
                target[col + dx] = ch

    if missing:
        print(f"warning: skipped {len(missing)} missing rooms: {missing[:5]}"
              f"{'...' if len(missing) > 5 else ''}", file=sys.stderr)

    composite = '\n'.join(''.join(row) for row in canvas) + '\n'
    return per_room, composite


DEFAULT_OUT_ROOT = Path('analysis/reachability_debug')


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('map_folder', type=Path, help='TMX map folder (e.g. tmx/content/main)')
    ap.add_argument('--out', type=Path,
                    help='Output directory (default: '
                         'analysis/reachability_debug/<map-name>/text)')
    args = ap.parse_args()

    if not args.map_folder.is_dir():
        print(f"error: {args.map_folder} is not a directory", file=sys.stderr)
        return 1

    per_room, composite = render_all(args.map_folder)
    if not composite:
        return 1

    out_dir = args.out or (DEFAULT_OUT_ROOT / args.map_folder.name / 'text')
    out_dir.mkdir(parents=True, exist_ok=True)

    for stem, rows in per_room:
        (out_dir / f"room_{stem}.txt").write_text('\n'.join(rows) + '\n',
                                                   encoding='utf-8')

    composite_path = out_dir / 'map_composite.txt'
    composite_path.write_text(composite, encoding='utf-8')

    print(f"wrote {len(per_room)} room files + map_composite.txt "
          f"to {out_dir}", file=sys.stderr)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
