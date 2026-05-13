"""
ZX-attribute-faithful renderer for JSW-engine snapshots / tape images.

Reads a `.z80` / `.sna` / `.szx` / `.tap` / `.tzx` / `.pzx` via
`jsw_snapshot.load_snapshot`, walks the per-room exit graph to compute
a Euclidean-grid placement for every populated room, and writes a PNG
showing every room rendered at native ZX colours.

Algorithm in three stages:

1. **Per-room render** — each cell is 8x8 pixels using its tile
   graphic's ZX attribute (paper / ink / bright) and bitmap.

2. **Exit-graph layout** — BFS from the first populated room; for each
   exit (LEFT / RIGHT / ABOVE / BELOW) place the neighbour at the
   corresponding offset. Skip an edge when the neighbour already has
   a position that would conflict OR the destination cell is occupied
   by another room. Repeat from any room not yet placed — those form
   their own components.

3. **Map composition** — every component gets a tightly packed
   bounding box of its rooms, components are stacked vertically with
   a gutter, and cross-component exits (the dropped edges) are routed
   as right-angled connector lines through the free tile-space between
   rooms — never crossing any room rectangle. Routing falls back to a
   text label only when no orthogonal path exists.

CLI:
    python jsw_render.py <snapshot-or-tape> [--out PATH] [--scale N]
"""

from __future__ import annotations

import argparse
import heapq
from collections import deque
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from jsw_snapshot import (
    Engine, Room, Snapshot, TileGraphic,
    detect_engine, iter_rooms, load_snapshot,
)


# ---------------------------------------------------------------------------
# ZX colour palette
# ---------------------------------------------------------------------------

# Each ZX attribute byte: bits 0-2 ink, bits 3-5 paper, bit 6 bright.
# Standard channel intensities are 0xCD (normal) and 0xFF (bright);
# black stays black regardless of the bright bit.
_ZX_BASE_RGB = (
    (0x00, 0x00, 0x00),  # 0 black
    (0x00, 0x00, 0xCD),  # 1 blue
    (0xCD, 0x00, 0x00),  # 2 red
    (0xCD, 0x00, 0xCD),  # 3 magenta
    (0x00, 0xCD, 0x00),  # 4 green
    (0x00, 0xCD, 0xCD),  # 5 cyan
    (0xCD, 0xCD, 0x00),  # 6 yellow
    (0xCD, 0xCD, 0xCD),  # 7 white
)


def _zx_color(idx: int, bright: bool) -> tuple[int, int, int]:
    if not bright or idx == 0:
        return _ZX_BASE_RGB[idx & 7]
    base = _ZX_BASE_RGB[idx & 7]
    return tuple(0xFF if c else 0 for c in base)  # type: ignore[return-value]


def _attr_paper_ink(attr: int) -> tuple[tuple[int, int, int],
                                        tuple[int, int, int]]:
    bright = bool(attr & 0x40)
    ink = _zx_color(attr & 0x07, bright)
    paper = _zx_color((attr >> 3) & 0x07, bright)
    return paper, ink


# ---------------------------------------------------------------------------
# Per-room render
# ---------------------------------------------------------------------------

ROOM_W_TILES = 32
ROOM_H_TILES = 16
TILE_PX = 8
ROOM_W_PX = ROOM_W_TILES * TILE_PX  # 256
ROOM_H_PX = ROOM_H_TILES * TILE_PX  # 128


# Canonical tile-category colours — single source of truth is
# docs/formats/CANONICAL_TILE_CATEGORY_COLORS.md (mirrored at runtime
# in src/rendering/tile_renderer.py and src/procgen/room_renderer.py).
# Keep these RGB values in sync with that doc.
_CATEGORY_COLORS = (
    (255, 255, 255),  # 0 SOLID
    (255, 255,   0),  # 1 STAIRS
    (  0, 255,   0),  # 2 PLATFORM
    (252,   1,   4),  # 3 HAZARD
    (  0,   0, 255),  # 4 DECORATION
    (  0, 255, 255),  # 5 CONVEYOR
    (128,   0, 255),  # 6 PENROSE
    (255, 128,   0),  # 7 COLLAPSIBLE
    (255,   0, 255),  # 8 TRAMPOLINE
)
# Fallback colour for JSW64 tile palette entries that don't have a
# documented role mapping (`tile_role_map` empty or shorter than the
# palette). Mid-grey so they read as "uncategorised" without colliding
# with any of the canonical role hues.
_UNKNOWN_CATEGORY_COLOR = (128, 128, 128)


def _attr_match_palette(palette: list[TileGraphic], attr: int) -> int | None:
    """Find the palette index whose attribute byte matches `attr`."""
    for i, t in enumerate(palette):
        if t.attr == attr:
            return i
    return None


# 8x8 "water" placeholder pattern for JSW64-Z cells whose attribute
# doesn't match any palette tile. Real Z files use a global water
# bitmap stored elsewhere in the engine — until we extract that, this
# wave-like hatch keeps unmatched cells visually distinct from solid
# blocks while still showing the cell's attribute colour.
_WATER_PATTERN = bytes(
    int(b, 2) for b in (
        "01010101",
        "10101010",
        "00000000",
        "01010101",
        "10101010",
        "00000000",
        "01010101",
        "10101010",
    )
)


def _resolve_cell(room: Room, value: int) -> tuple[TileGraphic | None, int]:
    """
    Map a layout cell value to a (tile, effective_attr) pair.

    For palette-index layouts: cell value indexes the palette directly.
    For attribute-array layouts (Z): cell value is a ZX attribute byte;
    look up the palette tile with the matching attribute. Unmatched
    attribute bytes reuse palette slot 1's bitmap colored by the
    cell's own attribute — JSWED's `Jsw64Room::exportCells`
    (`j64room.cxx:1620-1652`) does the same: it iterates every attr
    byte that appears on-screen but isn't in the 16-entry palette,
    creates a synthetic cell entry inheriting palette[1]'s 8-byte
    bitmap with the new attribute, and exports it as `CB_WATER`.
    Without this fallback the cell vanishes from the TMX (e.g. the
    "DeePeR" letter straights at the top of cavern 19).
    """
    palette = room.tile_palette
    if not palette:
        return None, 0
    if room.is_attribute_layout:
        idx = _attr_match_palette(palette, value)
        if idx is None:
            # Unmatched attribute: synthesize a tile using palette[1]'s
            # bitmap with the cell's own attribute as colour.
            if len(palette) > 1:
                base = palette[1]
                return TileGraphic(attr=value, bitmap=base.bitmap), value
            return None, value
        tile = palette[idx]
        return tile, tile.attr
    if value < len(palette):
        tile = palette[value]
        return tile, tile.attr
    # Out-of-range index — fall back to BG tile.
    bg = palette[0]
    return bg, bg.attr


def render_room(room: Room, category: bool = False) -> Image.Image:
    """
    Render one room as a 256x128 RGB image.

    `category=False` (default): native ZX rendering — each tile uses
    its own attribute (paper/ink/bright) and bitmap. JSW64-Z cells
    whose attribute doesn't match any palette tile are drawn with a
    placeholder "water" hatch coloured by the cell's attribute, since
    the real Z water bitmap lives outside the room record.

    `category=True`: each cell is filled with its tile-category colour
    from `_CATEGORY_COLORS`. For attribute-array layouts the colour
    comes from the matching palette index, or black for unmatched.
    Tile index 0 (room background) renders as black throughout.
    """
    arr = np.zeros((ROOM_H_PX, ROOM_W_PX, 3), dtype=np.uint8)
    palette = room.tile_palette
    if not palette:
        return Image.fromarray(arr, mode="RGB")
    for cy in range(ROOM_H_TILES):
        for cx in range(ROOM_W_TILES):
            value = int(room.layout[cy, cx])
            ix = cx * TILE_PX
            iy = cy * TILE_PX
            if category:
                cat_idx = _category_index(room, value)
                if cat_idx is None:
                    continue  # background — leave the cell black
                if 0 <= cat_idx < len(_CATEGORY_COLORS):
                    color = _CATEGORY_COLORS[cat_idx]
                else:
                    color = _UNKNOWN_CATEGORY_COLOR
                arr[iy:iy + TILE_PX, ix:ix + TILE_PX] = color
                continue
            tile, eff_attr = _resolve_cell(room, value)
            paper, ink = _attr_paper_ink(eff_attr)
            bitmap = tile.bitmap if tile is not None else _WATER_PATTERN
            for py in range(TILE_PX):
                row_byte = bitmap[py]
                for px in range(TILE_PX):
                    bit = (row_byte >> (7 - px)) & 1
                    arr[iy + py, ix + px] = ink if bit else paper
    return Image.fromarray(arr, mode="RGB")


def _category_index(room: Room, value: int) -> int | None:
    """
    Canonical tile-category index for `value` in `room`, or None if
    the cell should render as background.

    For engines with a documented role map (JSW48, JSW128) the
    mapping is exact. For engines whose role assignment we haven't
    decoded yet (JSW64 V/W/X/Y/YY/Z) the role map is empty, and we
    fall through to using the palette index as the category — a
    visual-distinguishability hack: tile-class N maps to category N
    so different tiles get different hues, and indices past the 9
    documented roles render in the grey "uncategorised" colour. This
    isn't a claim about which tile is which role; it's just enough
    structure to read the layout.

    For attribute-array layouts (Z), the layout value is a ZX
    attribute byte — match it against palette attrs first to recover
    the palette index, then resolve through the role table.
    """
    role_map = room.tile_role_map
    if room.is_attribute_layout:
        idx = _attr_match_palette(room.tile_palette, value)
        if idx is None:
            # JSWED `Jsw64Room::exportCells` exports unmatched attrs as
            # `CB_WATER` (= PLATFORM in the Manic-engine canonical role
            # map). Returning 2 here means the cell ends up in
            # `tiles_platform.tsx` with palette[1]'s bitmap recoloured
            # by the cell's attribute (see `_resolve_cell`). Skips
            # background-attribute cells: when the cell carries the
            # AIR slot's own attribute it's just empty space.
            if room.tile_palette and value == room.tile_palette[0].attr:
                return None
            return 2
    elif 0 <= value < len(room.tile_palette):
        idx = value
    else:
        idx = None
    if idx is None:
        return None
    if not role_map:
        # No documented mapping — surface the palette index directly
        # so the renderer can still distinguish tile classes visually.
        # Index 0 is reserved for "background" across every JSW
        # engine seen so far, so map it to None to keep BG black.
        return None if idx == 0 else idx
    if idx >= len(role_map):
        return None
    return role_map[idx]


# ---------------------------------------------------------------------------
# Exit-graph layout
# ---------------------------------------------------------------------------

# Direction order matches Room.exits: LEFT, RIGHT, ABOVE, BELOW.
_DIR_OFFSET = ((-1, 0), (1, 0), (0, -1), (0, 1))
_DIR_NAMES = ("L", "R", "U", "D")
# Reverse of each direction index — used for the "is this exit
# genuinely bidirectional?" sanity check below.
_DIR_REVERSE = (1, 0, 3, 2)


def _is_bidirectional_exit(rooms: dict[int, Room], src_id: int,
                           direction: int, tgt_id: int) -> bool:
    """
    True only when the source's exit in `direction` is mirrored by the
    target's exit in the opposite direction. JSW engines overload
    exit-byte `0` (and sometimes `255`) as a "no exit" sentinel —
    even though room 0 is a real room — so we can't trust the raw
    byte. A genuine playable edge always round-trips: room A's right
    is room B, and room B's left is room A.
    """
    if tgt_id not in rooms or tgt_id == src_id:
        return False
    return rooms[tgt_id].exits[_DIR_REVERSE[direction]] == src_id


@dataclass
class Placement:
    room_id: int
    component: int
    x: int  # in room cells (left-to-right)
    y: int  # in room cells (top-to-bottom)


@dataclass
class CrossEdge:
    """An exit that couldn't be placed inside the source's component."""

    src_id: int
    dst_id: int
    direction: int  # 0=L, 1=R, 2=U, 3=D
    reason: str     # 'conflict', 'occupied', 'unreachable'


def _bfs_from_seed(rooms: dict[int, Room], seed: int,
                   blocked_ids: frozenset[int],
                   ) -> tuple[dict[int, tuple[int, int]],
                              list[tuple[int, int, int, str]]]:
    """
    Walk the bidirectional exit graph from `seed`, placing every
    reachable room at its Euclidean offset. Returns a `(placed,
    cross)` pair where `placed` maps room-id to (x, y) and `cross`
    is the list of dropped edges (src_id, dst_id, direction, reason).

    `blocked_ids` are rooms already committed to earlier components —
    BFS won't claim them or use their cells.
    """
    placed: dict[int, tuple[int, int]] = {seed: (0, 0)}
    occupied: dict[tuple[int, int], int] = {(0, 0): seed}
    cross: list[tuple[int, int, int, str]] = []
    queue: deque[int] = deque([seed])
    while queue:
        rid = queue.popleft()
        r = rooms[rid]
        sx, sy = placed[rid]
        for direction, (dx, dy) in enumerate(_DIR_OFFSET):
            tgt = r.exits[direction]
            if not _is_bidirectional_exit(rooms, rid, direction, tgt):
                continue
            if tgt in blocked_ids:
                # Target already lives in another committed component —
                # this becomes a cross-component edge for the renderer.
                cross.append((rid, tgt, direction, 'conflict'))
                continue
            tx, ty = sx + dx, sy + dy
            if tgt in placed:
                if placed[tgt] != (tx, ty):
                    cross.append((rid, tgt, direction, 'conflict'))
                continue
            if (tx, ty) in occupied:
                cross.append((rid, tgt, direction, 'occupied'))
                continue
            placed[tgt] = (tx, ty)
            occupied[(tx, ty)] = tgt
            queue.append(tgt)
    return placed, cross


def _attach_one_way_singletons(rooms: dict[int, Room],
                               placements: dict[int, Placement]) -> int:
    """
    Pull singleton components into larger ones via non-bidirectional
    exits, using both **outgoing** (the singleton's own exits) and
    **incoming** (other rooms' exits *to* the singleton) constraints.

    JSW rooms often have death-respawn pointers in their exit table
    that aren't real adjacencies — JSW1's 'Entrance to Hades' is
    referenced from multiple rooms via spatial fall/walk-into edges
    (Drive.U, Security-Guard.D, Under-the-Drive.L all point at it),
    which collectively pin Hades to a single empty cell, but Hades's
    own exits are death-respawn pointers that don't round-trip. Using
    both directions lets us honour the "spatial" half while ignoring
    the "respawn" half.

    For each singleton R we collect every implied position — from the
    singleton's own exits (R.exits[d] = X => R is at X.pos - offset[d])
    AND from incoming references (X.exits[d] = R => R is at X.pos +
    offset[d]). The position with the most votes wins; ties broken by
    incoming-first (incoming pointers carry more spatial signal than
    outgoing ones). If the winning position is empty in the target's
    component, R is moved there. Iterates so attaching one singleton
    can free a slot for the next.
    """
    cells: dict[int, dict[tuple[int, int], int]] = {}
    sizes: dict[int, int] = {}
    for p in placements.values():
        cells.setdefault(p.component, {})[(p.x, p.y)] = p.room_id
        sizes[p.component] = sizes.get(p.component, 0) + 1

    # Build reverse index: for each room id R, list of (referrer_id,
    # direction) where referrer.exits[direction] == R.
    incoming: dict[int, list[tuple[int, int]]] = {}
    for rid, r in rooms.items():
        for d in range(4):
            tgt = r.exits[d]
            if tgt and tgt != rid:
                incoming.setdefault(tgt, []).append((rid, d))

    moved_total = 0
    changed = True
    while changed:
        changed = False
        singletons = sorted(c for c, s in sizes.items() if s == 1)
        for src_comp in singletons:
            if sizes.get(src_comp) != 1:
                continue
            src_rid = next(iter(cells[src_comp].values()))
            r = rooms[src_rid]
            # Tally implied positions from both incoming and outgoing
            # exits, weighted: incoming counts +2, outgoing counts +1.
            votes: dict[tuple[int, int, int], int] = {}
            for (ref_id, d) in incoming.get(src_rid, []):
                if ref_id not in placements:
                    continue
                rp = placements[ref_id]
                if rp.component == src_comp:
                    continue
                dx, dy = _DIR_OFFSET[d]
                key = (rp.component, rp.x + dx, rp.y + dy)
                votes[key] = votes.get(key, 0) + 2
            for d, (dx, dy) in enumerate(_DIR_OFFSET):
                tgt = r.exits[d]
                if tgt == 0 or tgt == src_rid or tgt not in placements:
                    continue
                tp = placements[tgt]
                if tp.component == src_comp:
                    continue
                key = (tp.component, tp.x - dx, tp.y - dy)
                votes[key] = votes.get(key, 0) + 1
            if not votes:
                continue
            # Sort by vote desc, then prefer larger target component.
            ranked = sorted(
                votes.items(),
                key=lambda kv: (-kv[1], -sizes.get(kv[0][0], 0)),
            )
            for (comp_id, nx, ny), _votes in ranked:
                if (nx, ny) in cells[comp_id]:
                    continue
                old = placements[src_rid]
                del cells[src_comp][(old.x, old.y)]
                cells.pop(src_comp, None)
                sizes.pop(src_comp, None)
                placements[src_rid] = Placement(src_rid, comp_id, nx, ny)
                cells[comp_id][(nx, ny)] = src_rid
                sizes[comp_id] = sizes.get(comp_id, 0) + 1
                moved_total += 1
                changed = True
                break
    return moved_total


def _attach_title_twin_singletons(rooms: dict[int, Room],
                                  placements: dict[int, Placement]) -> int:
    """
    Group singleton rooms that share a title with a room in a larger
    component into a single "mirror" component, placed at the same
    geometric position as their twin.

    JSW64-V/W use this pattern: rooms 64..127 (banks 4 and 6) are an
    alternate-level mansion that mirrors rooms 0..63 in banks 1/3.
    Each level-2 room shares a title with a level-1 twin and exits
    that point back to level-1 rooms (one-way). They have no bidir
    edges among themselves so the BFS leaves them as 22 singleton
    components — visually noisy. Stacking them in one mirror-shaped
    component gives an at-a-glance "level 2" map next to "level 1".

    Returns the number of singletons moved.
    """
    by_comp: dict[int, list[int]] = {}
    for p in placements.values():
        by_comp.setdefault(p.component, []).append(p.room_id)
    if not by_comp:
        return 0
    # Largest component is the "main" / level-1 reference.
    main_comp_id = max(by_comp.keys(), key=lambda c: len(by_comp[c]))
    title_to_main: dict[str, int] = {}
    for rid in by_comp[main_comp_id]:
        title = rooms[rid].title.strip()
        if title:
            title_to_main.setdefault(title, rid)

    moves: list[tuple[int, int, int]] = []  # (rid, x, y)
    consumed_comps: set[int] = set()
    for comp_id, ids in by_comp.items():
        if comp_id == main_comp_id or len(ids) != 1:
            continue
        rid = ids[0]
        title = rooms[rid].title.strip()
        twin = title_to_main.get(title)
        if twin is None:
            continue
        tp = placements[twin]
        moves.append((rid, tp.x, tp.y))
        consumed_comps.add(comp_id)

    if not moves:
        return 0
    # New component id: one past the highest currently in use.
    mirror_id = max(by_comp.keys()) + 1
    for rid, x, y in moves:
        placements[rid] = Placement(rid, mirror_id, x, y)
    return len(moves)


def compute_placements(snap: Snapshot, engine: Engine
                       ) -> tuple[dict[int, Placement], list[CrossEdge]]:
    """
    Place every populated room into a 2D grid of components.

    Strategy — **largest-segment first**:

    Repeatedly try every unplaced room as a BFS seed and commit the
    seed whose run places the most rooms in one Euclidean-aligned
    segment. After committing, repeat on what's left. This keeps the
    primary segment as large as the bidir-exit graph allows and pushes
    the remaining non-Euclidean fragments into the smallest possible
    set of secondary segments.

    Why seed choice matters: when two paths from a single seed both
    try to place the same room from different directions, the second
    path hits an "occupied" cell and the room is dropped. A seed that
    enters that neighbourhood from the "right" direction first avoids
    the conflict and pulls the room into the primary segment. JSW1's
    Ballroom-West / Kitchen island (7 rooms with 7 bidir-edges into
    the main mansion) is exactly this case.

    Edges dropped during BFS — whether due to in-segment 'occupied'
    cells or 'conflict' with rooms already placed in another
    committed segment — are returned as CrossEdges so the renderer
    can route a connector line between them.
    """
    rooms = {r.id: r for r in iter_rooms(snap, engine)}
    if not rooms:
        return {}, []

    placements: dict[int, Placement] = {}
    cross_out: list[CrossEdge] = []
    next_component = 0
    unplaced = set(rooms.keys())

    while unplaced:
        blocked = frozenset(placements.keys())
        best_size = 0
        best_seed = None
        best_placed: dict[int, tuple[int, int]] = {}
        best_cross: list[tuple[int, int, int, str]] = []
        # Stable order so the choice is deterministic when sizes tie.
        for seed in sorted(unplaced):
            placed, cross = _bfs_from_seed(rooms, seed, blocked)
            size = len(placed)
            if size > best_size:
                best_size = size
                best_seed = seed
                best_placed = placed
                best_cross = cross
            # Early exit: nothing else can beat us if we covered every
            # room reachable from any seed in the same connected sub-
            # graph (BFS reaches every bidir-connected room from any
            # seed in it; only the conflict-resolution layout differs).
            if size == len(unplaced):
                break

        if best_seed is None:
            # Should never happen — every non-empty `unplaced` has at
            # least the trivial size-1 BFS — but defend anyway.
            seed = next(iter(unplaced))
            placements[seed] = Placement(seed, next_component, 0, 0)
            unplaced.remove(seed)
            next_component += 1
            continue

        for rid, (x, y) in best_placed.items():
            placements[rid] = Placement(rid, next_component, x, y)
        for src, dst, d, reason in best_cross:
            cross_out.append(CrossEdge(src, dst, d, reason))
        unplaced -= best_placed.keys()
        next_component += 1

    # Pull singletons into larger components via one-way exits (death-
    # respawn pointers etc.) where the target cell is free.
    _attach_one_way_singletons(rooms, placements)
    # Group title-twin singletons (JSW64 V/W bank-4/6 mirror level)
    # into one shared mirror component.
    _attach_title_twin_singletons(rooms, placements)

    return placements, cross_out


# ---------------------------------------------------------------------------
# Map composition
# ---------------------------------------------------------------------------

# Inter-component gutter, in *room cells* (not pixels). Components are
# stacked vertically by default with this much breathing room between
# their bounding boxes. The router needs at least one row of free
# tiles to thread cross-edge connectors between components.
COMPONENT_GUTTER_CELLS = 2

# Margin around the whole layout, in room cells. Gives the router
# space to route around the outside of components when no internal
# corridor exists.
LAYOUT_MARGIN_CELLS = 2


def _build_tile_occupancy(placements: dict[int, "Placement"],
                          comp_origin: dict[int, tuple[int, int]],
                          canvas_w_cells: int,
                          canvas_h_cells: int) -> np.ndarray:
    """Tile-level occupancy grid — True where a placed room sits."""
    grid_w = canvas_w_cells * ROOM_W_TILES
    grid_h = canvas_h_cells * ROOM_H_TILES
    grid = np.zeros((grid_h, grid_w), dtype=bool)
    for p in placements.values():
        ox, oy = comp_origin[p.component]
        cx, cy = p.x + ox, p.y + oy
        x0 = cx * ROOM_W_TILES
        y0 = cy * ROOM_H_TILES
        grid[y0:y0 + ROOM_H_TILES, x0:x0 + ROOM_W_TILES] = True
    return grid


def _route_orthogonal(occ: np.ndarray, src: tuple[int, int],
                      dst: tuple[int, int],
                      turn_penalty: int = 8) -> list[tuple[int, int]]:
    """
    Dijkstra over an 8-pixel-tile grid with a per-turn cost penalty,
    finding the shortest orthogonal path through unoccupied tiles
    from `src` to `dst` (both inclusive). Returns [] if either
    endpoint is occupied or no path exists.

    The turn penalty produces visually clean routes — the planner
    prefers long straight runs with few corners over wiggly equal-
    length zig-zags. Cost = manhattan_steps + turn_penalty * #turns.
    """
    h, w = occ.shape
    sx, sy = src
    dx, dy = dst
    if not (0 <= sx < w and 0 <= sy < h and 0 <= dx < w and 0 <= dy < h):
        return []
    if occ[sy, sx] or occ[dy, dx]:
        return []
    # 4 directions: 0=R, 1=L, 2=D, 3=U. Last-direction state lets us
    # charge a penalty only when we change direction.
    dirs = ((1, 0), (-1, 0), (0, 1), (0, -1))
    INF = 0x3FFFFFFF
    # cost[y, x, last_dir+1]: 0..3 for entered direction, 4 = "no last"
    cost = np.full((h, w, 5), INF, dtype=np.int32)
    parent_x = np.full((h, w, 5), -1, dtype=np.int32)
    parent_y = np.full((h, w, 5), -1, dtype=np.int32)
    parent_d = np.full((h, w, 5), -1, dtype=np.int8)
    cost[sy, sx, 4] = 0
    pq: list[tuple[int, int, int, int]] = [(0, sx, sy, 4)]
    found_d = -1
    while pq:
        c, x, y, ld = heapq.heappop(pq)
        if c > cost[y, x, ld]:
            continue
        if (x, y) == dst:
            found_d = ld
            break
        for d, (mx, my) in enumerate(dirs):
            nx, ny = x + mx, y + my
            if not (0 <= nx < w and 0 <= ny < h):
                continue
            if occ[ny, nx]:
                continue
            turn = (ld != 4 and ld != d)
            nc = c + 1 + (turn_penalty if turn else 0)
            if nc < cost[ny, nx, d]:
                cost[ny, nx, d] = nc
                parent_x[ny, nx, d] = x
                parent_y[ny, nx, d] = y
                parent_d[ny, nx, d] = ld
                heapq.heappush(pq, (nc, nx, ny, d))
    if found_d < 0:
        return []
    path = [dst]
    x, y, di = dst[0], dst[1], found_d
    while True:
        px = int(parent_x[y, x, di])
        if px < 0:
            break
        py = int(parent_y[y, x, di])
        pd = int(parent_d[y, x, di])
        path.append((px, py))
        x, y, di = px, py, pd
    path.reverse()
    return path


def _path_corners(path: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Reduce a per-tile path to the points where direction changes."""
    if len(path) <= 2:
        return list(path)
    out = [path[0]]
    last = (path[1][0] - path[0][0], path[1][1] - path[0][1])
    for i in range(2, len(path)):
        cur = (path[i][0] - path[i - 1][0], path[i][1] - path[i - 1][1])
        if cur != last:
            out.append(path[i - 1])
            last = cur
    out.append(path[-1])
    return out


# (canvas_x, canvas_y) of the midpoint of a room's edge facing
# `direction` (0=L, 1=R, 2=U, 3=D), in PIXELS.
def _edge_pixel(canvas_cx: int, canvas_cy: int, direction: int
                ) -> tuple[int, int]:
    px = canvas_cx * ROOM_W_PX
    py = canvas_cy * ROOM_H_PX
    if direction == 0:    # L
        return px, py + ROOM_H_PX // 2
    if direction == 1:    # R
        return px + ROOM_W_PX - 1, py + ROOM_H_PX // 2
    if direction == 2:    # U
        return px + ROOM_W_PX // 2, py
    return px + ROOM_W_PX // 2, py + ROOM_H_PX - 1  # D


# Tile-grid coords of the first tile OUTSIDE a room past its edge in
# `direction`. This is the start tile for routing — the router can
# walk from here through free tiles to the destination's port.
def _port_tile(canvas_cx: int, canvas_cy: int, direction: int
               ) -> tuple[int, int]:
    base_x = canvas_cx * ROOM_W_TILES
    base_y = canvas_cy * ROOM_H_TILES
    mid_x = base_x + ROOM_W_TILES // 2
    mid_y = base_y + ROOM_H_TILES // 2
    if direction == 0:    # L
        return base_x - 1, mid_y
    if direction == 1:    # R
        return base_x + ROOM_W_TILES, mid_y
    if direction == 2:    # U
        return mid_x, base_y - 1
    return mid_x, base_y + ROOM_H_TILES  # D


def _load_label_font(size: int = 11) -> ImageFont.ImageFont:
    for candidate in (
        "/System/Library/Fonts/Monaco.ttf",
        "/System/Library/Fonts/SFNSMono.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    ):
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


@dataclass
class CanonicalLayout:
    """Result of `compute_canonical_layout`. `room_xy` maps room-id to
    absolute (gx, gy) on the canvas, in room-cell units (one room is
    one cell). `canvas_w_cells` / `canvas_h_cells` are the full canvas
    bounds in room-cells. `comp_origin` is the per-component translation
    used by the renderer's per-component cross-edge router; callers that
    only need final positions can ignore it."""
    room_xy: dict[int, tuple[int, int]]
    canvas_w_cells: int
    canvas_h_cells: int
    comp_origin: dict[int, tuple[int, int]]
    placements: dict[int, "Placement"]
    cross: list


def compute_canonical_layout(snap: Snapshot, engine: Engine) -> CanonicalLayout | None:
    """Stable per-room canvas placement, shared between the renderer and
    the TMX importer's world file. Components are stacked vertically by
    descending size, with a fixed gutter between them and a margin around
    the whole canvas — the same arrangement the canonical PNG output uses.

    Returns None when no rooms could be placed."""
    placements, cross = compute_placements(snap, engine)
    if not placements:
        return None

    by_comp: dict[int, list[Placement]] = {}
    for p in placements.values():
        by_comp.setdefault(p.component, []).append(p)
    components_sorted = sorted(by_comp.items(), key=lambda kv: -len(kv[1]))

    comp_bboxes: dict[int, tuple[int, int, int, int]] = {}
    for comp_id, items in components_sorted:
        xs = [p.x for p in items]
        ys = [p.y for p in items]
        comp_bboxes[comp_id] = (min(xs), min(ys), max(xs), max(ys))

    inner_w = max(bx2 - bx1 + 1 for (bx1, _, bx2, _) in comp_bboxes.values())
    inner_h = (sum(by2 - by1 + 1 for (_, by1, _, by2) in comp_bboxes.values())
               + COMPONENT_GUTTER_CELLS * (len(comp_bboxes) - 1))
    canvas_w_cells = inner_w + 2 * LAYOUT_MARGIN_CELLS
    canvas_h_cells = inner_h + 2 * LAYOUT_MARGIN_CELLS

    comp_origin: dict[int, tuple[int, int]] = {}
    cursor_y = LAYOUT_MARGIN_CELLS
    for comp_id, _ in components_sorted:
        bx1, by1, _, _ = comp_bboxes[comp_id]
        comp_origin[comp_id] = (LAYOUT_MARGIN_CELLS - bx1, cursor_y - by1)
        bx2, by2 = comp_bboxes[comp_id][2], comp_bboxes[comp_id][3]
        cursor_y += (by2 - by1 + 1) + COMPONENT_GUTTER_CELLS

    room_xy = {
        p.room_id: (p.x + comp_origin[p.component][0],
                    p.y + comp_origin[p.component][1])
        for p in placements.values()
    }
    return CanonicalLayout(
        room_xy=room_xy,
        canvas_w_cells=canvas_w_cells,
        canvas_h_cells=canvas_h_cells,
        comp_origin=comp_origin,
        placements=placements,
        cross=cross,
    )


def render_map(snap: Snapshot, engine: Engine,
               scale: int = 1, category: bool = False
               ) -> tuple[Image.Image, dict]:
    """
    Render every populated room of the snapshot into a single PNG.

    Returns the composed image plus a dict of metadata (placements
    grouped by component, cross-edge list) useful for further tooling.
    """
    layout = compute_canonical_layout(snap, engine)
    rooms = {r.id: r for r in iter_rooms(snap, engine)}
    if layout is None:
        return Image.new("RGB", (ROOM_W_PX, ROOM_H_PX), (32, 32, 32)), {}
    placements = layout.placements
    cross = layout.cross
    canvas_w_cells = layout.canvas_w_cells
    canvas_h_cells = layout.canvas_h_cells
    comp_origin = layout.comp_origin

    by_comp: dict[int, list[Placement]] = {}
    for p in placements.values():
        by_comp.setdefault(p.component, []).append(p)
    components_sorted = sorted(by_comp.items(), key=lambda kv: -len(kv[1]))

    canvas = Image.new("RGB",
                       (canvas_w_cells * ROOM_W_PX,
                        canvas_h_cells * ROOM_H_PX),
                       (16, 16, 16))
    draw = ImageDraw.Draw(canvas)

    # Draw each room.
    for p in placements.values():
        room = rooms[p.room_id]
        room_img = render_room(room, category=category)
        ox, oy = comp_origin[p.component]
        px = (p.x + ox) * ROOM_W_PX
        py = (p.y + oy) * ROOM_H_PX
        canvas.paste(room_img, (px, py))

    # Per-room thin border so adjacent rooms read as distinct cells.
    grid_col = (60, 60, 60)
    for p in placements.values():
        ox, oy = comp_origin[p.component]
        px = (p.x + ox) * ROOM_W_PX
        py = (p.y + oy) * ROOM_H_PX
        draw.rectangle([px, py, px + ROOM_W_PX - 1, py + ROOM_H_PX - 1],
                       outline=grid_col)

    # Cross-edges: try to route an orthogonal connector through free
    # tiles between source-port and target-port. Falls back to a text
    # label when no path exists (e.g. ports themselves are occupied).
    font = _load_label_font(11)
    occ = _build_tile_occupancy(placements, comp_origin,
                                canvas_w_cells, canvas_h_cells)
    canvas_pos: dict[int, tuple[int, int]] = {}
    for p in placements.values():
        ox, oy = comp_origin[p.component]
        canvas_pos[p.room_id] = (p.x + ox, p.y + oy)

    routed = 0
    labelled = 0
    for ce in cross:
        if ce.src_id not in canvas_pos:
            continue
        sp_cx, sp_cy = canvas_pos[ce.src_id]
        color = (255, 220, 80) if ce.reason == 'occupied' else (255, 120, 120)
        path: list[tuple[int, int]] = []
        if ce.dst_id in canvas_pos:
            tp_cx, tp_cy = canvas_pos[ce.dst_id]
            src_tile = _port_tile(sp_cx, sp_cy, ce.direction)
            tgt_tile = _port_tile(tp_cx, tp_cy, _DIR_REVERSE[ce.direction])
            path = _route_orthogonal(occ, src_tile, tgt_tile)
        if path:
            corners = _path_corners(path)
            # Convert tile-grid coords to canvas pixel coords (tile centre).
            pix_pts = [
                (t[0] * TILE_PX + TILE_PX // 2,
                 t[1] * TILE_PX + TILE_PX // 2)
                for t in corners
            ]
            # Stub from the source room's edge midpoint to the first
            # routing tile, and from the last routing tile to the
            # target room's edge midpoint, so the line visually
            # docks against the rooms it connects.
            tp_cx, tp_cy = canvas_pos[ce.dst_id]
            src_edge = _edge_pixel(sp_cx, sp_cy, ce.direction)
            tgt_edge = _edge_pixel(tp_cx, tp_cy, _DIR_REVERSE[ce.direction])
            pts = [src_edge] + pix_pts + [tgt_edge]
            for i in range(len(pts) - 1):
                draw.line([pts[i], pts[i + 1]], fill=color, width=2)
            # Small dots at the two room-edge ports so the connector
            # reads as "exit → entry" rather than a stray scribble.
            for ex, ey in (src_edge, tgt_edge):
                draw.ellipse([ex - 2, ey - 2, ex + 2, ey + 2], fill=color)
            routed += 1
            continue
        # Fallback: label-only marker on the source's edge.
        labelled += 1
        ox, oy = comp_origin[placements[ce.src_id].component]
        px = (placements[ce.src_id].x + ox) * ROOM_W_PX
        py = (placements[ce.src_id].y + oy) * ROOM_H_PX
        if ce.direction == 0:
            ax, ay = px + 2, py + ROOM_H_PX // 2 - 6
        elif ce.direction == 1:
            ax, ay = px + ROOM_W_PX - 36, py + ROOM_H_PX // 2 - 6
        elif ce.direction == 2:
            ax, ay = px + ROOM_W_PX // 2 - 14, py + 2
        else:
            ax, ay = px + ROOM_W_PX // 2 - 14, py + ROOM_H_PX - 14
        label = f"{_DIR_NAMES[ce.direction]}->{ce.dst_id}"
        bbox = draw.textbbox((ax, ay), label, font=font)
        draw.rectangle([bbox[0] - 1, bbox[1] - 1, bbox[2] + 1, bbox[3] + 1],
                       fill=(0, 0, 0))
        draw.text((ax, ay), label, fill=color, font=font)

    if scale != 1:
        canvas = canvas.resize(
            (canvas.width * scale, canvas.height * scale),
            Image.NEAREST,
        )

    meta = {
        "engine": engine.name,
        "components": len(layout.comp_origin),
        "rooms_placed": len(placements),
        "cross_edges": len(cross),
        "cross_edge_reasons": {
            r: sum(1 for c in cross if c.reason == r)
            for r in ("conflict", "occupied")
        },
    }
    return canvas, meta


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("path", type=Path,
                   help="snapshot or tape (.z80/.sna/.szx/.tap/.tzx/.pzx)")
    p.add_argument("--out", type=Path, default=None,
                   help="output PNG (default: <input>.canonical.png)")
    p.add_argument("--scale", type=int, default=1,
                   help="integer pixel-scale factor for the final PNG")
    p.add_argument("--category", action="store_true",
                   help="render each cell with its tile-category colour "
                        "(see CANONICAL_TILE_CATEGORY_COLORS.md) instead of "
                        "the native ZX bitmap")
    args = p.parse_args(argv)

    snap = load_snapshot(args.path)
    engine = detect_engine(snap)
    if engine is None:
        print(f"{args.path}: no JSW engine variant matched")
        return 1
    img, meta = render_map(snap, engine, scale=args.scale,
                           category=args.category)
    suffix = ".category.png" if args.category else ".canonical.png"
    out = args.out or args.path.with_suffix(suffix)
    img.save(out)
    print(f"wrote {out}  ({img.width}x{img.height}, "
          f"{meta['rooms_placed']} rooms in {meta['components']} components, "
          f"{meta['cross_edges']} cross-edges)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
