#!/usr/bin/env python3
"""
JSW-style map image importer.

Imports a full-mansion screenshot of a JSW-engine map and produces analysis
artifacts that downstream tools use to assemble a JSWR map folder.

Subcommands:
  detect-metadata <input.png>
    Detect:
      - room grid (cells)
      - room titles (text below rooms, when present)
      - title screen
      - credits region
      - other small text annotations ("T2", "T3", "Out", etc.)
    Writes alongside the input:
      <input>.metadata.png   annotated overlay
      <input>.metadata.json  region list with bboxes + per-region confidence
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageDraw, ImageFont, ImageStat
from rapidocr_onnxruntime import RapidOCR


# JSW native room dimensions in game pixels.
NATIVE_ROOM_W = 256
NATIVE_ROOM_H = 128

# Common extra heights added below a room body for an under-room title strip.
# At native scale a single ZX font row is 8 px tall.
TITLE_STRIP_HEIGHTS_NATIVE = (0, 8, 9, 16, 24)

# Maximum border (in pixels at native scale) to tolerate around the playable
# grid. Maps may have a few px of margin on each side or a non-standard final
# row that doesn't perfectly tile.
MAX_BORDER_NATIVE = 64

# Pixel intensity below this is treated as background ("black").
BG_THRESHOLD = 8

# OCR upscale factor (nearest-neighbour). Bitmap font is ~8 px tall at native;
# rapidocr's detector wants larger characters.
OCR_UPSCALE = 3

# Drop OCR detections below this confidence as noise. Calibrated against
# Paris (real T1/T2/T3/Out hit ~0.85 raw) and JSW1 (false positives like
# "L1", "2.3" hit ~0.55-0.6 raw).
OCR_CONF_FLOOR = 0.6

# ZX Spectrum tile cell size in native game pixels. Each room is 32x16
# tile cells; each tile cell is one ZX attribute cell.
TILE_PX = 8

# A signature seen in this many tile cells (or this fraction of the room,
# whichever is larger) is treated as a structural tile rather than a
# sprite candidate. Calibrated against JSW rooms where bg/floor/wall/ramp
# typically each occupy >= 5 tiles.
STRUCTURAL_MIN_COUNT = 4
STRUCTURAL_MIN_FRAC = 0.04

# A full (paper, ink, bitmap) signature appearing in this many tile cells
# across the entire map is treated as a tile graphic regardless of
# in-room cluster shape. Tiles repeat; sprite frames captured in a still
# screenshot rarely line up bitmap-for-bitmap. Counter-case: items
# rendered into many rooms share a bitmap and so will be classed as
# tiles by this rule — accepted false-negative.
GLOBAL_TILE_REPEATS = 2

# When a sprite candidate cell's paper matches the room's predominant
# background colour, its bitmask is scanned across the WHOLE map at
# every pixel offset (not just tile-aligned). If at least this many
# matches are found, it is confirmed as a guardian — overriding the
# global-bitmap-repeat rule. Two marias in one room produce >= 2 matches.
GUARDIAN_BITMASK_MIN_MATCHES = 2


# ---------------------------------------------------------------------------
# Region model
# ---------------------------------------------------------------------------

REGION_TYPES = ("room", "room_title", "title", "credits", "annotation",
                "item", "guardian", "unknown")


@dataclass
class Region:
    type: str
    bbox: tuple[int, int, int, int]  # (x, y, w, h) in original-image pixels
    confidence: float                 # 0..1
    ocr_text: str = ""
    notes: str = ""
    # 1-based sequential id assigned to room regions in row-major order.
    # Set on type=="room" Regions and propagated to the matching
    # type=="room_title" Regions so users can refer to "Room 7" in feedback.
    room_number: int | None = None
    cell: tuple[int, int] | None = None  # (row, col) when applicable
    # Tile-cell coords (col, row) within the parent room's 32x16 tile grid.
    # Set on type=="item" / "guardian" Regions.
    tile_cell: tuple[int, int] | None = None
    # Set on type=="room" Regions: how cleanly the room's tile signatures
    # cluster (top few signatures dominate vs. long-tailed). 0..1.
    classification_confidence: float | None = None

    def to_json(self) -> dict:
        d = {
            "type": self.type,
            "bbox": list(self.bbox),
            "confidence": round(self.confidence, 3),
            "ocr_text": self.ocr_text,
            "notes": self.notes,
        }
        if self.room_number is not None:
            d["room_number"] = self.room_number
        if self.cell is not None:
            d["cell"] = list(self.cell)
        if self.tile_cell is not None:
            d["tile_cell"] = list(self.tile_cell)
        if self.classification_confidence is not None:
            d["classification_confidence"] = round(
                self.classification_confidence, 3
            )
        return d


def confidence_color(c: float) -> tuple[int, int, int]:
    """Map confidence 0..1 to a colour: red -> yellow -> green."""
    c = max(0.0, min(1.0, c))
    if c < 0.5:
        return (255, int(round(2 * c * 255)), 0)
    return (int(round((1 - 2 * (c - 0.5)) * 255)), 255, 0)


# ---------------------------------------------------------------------------
# Grid detection
# ---------------------------------------------------------------------------

@dataclass
class Grid:
    scale: int
    cell_w: int       # full cell width incl. any side margins (= room body width)
    cell_h: int       # full cell height incl. title strip
    title_strip: int  # height of under-room title strip (0 if none), in image px
    cols: int
    rows: int
    x_offset: int = 0  # pixels of left-margin before first cell
    y_offset: int = 0  # pixels of top-margin before first cell

    @property
    def body_h(self) -> int:
        return self.cell_h - self.title_strip

    def cell_origin(self, row: int, col: int) -> tuple[int, int]:
        return (self.x_offset + col * self.cell_w,
                self.y_offset + row * self.cell_h)

    def cell_at(self, x: int, y: int) -> tuple[int, int]:
        """Return (row, col) of the cell containing pixel (x, y).
        Caller is responsible for bounds-checking the result."""
        return ((y - self.y_offset) // self.cell_h,
                (x - self.x_offset) // self.cell_w)

    def to_json(self) -> dict:
        return {
            "scale": self.scale,
            "cell_w": self.cell_w,
            "cell_h": self.cell_h,
            "title_strip": self.title_strip,
            "cols": self.cols,
            "rows": self.rows,
            "x_offset": self.x_offset,
            "y_offset": self.y_offset,
        }


def detect_room_grid(im: Image.Image) -> Grid:
    """
    Detect the room cell pitch.

    Permissive: assumes JSW native room body is 256x128 (or scaled), but
    allows under-room title strips of 0/8/9/16/24 px and up to
    MAX_BORDER_NATIVE px of border/margin on each side. Some maps have
    1-2 px of mis-cropping, others have wider margins around the playable
    area when the title screen extends above the room rows.
    """
    w, h = im.size
    candidates: list[Grid] = []
    for scale in (1, 2, 3, 4):
        cell_w = NATIVE_ROOM_W * scale
        if w < cell_w * 2:
            continue
        max_border_x = MAX_BORDER_NATIVE * scale
        # Possible column counts. Prefer no border, then small border.
        for cols in range(2, w // cell_w + 1):
            border_x = w - cols * cell_w
            if border_x < 0 or border_x > max_border_x:
                continue
            for ts_native in TITLE_STRIP_HEIGHTS_NATIVE:
                cell_h = (NATIVE_ROOM_H + ts_native) * scale
                if h < cell_h * 2:
                    continue
                max_border_y = MAX_BORDER_NATIVE * scale
                for rows in range(2, h // cell_h + 1):
                    border_y = h - rows * cell_h
                    if border_y < 0 or border_y > max_border_y:
                        continue
                    n_cells = cols * rows
                    if not (4 <= n_cells <= 1500):
                        continue
                    candidates.append(Grid(
                        scale=scale,
                        cell_w=cell_w,
                        cell_h=cell_h,
                        title_strip=ts_native * scale,
                        cols=cols,
                        rows=rows,
                        x_offset=border_x // 2,
                        y_offset=border_y // 2,
                    ))
    if not candidates:
        raise SystemExit(
            f"Could not detect JSW room grid for image {w}x{h}.\n"
            f"No (cell_w, cell_h) combo produced an integer-cell tiling "
            f"with border <= {MAX_BORDER_NATIVE} px on each side."
        )

    # Score each candidate. Lower score = better.
    def score(g: Grid) -> tuple:
        n_cells = g.cols * g.rows
        border_x = w - g.cols * g.cell_w
        border_y = h - g.rows * g.cell_h
        total_border = border_x + border_y
        # Prefer 8-px title strip (commonest), then 0, then others.
        ts_pref = {8: 0, 0: 1, 9: 2, 16: 3, 24: 4}.get(
            g.title_strip // g.scale, 5
        )
        # Prefer cell counts in ~30..600 range.
        if 30 <= n_cells <= 600:
            count_pref = 0
        elif n_cells < 30:
            count_pref = 30 - n_cells
        else:
            count_pref = (n_cells - 600) // 50
        # Prefer scale=1 (most JSW maps are at native) over higher scales.
        return (total_border, ts_pref, count_pref, g.scale, -n_cells)

    candidates.sort(key=score)
    return candidates[0]


# ---------------------------------------------------------------------------
# Cell / floor analysis
# ---------------------------------------------------------------------------

def cell_density(im_l: Image.Image, x: int, y: int, w: int, h: int) -> float:
    """Fraction of pixels brighter than BG_THRESHOLD inside the rect."""
    cell = im_l.crop((x, y, x + w, y + h))
    hist = cell.histogram()
    total = w * h
    bg = sum(hist[: BG_THRESHOLD + 1])
    return (total - bg) / total if total else 0.0


def has_floor(im_l: Image.Image, x: int, y: int, w: int, h: int,
              scale: int) -> bool:
    """
    Detect a horizontal "floor band" near the bottom of the room body.

    Floors in JSW rooms are a continuous horizontal stripe of solid tile
    spanning most of the room width. We look at the bottom 4 native px
    (= 4 * scale image px) of the body for a row that is non-background
    across at least 70% of the width.
    """
    band_h = 4 * scale
    band_top = y + h - band_h
    px = im_l.load()
    threshold = max(1, int(round(w * 0.7)))
    for row_y in range(band_top, y + h):
        run = 0
        max_run = 0
        for col_x in range(x, x + w):
            if px[col_x, row_y] > BG_THRESHOLD:
                run += 1
                if run > max_run:
                    max_run = run
            else:
                run = 0
        if max_run >= threshold:
            return True
    return False


def classify_cells(
    im: Image.Image, grid: Grid
) -> tuple[list[list[str]], list[list[bool]], list[list[float]]]:
    """
    Walk every grid cell and tag it as "empty" or "room".

    JSW maps don't always have a clear floor band — guardian-only rooms,
    sky-themed rooms, vortex rooms, etc. So the floor check is recorded
    as a separate signal (used later as one input into title/credits
    detection) but NOT used to gate the room/empty classification.

    Returns:
      cell_kind        - 2D grid [row][col] of "empty" | "room"
      has_floor_grid   - 2D bool grid (True if a floor band was detected)
      density_grid     - 2D float grid of body-pixel densities
    """
    im_l = im.convert("L")
    cell_kind: list[list[str]] = [
        ["empty"] * grid.cols for _ in range(grid.rows)
    ]
    has_floor_grid: list[list[bool]] = [
        [False] * grid.cols for _ in range(grid.rows)
    ]
    density_grid: list[list[float]] = [
        [0.0] * grid.cols for _ in range(grid.rows)
    ]
    for row in range(grid.rows):
        for col in range(grid.cols):
            x, y = grid.cell_origin(row, col)
            body_h = grid.body_h
            density = cell_density(im_l, x, y, grid.cell_w, body_h)
            density_grid[row][col] = density
            if density < 0.001:
                continue
            cell_kind[row][col] = "room"
            has_floor_grid[row][col] = has_floor(
                im_l, x, y, grid.cell_w, body_h, grid.scale
            )
    return cell_kind, has_floor_grid, density_grid


def build_room_regions(grid: Grid, cell_kind: list[list[str]],
                       has_floor_grid: list[list[bool]],
                       density_grid: list[list[float]]
                       ) -> tuple[list[Region], dict[tuple[int, int], int]]:
    """
    Emit a Region for every cell currently tagged 'room'. Rooms are numbered
    sequentially in row-major order (1-based) so the user can refer to
    rooms by number in feedback.

    Returns (regions, cell_to_number) where cell_to_number maps (row, col)
    to the assigned room_number — useful for cross-referencing room titles
    and other related regions.
    """
    out: list[Region] = []
    cell_to_number: dict[tuple[int, int], int] = {}
    next_n = 1
    for row in range(grid.rows):
        for col in range(grid.cols):
            if cell_kind[row][col] != "room":
                continue
            x, y = grid.cell_origin(row, col)
            density = density_grid[row][col]
            floor = has_floor_grid[row][col]
            conf = 0.85 if floor else 0.65
            cell_to_number[(row, col)] = next_n
            out.append(Region(
                type="room",
                bbox=(x, y, grid.cell_w, grid.body_h),
                confidence=conf,
                room_number=next_n,
                cell=(row, col),
                notes=f"density={density:.3f} "
                      f"floor={'yes' if floor else 'no'}",
            ))
            next_n += 1
    return out, cell_to_number


# ---------------------------------------------------------------------------
# Title-screen / credits region detection
# ---------------------------------------------------------------------------

# OCR text fragments that strongly suggest a title-screen / author credits
# block. Lower-cased; tolerant of common ZX-font OCR misreads (e.g. ENTER
# often comes through as EMTER, speccy as specch).
TITLE_KEYWORDS = (
    "created",
    "http",
    "speccy",
    "specch",
    "maps.",
    "+++++",
    "press",
    "prss",
    "enter",
    "emter",
    "presents",
)


def _detect_title_keyword_cells(grid: Grid,
                                words: list[dict]) -> set[tuple[int, int]]:
    """Cells whose OCR text contains a title-screen keyword."""
    out: set[tuple[int, int]] = set()
    for w in words:
        text = (w["text"] or "").lower()
        if not any(kw in text for kw in TITLE_KEYWORDS):
            continue
        bx, by, bw, bh = w["bbox"]
        row, col = grid.cell_at(bx + bw // 2, by + bh // 2)
        if 0 <= col < grid.cols and 0 <= row < grid.rows:
            out.add((row, col))
    return out


def _all_cell_clusters(cells: set[tuple[int, int]],
                       tolerance: int = 2
                       ) -> list[set[tuple[int, int]]]:
    """
    Cluster cells by spatial proximity. Two cells are in the same cluster
    if their Chebyshev distance is <= `tolerance`. Returns clusters sorted
    by size descending.
    """
    remaining = set(cells)
    clusters: list[set[tuple[int, int]]] = []
    while remaining:
        seed = next(iter(remaining))
        cluster = {seed}
        frontier = [seed]
        remaining.discard(seed)
        while frontier:
            r, c = frontier.pop()
            to_add = [
                (rr, cc) for (rr, cc) in remaining
                if max(abs(rr - r), abs(cc - c)) <= tolerance
            ]
            for cell in to_add:
                cluster.add(cell)
                frontier.append(cell)
                remaining.discard(cell)
        clusters.append(cluster)
    clusters.sort(key=lambda c: -len(c))
    return clusters


def _looks_like_titled_room(strip_text: str, strip_conf: float) -> bool:
    """
    Heuristic: does this strip OCR result look like a real room title
    (consistent with a normal playable room) rather than garbage / empty?

    Used by title detection to reject keyword clusters where every cell
    is in fact a regular room whose strip happens to contain a title-like
    word.
    """
    if strip_conf < 0.7:
        return False
    s = (strip_text or "").strip()
    if len(s) < 3:
        return False
    if not _is_ascii_text(s):
        return False
    # Mostly punctuation? Probably not a room title.
    alnum = sum(1 for c in s if c.isalnum())
    return alnum / len(s) >= 0.5


def _expand_title_bbox(bbox_cells: tuple[int, int, int, int],
                       cell_kind: list[list[str]],
                       has_floor_grid: list[list[bool]],
                       strip_titles: dict[tuple[int, int], dict],
                       grid: Grid,
                       max_extra: int = 4) -> tuple[int, int, int, int]:
    """
    Extend the title's keyword-cell bbox to pick up logo / decoration
    cells that frame the keyword text on all sides.

    Vertical-up uses a loose density criterion (3D logo edges often
    falsely trigger has_floor). Vertical-down is strict (no-floor) to
    avoid sucking the playable mansion below the title into the title.

    Horizontal expansion uses *strip-title presence* as a negative
    signal: a column is included only if no cell in the title's row
    span has a real strip-OCR room title there. Real titled rooms are
    obviously not part of the title screen, while title-frame cells
    (logo arms / overflow text) have no strip title even though they
    contain pixels.
    """
    rmin, cmin, rmax, cmax = bbox_cells

    def is_real_room(r: int, c: int) -> bool:
        if (r, c) not in strip_titles:
            return False
        v = strip_titles[(r, c)]
        return _looks_like_titled_room(v.get("text", ""), v.get("conf", 0.0))

    def row_loose(r: int) -> float:
        if r < 0 or r >= grid.rows:
            return 0.0
        n = cmax - cmin + 1
        if n <= 0:
            return 0.0
        return sum(1 for c in range(cmin, cmax + 1)
                   if cell_kind[r][c] in ("room", "title")) / n

    def row_strict(r: int) -> float:
        if r < 0 or r >= grid.rows:
            return 0.0
        n = cmax - cmin + 1
        if n <= 0:
            return 0.0
        return sum(1 for c in range(cmin, cmax + 1)
                   if cell_kind[r][c] in ("room", "title")
                   and not has_floor_grid[r][c]) / n

    def col_admissible(c: int) -> bool:
        if c < 0 or c >= grid.cols:
            return False
        # If ANY cell in this column's title-row span is a real titled
        # room, this column is part of the playable mansion — don't
        # absorb it.
        for r in range(rmin, rmax + 1):
            if is_real_room(r, c):
                return False
        # Must have at least one non-empty cell in the title-row span,
        # otherwise we're expanding into pure void.
        return any(
            cell_kind[r][c] in ("room", "title")
            for r in range(rmin, rmax + 1)
        )

    # Vertical: up loose, down strict.
    for _ in range(max_extra):
        if row_loose(rmin - 1) >= 0.3:
            rmin -= 1
        else:
            break
    for _ in range(max_extra):
        if row_strict(rmax + 1) >= 0.5:
            rmax += 1
        else:
            break

    # Horizontal: expand into any column whose title-row cells are
    # neither real titled rooms nor entirely empty.
    for _ in range(max_extra):
        if col_admissible(cmin - 1):
            cmin -= 1
        else:
            break
    for _ in range(max_extra):
        if col_admissible(cmax + 1):
            cmax += 1
        else:
            break

    return (rmin, cmin, rmax, cmax)


def detect_title_screens(
    grid: Grid,
    cell_kind: list[list[str]],
    has_floor_grid: list[list[bool]],
    words: list[dict] | None = None,
    strip_titles: dict[tuple[int, int], dict] | None = None,
) -> list[Region]:
    """
    Detect title-screen block(s). Some maps (e.g. JSWX) have more than one
    title block, so this returns a list.

    Strategy: find cells whose OCR contains title-screen keywords, cluster
    them spatially, then *filter out* clusters whose cells all have real
    per-strip room titles — those clusters are just regular playable rooms
    whose strip text happens to contain a title-like word, not actual
    title-screen cells.

    A surviving cluster's bbox is then expanded to include adjacent
    logo / decoration cells.

    Falls back to the legacy top-left no-floor grow when OCR isn't
    available.
    """
    rows, cols = grid.rows, grid.cols
    if not rows or not cols:
        return []

    strip_titles = strip_titles or {}

    if words:
        kw_cells = _detect_title_keyword_cells(grid, words)
        if kw_cells:
            clusters = _all_cell_clusters(kw_cells, tolerance=2)
            out: list[Region] = []
            for cluster in clusters:
                if len(cluster) < 2:
                    continue
                # Filter: if every cell in the cluster has a strong room-
                # title detection in its strip, this cluster is just a
                # group of normal rooms whose body OCR happened to contain
                # a keyword — not a title screen.
                titled = sum(
                    1 for cell in cluster
                    if cell in strip_titles
                    and _looks_like_titled_room(
                        strip_titles[cell].get("text", ""),
                        strip_titles[cell].get("conf", 0.0),
                    )
                )
                if titled / len(cluster) >= 0.5:
                    continue
                rs = [r for r, _ in cluster]
                cs = [c for _, c in cluster]
                rmin, rmax = min(rs), max(rs)
                cmin, cmax = min(cs), max(cs)
                rmin, cmin, rmax, cmax = _expand_title_bbox(
                    (rmin, cmin, rmax, cmax),
                    cell_kind, has_floor_grid, strip_titles, grid,
                )
                x0, y0 = grid.cell_origin(rmin, cmin)
                bbox = (
                    x0, y0,
                    (cmax - cmin + 1) * grid.cell_w,
                    (rmax - rmin + 1) * grid.cell_h,
                )
                out.append(Region(
                    type="title",
                    bbox=bbox,
                    confidence=0.75,
                    notes=(f"OCR keyword cluster: {len(cluster)} cells "
                           f"({titled} with strip titles), "
                           f"rows {rmin}..{rmax} cols {cmin}..{cmax}"),
                ))
            if out:
                return out

    # Fallback: top-left greedy grow over floor-less rooms.
    if cell_kind[0][0] != "room" or has_floor_grid[0][0]:
        return []

    def is_title_like(r: int, c: int) -> bool:
        return cell_kind[r][c] == "room" and not has_floor_grid[r][c]

    cmax = 0
    while cmax + 1 < cols and is_title_like(0, cmax + 1):
        cmax += 1
    rmax = 0
    while rmax + 1 < rows and all(
        is_title_like(rmax + 1, c) for c in range(cmax + 1)
    ):
        rmax += 1
    x0, y0 = grid.cell_origin(0, 0)
    bbox = (x0, y0, (cmax + 1) * grid.cell_w, (rmax + 1) * grid.cell_h)
    return [Region(
        type="title",
        bbox=bbox,
        confidence=0.55,
        notes=f"top-left contiguous floor-less rooms {cmax + 1}x{rmax + 1}",
    )]


# Glyph-height thresholds (in original-image native px). Calibrated for
# scale=1; for >1x maps these scale up automatically below.
GLYPH_H_SMALL_MAX = 16   # at or below = small annotation / room title
GLYPH_H_LARGE_MIN = 24   # at or above = large stylized / tile-spelled


# How many bottom rows the credits-detector considers. Credits in JSW maps
# almost always live on the last row; allow a small buffer for safety.
CREDITS_BOTTOM_ROWS = 2

# Keywords whose presence in a room title strongly suggests a credits cell.
CREDITS_KEYWORDS = (
    " by ",
    "presents",
    "created",
    "dedicated",
    "thanks",
    " fin ",
    "the end",
    "credits",
)

_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")


def _extract_long_words(text: str) -> set[str]:
    """Lower-cased alphabetic tokens of length >= 4 (for word overlap)."""
    return set(re.findall(r"[a-z]{4,}", text.lower()))


def _credits_signal(title_text: str,
                    title_screen_words: set[str]) -> tuple[bool, str]:
    """
    Decide whether a candidate credits cell's room title looks credits-like.

    A "yes" requires explicit evidence (year, credit keyword, or word-overlap
    with the title screen). An empty / unrelated title returns "no" — biased
    toward classifying as a room when uncertain (per user guidance: false-
    negative on credits is preferable to false-positive).
    """
    if not title_text:
        return False, "no title-strip text"
    s = title_text.lower()
    if _YEAR_RE.search(s):
        return True, "year in title"
    for kw in CREDITS_KEYWORDS:
        if kw in s:
            return True, f"credit keyword '{kw.strip()}' in title"
    overlap = _extract_long_words(title_text) & title_screen_words
    if overlap:
        return True, f"title-screen word overlap: {sorted(overlap)}"
    return False, "no credit signal"


def _title_screen_words(words: list[dict],
                        title_region: Region | None) -> set[str]:
    """Long lowercased tokens from OCR detections inside the title block."""
    if title_region is None:
        return set()
    tx, ty, tw, th = title_region.bbox
    out: set[str] = set()
    for w in words:
        bx, by, bw, bh = w["bbox"]
        cx, cy = bx + bw // 2, by + bh // 2
        if not (tx <= cx < tx + tw and ty <= cy < ty + th):
            continue
        out |= _extract_long_words(w["text"] or "")
    return out


def detect_credits(grid: Grid,
                   words: list[dict],
                   cell_kind: list[list[str]],
                   strip_titles: dict[tuple[int, int], dict],
                   title_screen_words: set[str]) -> list[Region]:
    """
    Per-cell credits detection. A cell is flagged as credits only when:
      1. it lies in the bottom CREDITS_BOTTOM_ROWS rows of the grid, AND
      2. its body contains an OCR detection with glyph height >=
         GLYPH_H_LARGE_MIN (scaled), AND
      3. its under-room title strip yields a credits signal — either a
         4-digit year, a known credit keyword, or word-overlap with the
         title-screen text (per user feedback: correlate room titles
         against the title-screen credits).

    Bias is intentionally toward NOT flagging: the user prefers a credits
    cell mis-tagged as a room over a real room mis-tagged as credits.
    """
    threshold = GLYPH_H_LARGE_MIN * grid.scale
    bottom_first_row = max(0, grid.rows - CREDITS_BOTTOM_ROWS)
    flagged: dict[tuple[int, int], float] = {}
    for w in words:
        bx, by, bw, bh = w["bbox"]
        if bh < threshold:
            continue
        cx, cy = bx + bw // 2, by + bh // 2
        row, col = grid.cell_at(cx, cy)
        if not (0 <= col < grid.cols and 0 <= row < grid.rows):
            continue
        if row < bottom_first_row:
            continue
        if cell_kind[row][col] != "room":
            continue
        y_in_cell = cy - (grid.y_offset + row * grid.cell_h)
        if y_in_cell >= grid.body_h:
            continue
        flagged[(row, col)] = max(flagged.get((row, col), 0), bh)

    out: list[Region] = []
    for (row, col), max_h in flagged.items():
        title_info = strip_titles.get((row, col))
        title_text = title_info["text"] if title_info else ""
        is_credits, reason = _credits_signal(title_text, title_screen_words)
        if not is_credits:
            continue
        x, y = grid.cell_origin(row, col)
        out.append(Region(
            type="credits",
            bbox=(x, y, grid.cell_w, grid.body_h),
            confidence=0.65,
            ocr_text=title_text,
            cell=(row, col),
            notes=f"big glyph (h={max_h}) + {reason}",
        ))
    return out


# ---------------------------------------------------------------------------
# OCR
# ---------------------------------------------------------------------------

def _bbox_from_quad(quad) -> tuple[int, int, int, int]:
    xs = [int(p[0]) for p in quad]
    ys = [int(p[1]) for p in quad]
    return (min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))


def _bbox_iou(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    x1, y1 = max(ax, bx), max(ay, by)
    x2, y2 = min(ax + aw, bx + bw), min(ay + ah, by + bh)
    if x1 >= x2 or y1 >= y2:
        return 0.0
    inter = (x2 - x1) * (y2 - y1)
    union = aw * ah + bw * bh - inter
    return inter / union if union > 0 else 0.0


def _tile_is_empty(tile_l: Image.Image, threshold: float = 0.005) -> bool:
    """Tile is mostly background (skip OCR)."""
    hist = tile_l.histogram()
    total = tile_l.width * tile_l.height
    bg = sum(hist[: BG_THRESHOLD + 1])
    return total == 0 or (total - bg) / total < threshold


def ocr_room_title_strips(
    im: Image.Image,
    grid: Grid,
    cell_kind: list[list[str]],
    upscale: int = 3,
    progress: bool = True,
) -> dict[tuple[int, int], dict]:
    """
    Focused OCR on the under-room title strip of every non-empty 'room' cell.

    JSW-style maps that use under-room titles place each room's name in a
    single horizontal strip immediately below the room body (typically 8 px
    tall at native scale). We crop each strip individually and OCR it as a
    single block — much more accurate than letting the global tiled pass
    detect them piecemeal, which tends to fragment or miss them.

    Returns a dict keyed by (row, col) -> { 'text', 'bbox', 'conf' } in
    ORIGINAL-image pixel coordinates.
    """
    if grid.title_strip <= 0:
        return {}
    import numpy as np
    engine = RapidOCR()
    im_l = im.convert("L")
    out: dict[tuple[int, int], dict] = {}
    strip_h = grid.title_strip
    body_h = grid.body_h
    pad_top = min(2 * grid.scale, body_h)  # context line above the strip

    candidates = [
        (r, c)
        for r in range(grid.rows)
        for c in range(grid.cols)
        if cell_kind[r][c] == "room"
    ]
    total = len(candidates)
    done = 0
    skipped_empty = 0
    found = 0
    for row, col in candidates:
        done += 1
        x, y_cell = grid.cell_origin(row, col)
        y_strip = y_cell + body_h
        if cell_density(im_l, x, y_strip, grid.cell_w, strip_h) < 0.01:
            skipped_empty += 1
            if progress and done % 40 == 0:
                print(f"    strip {done}/{total} "
                      f"(empty={skipped_empty} found={found})")
            continue
        strip = im.crop(
            (x, y_strip - pad_top, x + grid.cell_w, y_strip + strip_h)
        )
        big = strip.resize(
            (strip.width * upscale, strip.height * upscale),
            Image.NEAREST,
        )
        arr = np.asarray(big.convert("RGB"))
        # Run detection + recognition; combine all detections into a single
        # left-to-right line. rapidocr's detector often fragments a single
        # room title ("The Bathroom" -> "The" + "Bathroom"); we glue them
        # back together rather than taking the single highest-conf piece.
        result, _ = engine(arr)
        if not result:
            if progress and done % 40 == 0:
                print(f"    strip {done}/{total} "
                      f"(empty={skipped_empty} found={found})")
            continue
        ordered = sorted(
            ((d[0], d[1] or "", float(d[2])) for d in result),
            key=lambda d: _bbox_from_quad(d[0])[0],
        )
        pieces = [t.strip() for _, t, _ in ordered if t.strip()]
        if not pieces:
            if progress and done % 40 == 0:
                print(f"    strip {done}/{total} "
                      f"(empty={skipped_empty} found={found})")
            continue
        combined = " ".join(pieces)
        # Bbox spans from the leftmost detection's x to the rightmost
        # detection's right edge, with y from the union.
        xs1, ys1, xs2, ys2 = [], [], [], []
        for quad, _, _ in ordered:
            qx, qy, qw, qh = _bbox_from_quad(quad)
            xs1.append(qx); ys1.append(qy)
            xs2.append(qx + qw); ys2.append(qy + qh)
        bx_big, by_big = min(xs1), min(ys1)
        bw_big, bh_big = max(xs2) - bx_big, max(ys2) - by_big
        ox = x + bx_big // upscale
        oy = (y_strip - pad_top) + by_big // upscale
        ow = max(1, bw_big // upscale)
        oh = max(1, bh_big // upscale)
        avg_conf = sum(c for _, _, c in ordered) / len(ordered)
        out[(row, col)] = {
            "text": combined,
            "bbox": (ox, oy, ow, oh),
            "conf": avg_conf,
        }
        found += 1
        if progress and done % 40 == 0:
            print(f"    strip {done}/{total} "
                  f"(empty={skipped_empty} found={found})")
    if progress:
        print(f"    {total} strips: {found} titled, "
              f"{skipped_empty} empty, "
              f"{total - found - skipped_empty} no-text")
    return out


def ocr_image(
    im: Image.Image,
    upscale: int = OCR_UPSCALE,
    tile_size: int = 960,
    overlap: int = 96,
    progress: bool = True,
) -> list[dict]:
    """
    Run OCR on a nearest-neighbour upscale of the image, tiled to keep each
    tile within rapidocr's preferred input size (so the detector doesn't
    silently down-rescale and lose small bitmap-font text).

    Returns word-ish detections with bboxes mapped back to ORIGINAL coords.
    """
    # numpy is a transitive dep via rapidocr-onnxruntime; rapidocr's __call__
    # only accepts ndarray / bytes / str / Path so PIL is out.
    import numpy as np

    big = im.resize((im.width * upscale, im.height * upscale), Image.NEAREST)
    big_l = big.convert("L")
    engine = RapidOCR()

    W, H = big.size
    step = tile_size - overlap
    xs = list(range(0, max(1, W - tile_size + 1), step)) or [0]
    ys = list(range(0, max(1, H - tile_size + 1), step)) or [0]
    if xs[-1] + tile_size < W:
        xs.append(W - tile_size)
    if ys[-1] + tile_size < H:
        ys.append(H - tile_size)
    total_tiles = len(xs) * len(ys)
    done = 0
    skipped = 0

    raw: list[dict] = []
    for y0 in ys:
        for x0 in xs:
            done += 1
            x1, y1 = min(x0 + tile_size, W), min(y0 + tile_size, H)
            if _tile_is_empty(big_l.crop((x0, y0, x1, y1))):
                skipped += 1
                if progress and done % 20 == 0:
                    print(f"    tile {done}/{total_tiles} (skipped: {skipped})")
                continue
            tile = big.crop((x0, y0, x1, y1))
            arr = np.asarray(tile)
            result, _ = engine(arr)
            if progress and done % 20 == 0:
                print(f"    tile {done}/{total_tiles} (skipped: {skipped})")
            if not result:
                continue
            for quad, text, conf in result:
                bx, by, bw, bh = _bbox_from_quad(quad)
                raw.append({
                    "bbox_big": (bx + x0, by + y0, bw, bh),
                    "text": text or "",
                    "conf": float(conf),
                })

    # Dedupe overlap-region duplicates: IoU > 0.4 -> keep highest confidence.
    raw.sort(key=lambda d: -d["conf"])
    kept: list[dict] = []
    for d in raw:
        if any(_bbox_iou(d["bbox_big"], k["bbox_big"]) > 0.4 for k in kept):
            continue
        kept.append(d)

    out: list[dict] = []
    for d in kept:
        bx, by, bw, bh = d["bbox_big"]
        out.append({
            "bbox": (bx // upscale, by // upscale,
                     max(1, bw // upscale), max(1, bh // upscale)),
            "text": d["text"],
            "conf": d["conf"],
        })
    if progress:
        print(f"    {done}/{total_tiles} tiles processed, "
              f"{skipped} empty-skipped, "
              f"{len(raw)} raw -> {len(out)} after dedup")
    return out


def _is_ascii_text(s: str) -> bool:
    """True if every non-whitespace character is in the printable ASCII range."""
    s = s.strip()
    if not s:
        return False
    return all(0x20 <= ord(c) <= 0x7E for c in s)


def _looks_like_real_annotation(text: str) -> tuple[bool, str]:
    """
    Heuristic for distinguishing real annotation labels (T2, T3, Out, *)
    from OCR noise hallucinated on tile patterns and decorative content.
    Returns (is_real, reason).

    Known real-annotation forms observed:
      - T-numbered tags (T1, T2, T3)
      - Short words (Out, ENTRY, EXIT)
      - Asterisk markers (*, **) — JSW1 uses these to indicate
        "gap between rooms is gameplay-irrelevant; rooms are adjacent"

    Common OCR noise to drop:
      - pure digits ("202", "54", "00")  - tile pattern hallucinations
      - dominant-char-repeated ("LLL", "PPPR")
      - punctuation-only runs ("...", "#+")
    """
    s = text.strip()
    if not s:
        return False, "empty"
    # Asterisk-only markers (any length) are kept as gap-adjacency indicators.
    if all(c == "*" for c in s):
        return True, ""
    if len(s) < 2:
        return False, "single non-asterisk char"
    alnum = sum(1 for c in s if c.isalnum())
    if alnum / len(s) < 0.5:
        return False, "<50% alphanumeric"
    if s.isdigit():
        return False, "all digits (likely tile-pattern noise)"
    letters_lc = "".join(c for c in s if c.isalnum()).lower()
    if letters_lc:
        max_repeat = max(letters_lc.count(c) for c in set(letters_lc))
        if max_repeat / len(letters_lc) >= 0.7:
            return False, "dominant char >=70% (likely tile pattern)"
    return True, ""


def classify_ocr(words: list[dict], grid: Grid,
                 cell_kind: list[list[str]],
                 skip_title_strips: bool = False) -> list[Region]:
    """
    Convert OCR detections into Regions by glyph height and grid position.

    Filtering:
      - drop empty / sub-OCR_CONF_FLOOR / non-ASCII / single-char
      - drop detections inside title or credits cells (already labelled)
      - drop annotations that fail _looks_like_real_annotation
        (filters tile-pattern noise like '202', 'LLL', '#+', '...')
      - if skip_title_strips, also drop detections in any under-room
        title strip — room titles are handled by ocr_room_title_strips

    Categorisation:
      - text in the under-room title strip (small glyphs)  -> room_title
      - small glyphs (<=GLYPH_H_SMALL_MAX) in a room body  -> annotation
      - large glyphs (>=GLYPH_H_LARGE_MIN)                 -> SUPPRESSED
      - mid-sized glyphs                                   -> annotation
        (lower confidence — uncertain category)
    """
    out: list[Region] = []
    small_max = GLYPH_H_SMALL_MAX * grid.scale
    large_min = GLYPH_H_LARGE_MIN * grid.scale

    for w in words:
        text = w["text"].strip()
        if not text:
            continue
        ocr_conf = max(0.0, min(1.0, w["conf"]))
        if ocr_conf < OCR_CONF_FLOOR:
            continue
        if not _is_ascii_text(text):
            continue

        bx, by, bw, bh = w["bbox"]
        cx = bx + bw // 2
        cy = by + bh // 2
        row, col = grid.cell_at(cx, cy)
        in_grid = 0 <= col < grid.cols and 0 <= row < grid.rows

        if in_grid and cell_kind[row][col] in ("title", "credits"):
            continue

        y_in_cell = (cy - (grid.y_offset + row * grid.cell_h)
                     if in_grid else -1)
        in_title_strip = (
            in_grid and grid.title_strip > 0 and y_in_cell >= grid.body_h
        )
        glyph_h = bh

        if in_title_strip:
            if skip_title_strips:
                continue
            if glyph_h > small_max:
                continue
            out.append(Region(
                type="room_title",
                bbox=(bx, by, bw, bh),
                confidence=0.55 + 0.4 * ocr_conf,
                ocr_text=text,
                notes=f"under-room title strip (h={glyph_h})",
            ))
            continue

        if glyph_h >= large_min:
            continue  # tile-spelled / stylized

        # Annotation candidate — apply real-annotation heuristics.
        is_real, reason = _looks_like_real_annotation(text)
        if not is_real:
            continue

        if glyph_h <= small_max:
            out.append(Region(
                type="annotation",
                bbox=(bx, by, bw, bh),
                confidence=0.45 + 0.4 * ocr_conf,
                ocr_text=text,
                notes=f"small text in room (h={glyph_h})",
            ))
        else:
            out.append(Region(
                type="annotation",
                bbox=(bx, by, bw, bh),
                confidence=0.30 + 0.3 * ocr_conf,
                ocr_text=text,
                notes=f"medium text (h={glyph_h}) — ambiguous size",
            ))
    return out


# ---------------------------------------------------------------------------
# Tile / sprite classification (items + guardians)
# ---------------------------------------------------------------------------
#
# Strategy: per detected room, downsample to native 256x128, split into
# 32x16 of 8x8 tile cells, compute a (paper, ink, bitmap) signature per
# cell using ZX Spectrum 4-bit attribute quantisation. The most-frequent
# signatures in the room are structural tiles (background / floor / wall /
# ramp / conveyor); rare signatures (especially with bright vivid ink) are
# sprite overlays — items if isolated, guardians if part of a small
# 4-connected cluster.
#
# Two confidence scores come out:
#   * per-cell sprite confidence (red->yellow->green outline) combining
#     signature rarity + attribute saturation/brightness + cluster shape
#   * per-room classification confidence reflecting how cleanly the
#     signature distribution separates structural from rare


# ZX Spectrum 8-color base palette (normal-brightness form). In BRIGHT
# variants each non-zero channel becomes 0xFF instead of 0xCD. Black is
# the same in both brightnesses.
_ZX_NAMES = ("black", "blue", "red", "magenta",
             "green", "cyan", "yellow", "white")

# ZX color-index bit layout: bit 2 = green, bit 1 = red, bit 0 = blue.
# Color indices that read as visually "vivid" / sprite-like ink colors.
_VIVID_INKS = {3, 5, 6, 7}  # magenta, cyan, yellow, white

# Bright threshold for max-channel intensity — between 0xCD (normal) and
# 0xFF (bright). We allow some headroom for screenshot variation.
_BRIGHT_MIN = 0xE0


def _quantize_full_map(im: Image.Image, grid: Grid):
    """
    Quantise the entire image to ZX 4-bit attribute codes at native game-
    pixel resolution. Returns a uint8 (H_native, W_native) array used by
    the cross-map silhouette scan.
    """
    import numpy as np
    arr = np.asarray(im.convert("RGB"))
    s = grid.scale
    half = s // 2
    body = arr[half::s, half::s]
    r = body[:, :, 0]
    g = body[:, :, 1]
    b = body[:, :, 2]
    color = (((g >= 128).astype(np.uint8) << 2) |
             ((r >= 128).astype(np.uint8) << 1) |
             ((b >= 128).astype(np.uint8)))
    bright = ((np.maximum(np.maximum(r, g), b) >= _BRIGHT_MIN) &
              (color > 0)).astype(np.uint8)
    return (color.astype(np.uint8) << 1) | bright


def _all_8x8_bitmasks(silhouette):
    """
    For every (y, x) position in the native silhouette map, compute the
    64-bit packed bitmask of the 8x8 window starting at that pixel.
    Returns a uint64 (H-7, W-7) array. Bit (dy*8 + dx) is set when the
    pixel at (y+dy, x+dx) is non-bg.

    Vectorised via slicing — 64 numpy ops, no Python per-pixel loops.
    """
    import numpy as np
    H, W = silhouette.shape
    bmasks = np.zeros((H - 7, W - 7), dtype=np.uint64)
    for dy in range(8):
        for dx in range(8):
            bit = np.uint64(1) << np.uint64(dy * 8 + dx)
            bmasks |= silhouette[dy:H - 7 + dy,
                                 dx:W - 7 + dx].astype(np.uint64) * bit
    return bmasks


def _quantize_room(im: Image.Image, grid: Grid,
                   x: int, y: int, w: int, h: int):
    """
    Sample the room body at native game-pixel resolution and quantise each
    pixel to a ZX 4-bit attribute code (3 bits color + 1 bit brightness).

    Returns a numpy uint8 array of shape (rows_t * 8, cols_t * 8) where
    each entry is in [0..15] — the per-pixel ZX attribute. Caller reshapes
    into 8x8 tiles.
    """
    import numpy as np
    arr = np.asarray(im.convert("RGB"))
    s = grid.scale
    # Take centre of each scaled block.
    half = s // 2
    body = arr[y + half: y + h: s, x + half: x + w: s]
    if body.shape[0] < 8 or body.shape[1] < 8:
        return None
    # Trim to a multiple of TILE_PX in each dimension.
    Hn = (body.shape[0] // TILE_PX) * TILE_PX
    Wn = (body.shape[1] // TILE_PX) * TILE_PX
    body = body[:Hn, :Wn]
    r = body[:, :, 0]
    g = body[:, :, 1]
    b = body[:, :, 2]
    color = (((g >= 128).astype(np.uint8) << 2) |
             ((r >= 128).astype(np.uint8) << 1) |
             ((b >= 128).astype(np.uint8)))
    bright = ((np.maximum(np.maximum(r, g), b) >= _BRIGHT_MIN) &
              (color > 0)).astype(np.uint8)
    return (color.astype(np.uint8) << 1) | bright


def _tile_signatures(quant) -> tuple[list[list[tuple[int, int, int]]],
                                     int, int]:
    """
    From a per-pixel ZX attribute array, derive (paper, ink, bitmap) for
    every 8x8 tile. Bitmap is a 64-bit int where bit i is set when the
    i-th pixel (row-major within the tile) differs from `paper`.
    Returns (sigs[row][col], rows_t, cols_t).
    """
    import numpy as np
    Hn, Wn = quant.shape
    rows_t = Hn // TILE_PX
    cols_t = Wn // TILE_PX
    # (rows_t, 8, cols_t, 8) -> (rows_t, cols_t, 8, 8)
    tiles = quant.reshape(rows_t, TILE_PX, cols_t, TILE_PX).transpose(0, 2, 1, 3)
    sigs: list[list[tuple[int, int, int]]] = []
    # Row-major flat index per pixel within tile.
    bit_weights = (1 << np.arange(TILE_PX * TILE_PX, dtype=np.uint64))
    for cy in range(rows_t):
        row_sigs: list[tuple[int, int, int]] = []
        for cx in range(cols_t):
            t = tiles[cy, cx].reshape(-1)
            counts = np.bincount(t, minlength=16)
            paper = int(np.argmax(counts))
            counts[paper] = 0
            ink_max = int(counts.max())
            ink = int(np.argmax(counts)) if ink_max > 0 else paper
            mask = (t != paper).astype(np.uint64)
            bitmap = int((mask * bit_weights).sum())
            row_sigs.append((paper, ink, bitmap))
        sigs.append(row_sigs)
    return sigs, rows_t, cols_t


def _cluster_8connected(cells: set[tuple[int, int]]) -> list[list[tuple[int, int]]]:
    """
    8-connected (queen-move) clustering of (col, row) cells. Diagonal
    neighbours count — important so a 1-tile-wide diagonal staircase
    becomes a single long cluster instead of N isolated cells (which
    would be wrongly flagged as N tiny sprites).
    """
    rest = set(cells)
    out: list[list[tuple[int, int]]] = []
    while rest:
        seed = next(iter(rest))
        rest.discard(seed)
        cluster = [seed]
        frontier = [seed]
        while frontier:
            cx, cy = frontier.pop()
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    if dx == 0 and dy == 0:
                        continue
                    n = (cx + dx, cy + dy)
                    if n in rest:
                        rest.discard(n)
                        cluster.append(n)
                        frontier.append(n)
        out.append(cluster)
    return out


def _attribute_is_structural(
    clusters: list[list[tuple[int, int]]],
    paper_attr: int,
    ink_attr: int,
) -> bool:
    """
    Decide whether the cells belonging to one (paper, ink) attribute pair
    are structural (background / floor / wall / ramp / conveyor / stairs /
    platforms / ladders) rather than sprite overlays.

    Heuristics, in order:
      1. Solid attribute (paper == ink, no ink pixels in any tile) ->
         always structural. Solid colour blocks are background or solid
         walls / floors, never sprites.
      2. Single cell -> sprite (definitely not structural by itself).
      3. Cells span only one row OR one column (with >= 2 cells) ->
         structural. Catches platforms, ceilings, conveyors, single-row
         floors, and ladders.
      4. Cells span >= 4 distinct rows AND >= 4 distinct cols AND there
         is at least one cluster of size >= 4 -> usually structural
         (room-sized backbone like floor + walls + ceiling sharing an
         attribute). EXCEPT when it's one compact cluster with high
         bbox fill ratio — that's an oversized sprite (big guardian)
         sitting in one place. Without the size->=4 cluster constraint,
         a swarm of N scattered singletons that happens to span the
         room would be wrongly classed as a backbone.
      5. Otherwise -> sprite candidate.
    """
    if paper_attr == ink_attr:
        return True  # solid colour block (background / solid wall)
    total = sum(len(c) for c in clusters)
    if total <= 1:
        return False
    rows: set[int] = set()
    cols: set[int] = set()
    for cluster in clusters:
        for (cx, cy) in cluster:
            rows.add(cy)
            cols.add(cx)
    if len(rows) == 1 or len(cols) == 1:
        return True
    if len(rows) >= 4 and len(cols) >= 4:
        max_cluster = max(len(cl) for cl in clusters)
        if max_cluster < 4:
            # All-small clusters scattered across the room = many
            # sprites with the same attribute, not a backbone.
            return False
        if len(clusters) == 1:
            cluster = clusters[0]
            xs = [cx for cx, _ in cluster]
            ys = [cy for _, cy in cluster]
            bbox_w = max(xs) - min(xs) + 1
            bbox_h = max(ys) - min(ys) + 1
            fill_ratio = len(cluster) / (bbox_w * bbox_h)
            if fill_ratio >= 0.5:
                return False  # compact blob -> oversized sprite
        return True
    return False


def _saturation_score(ink_attr: int, paper_attr: int) -> float:
    """How 'sprite-like' the ink color is (vivid + bright biases up)."""
    ink_color = ink_attr >> 1
    ink_bright = ink_attr & 1
    paper_color = paper_attr >> 1
    if ink_color == 0:
        return 0.0  # black ink (unlikely sprite)
    if ink_color == paper_color:
        return 0.0  # solid tile, no real ink
    if ink_color in _VIVID_INKS and ink_bright:
        return 1.0
    if ink_color in _VIVID_INKS:
        return 0.6
    if ink_bright:
        return 0.5
    return 0.25


def _shape_score(cluster_size: int) -> tuple[float, str]:
    """Cluster-size based shape score and predicted sprite type."""
    if cluster_size == 1:
        return 0.85, "item"
    if cluster_size == 2:
        return 0.55, "item"
    if cluster_size in (3, 4):
        return 0.75, "guardian"  # 2x2 sprite = classic JSW guardian
    if cluster_size <= 8:
        return 0.45, "guardian"
    if cluster_size <= 16:
        return 0.25, "guardian"
    return 0.10, "guardian"  # blob — likely stylized text or decoration


def _rarity_score(count: int) -> float:
    """Rarer signatures score higher. 1 occ -> 1.0, ramps off by ~7."""
    if count <= 1:
        return 1.0
    return max(0.0, 1.0 - (count - 1) / 6.0)


def classify_room_contents(im: Image.Image, grid: Grid,
                           room_regions: list[Region],
                           progress: bool = True
                           ) -> list[Region]:
    """
    Per-room sprite-overlay detection.

    Two complementary signals decide whether a cell is structural:

    A) **Cross-room bitmap repetition** (positive tile signal) — a full
       (paper, ink, bitmap) signature seen >= GLOBAL_TILE_REPEATS times
       across the whole map is a tile. Tile graphics are shared across
       rooms; sprite frames captured in a still screenshot rarely line
       up bitmap-for-bitmap.

    B) **In-room (paper, ink) attribute spread** (elimination signal) —
       cells of the same attribute pair grouped by 8-connectivity:
         - solid attribute (paper == ink) -> structural
         - cells span 1 row or 1 col >= 2 cells -> structural (line)
         - cells span >= 4 rows AND >= 4 cols with at least one cluster
           >= 4 cells -> structural (backbone), unless single compact
           blob with fill ratio >= 0.5 (oversized sprite)
         - all-tiny scattered clusters -> sprite candidate
         - 1- or 2-cell isolated clusters -> sprite candidate

    Anything left over after both passes is emitted as a sprite
    Region — single-cell clusters as items, multi-cell clusters as
    guardians. Confidence combines rarity, ink saturation/brightness,
    and cluster-shape fit.

    Mutates each room Region's classification_confidence and notes;
    returns a flat list of item / guardian sprite Regions.
    """
    # --- pre-pass: cache per-room sigs + build the cross-room histogram.
    room_sigs: dict[int, tuple[list[list[tuple[int, int, int]]], int, int]] = {}
    global_sig_count: dict[tuple[int, int, int], int] = {}
    for rr in room_regions:
        if rr.type != "room" or rr.room_number is None:
            continue
        x, y, w, h = rr.bbox
        quant = _quantize_room(im, grid, x, y, w, h)
        if quant is None:
            continue
        sigs, rows_t, cols_t = _tile_signatures(quant)
        room_sigs[rr.room_number] = (sigs, rows_t, cols_t)
        for cy in range(rows_t):
            for cx in range(cols_t):
                sig = sigs[cy][cx]
                global_sig_count[sig] = global_sig_count.get(sig, 0) + 1

    # --- pre-pass: cross-map silhouette + bitmask map for guardian
    # confirmation. Bg paper assumed to be ZX attribute 0 (black,
    # bright=0); true for the vast majority of JSW-style rooms. Cells
    # whose room bg differs (cyan-paper rooms etc.) skip this branch and
    # fall back to the elimination logic only.
    import numpy as np
    map_quant = _quantize_full_map(im, grid)
    BG_ATTR = 0
    silhouette = (map_quant != BG_ATTR).astype(np.uint8)
    bmask_at_pos = _all_8x8_bitmasks(silhouette)
    bmask_view = bmask_at_pos  # alias used inside the loop

    sprite_regions: list[Region] = []
    s = grid.scale
    tile_img_px = TILE_PX * s
    n_rooms = len(room_regions)
    n_items = 0
    n_guardians = 0
    n_repeat_overrides = 0
    for i, rr in enumerate(room_regions):
        if progress and (i + 1) % 25 == 0:
            print(f"    classified {i + 1}/{n_rooms} rooms "
                  f"(items={n_items}, guardians={n_guardians})")
        if rr.type != "room" or rr.room_number is None:
            continue
        cached = room_sigs.get(rr.room_number)
        if cached is None:
            continue
        sigs, rows_t, cols_t = cached
        x, y, w, h = rr.bbox
        n_total = rows_t * cols_t
        if n_total == 0:
            continue

        # Group cells by (paper, ink) attribute pair.
        attr_cells: dict[tuple[int, int], list[tuple[int, int]]] = {}
        cell_attr: dict[tuple[int, int], tuple[int, int]] = {}
        cell_bitmap: dict[tuple[int, int], int] = {}
        for cy in range(rows_t):
            for cx in range(cols_t):
                paper, ink, bitmap = sigs[cy][cx]
                ap = (paper, ink)
                attr_cells.setdefault(ap, []).append((cx, cy))
                cell_attr[(cx, cy)] = ap
                cell_bitmap[(cx, cy)] = bitmap

        # For each attribute pair, decide if it's structural based on the
        # spatial distribution of its cells (see _attribute_is_structural).
        attr_clusters: dict[tuple[int, int], list[list[tuple[int, int]]]] = {}
        structural: set[tuple[int, int]] = set()
        for ap, cells in attr_cells.items():
            clusters = _cluster_8connected(set(cells))
            attr_clusters[ap] = clusters
            if _attribute_is_structural(clusters, ap[0], ap[1]):
                structural.add(ap)

        # Always treat the dominant attribute pair as structural even if
        # it didn't trigger the spatial test (sparse rooms).
        if not structural and attr_cells:
            top_ap = max(attr_cells.items(), key=lambda kv: len(kv[1]))[0]
            structural.add(top_ap)

        # Per-room classification confidence: how well-separated are the
        # structural attribute pairs from sprite candidates? Use the share
        # of cells covered by structural attrs (high = clean room, low =
        # stylized / unusual).
        struct_cell_count = sum(
            len(cells) for ap, cells in attr_cells.items() if ap in structural
        )
        cls_conf = struct_cell_count / n_total
        rr.classification_confidence = cls_conf

        # Identify the room's predominant bg paper (the paper component
        # of the most-common attribute pair). For nearly all JSW rooms
        # this is ZX attr 0 (solid black). Used to decide whether a
        # candidate has the "guardian-on-bg" profile.
        room_bg_paper = max(
            attr_cells.items(), key=lambda kv: len(kv[1])
        )[0][0]

        # Walk each non-structural attribute pair's clusters and emit
        # sprite Regions. Cells survive into the sprite list when:
        #   - their bitmap is GLOBALLY rare (full-sig count < threshold),
        #     OR
        #   - they sit on bg paper and their silhouette has multiple
        #     matches anywhere in the map (per-pixel scan, including
        #     non-tile-aligned positions). This catches identical
        #     guardians (e.g. two marias in one room) whose tile-aligned
        #     bitmaps repeat globally and would otherwise be lost to
        #     the global-repeat tile rule.
        for ap, clusters in attr_clusters.items():
            if ap in structural:
                continue
            paper, ink = ap
            if paper == 0 and ink == 0:
                continue
            on_bg = (paper == room_bg_paper) and (paper == BG_ATTR)
            for cluster in clusters:
                kept: list[tuple[int, int]] = []
                cell_match_counts: dict[tuple[int, int], int] = {}
                for c in cluster:
                    bm = cell_bitmap[c]
                    g_count = global_sig_count.get((paper, ink, bm), 0)
                    bm_matches = 0
                    if on_bg and bm != 0:
                        bm_matches = int(
                            (bmask_view == np.uint64(bm)).sum()
                        )
                    cell_match_counts[c] = bm_matches
                    keep = (g_count < GLOBAL_TILE_REPEATS) or (
                        bm_matches >= GUARDIAN_BITMASK_MIN_MATCHES
                    )
                    if keep:
                        kept.append(c)
                    else:
                        n_repeat_overrides += 1
                if not kept:
                    continue
                shape_sc, sprite_type = _shape_score(len(kept))
                rarity = _rarity_score(len(kept))
                sat = _saturation_score(ink, paper)
                # Match-count boost: many matches across the map
                # (especially for bg-paper candidates) is positive
                # guardian evidence. Cap at 0.3 to keep a single
                # signal from saturating confidence.
                max_matches = max(cell_match_counts.values()) if kept else 0
                match_boost = 0.0
                if on_bg and max_matches >= 2:
                    match_boost = min(0.3, 0.1 + 0.05 * (max_matches - 2))
                conf = min(1.0,
                           0.35 * rarity + 0.30 * sat + 0.20 * shape_sc
                           + match_boost)
                for (cx, cy) in kept:
                    tx = x + cx * tile_img_px
                    ty = y + cy * tile_img_px
                    bm = cell_bitmap[(cx, cy)]
                    g_count = global_sig_count.get((paper, ink, bm), 0)
                    bm_matches = cell_match_counts[(cx, cy)]
                    sprite_regions.append(Region(
                        type=sprite_type,
                        bbox=(tx, ty, tile_img_px, tile_img_px),
                        confidence=conf,
                        tile_cell=(cx, cy),
                        room_number=rr.room_number,
                        notes=(f"attr_count={len(attr_cells[ap])} "
                               f"cluster={len(kept)} "
                               f"global_bitmap_count={g_count} "
                               f"bm_matches={bm_matches} "
                               f"rarity={rarity:.2f} sat={sat:.2f} "
                               f"shape={shape_sc:.2f} "
                               f"ink={_ZX_NAMES[ink >> 1]}"
                               f"{'+B' if ink & 1 else ''}"),
                    ))
                    if sprite_type == "item":
                        n_items += 1
                    else:
                        n_guardians += 1

        rr.notes += (f"  | attrs={len(attr_cells)} "
                     f"struct_share={cls_conf:.2f}")
    if progress:
        print(f"    {n_rooms} rooms classified: "
              f"{n_items} item-cells, {n_guardians} guardian-cells "
              f"(repeat-bitmap overrides: {n_repeat_overrides})")
    return sprite_regions


# ---------------------------------------------------------------------------
# Rendering overlay
# ---------------------------------------------------------------------------

def _load_label_font(size: int) -> ImageFont.ImageFont:
    for candidate in (
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/SFNSMono.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ):
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def render_overlay(im: Image.Image, grid: Grid,
                   regions: list[Region]) -> Image.Image:
    out = im.convert("RGB").copy()
    draw = ImageDraw.Draw(out, "RGBA")

    # Subtle grid lines
    grid_col = (60, 60, 60, 180)
    for c in range(grid.cols + 1):
        x = grid.x_offset + c * grid.cell_w
        draw.line([(x, 0), (x, im.height)], fill=grid_col, width=1)
    for r in range(grid.rows + 1):
        y = grid.y_offset + r * grid.cell_h
        draw.line([(0, y), (im.width, y)], fill=grid_col, width=1)
    if grid.title_strip > 0:
        for r in range(grid.rows):
            y = grid.y_offset + r * grid.cell_h + grid.body_h
            draw.line([(0, y), (im.width, y)],
                      fill=(60, 60, 60, 120), width=1)

    font = _load_label_font(13)
    # Item / guardian outlines render below room outlines so they don't
    # blanket the per-room frame, but above grid lines.
    label_priority = {"title": 5, "credits": 4, "room": 3,
                      "annotation": 3, "room_title": 2,
                      "item": 1, "guardian": 1, "unknown": 1}
    # Render high-priority regions last so their labels sit on top.
    for r in sorted(regions, key=lambda r: label_priority.get(r.type, 0)):
        x, y, w, h = r.bbox
        if w <= 0 or h <= 0:
            continue
        col = confidence_color(r.confidence)
        if r.type in ("item", "guardian"):
            # Single-tile sprites: 1px outline, no label, fill alpha tint.
            tint = (col[0], col[1], col[2], 70)
            draw.rectangle([x, y, x + w - 1, y + h - 1],
                           outline=col, fill=tint, width=1)
            continue
        draw.rectangle(
            [x, y, x + w - 1, y + h - 1], outline=col, width=2
        )
        # Always label annotations (small text labels like T2/T3/Out are
        # the whole point — even tiny boxes need their text shown).
        # For other types skip the label on tiny boxes to keep overlay clean.
        if r.type != "annotation" and (w < 30 or h < 12):
            continue
        if r.type == "room" and r.room_number is not None:
            label = f"#{r.room_number}"
        elif r.type == "room_title" and r.room_number is not None:
            label = f"#{r.room_number} title"
        elif r.type == "credits" and r.room_number is not None:
            label = f"#{r.room_number} credits"
        else:
            label = r.type
        if r.ocr_text and r.type in ("room_title", "annotation",
                                      "credits", "title"):
            t = r.ocr_text.strip()
            if len(t) > 24:
                t = t[:24] + "..."
            label += f" “{t}”"
        ly = y - 15 if y >= 16 else y + h + 1
        tb = draw.textbbox((x + 2, ly), label, font=font)
        draw.rectangle([tb[0] - 2, tb[1] - 1, tb[2] + 2, tb[3] + 1],
                       fill=(0, 0, 0, 210))
        draw.text((x + 2, ly), label, fill=col, font=font)
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def cmd_detect_metadata(args: argparse.Namespace) -> int:
    in_path: Path = args.input
    if not in_path.is_file():
        print(f"error: not a file: {in_path}", file=sys.stderr)
        return 2

    out_png = args.output_png or in_path.with_suffix(".metadata.png")
    out_json = args.output_json or in_path.with_suffix(".metadata.json")

    print(f"Loading {in_path}")
    im = Image.open(in_path).convert("RGB")
    print(f"  size={im.size}")

    grid = detect_room_grid(im)
    border_x = im.width - grid.cols * grid.cell_w
    border_y = im.height - grid.rows * grid.cell_h
    print(f"Grid: {grid.cols}x{grid.rows} cells, "
          f"cell={grid.cell_w}x{grid.cell_h} "
          f"(body {grid.cell_w}x{grid.body_h} + "
          f"title_strip {grid.title_strip}), "
          f"scale={grid.scale}x, offset=({grid.x_offset},{grid.y_offset}), "
          f"border=({border_x}, {border_y})")

    print("Classifying cells...")
    cell_kind, has_floor_grid, density_grid = classify_cells(im, grid)
    n_room = sum(1 for row in cell_kind for k in row if k == "room")
    n_floor = sum(
        1 for row in has_floor_grid for f in row if f
    )
    print(f"  non-empty rooms={n_room}  with floor band={n_floor}  "
          f"empty={grid.cols * grid.rows - n_room}")

    if args.no_ocr:
        print("Skipping OCR (--no-ocr)")
        words: list[dict] = []
        ocr_regions: list[Region] = []
    else:
        print(f"Running tiled OCR (upscale x{args.ocr_scale}, "
              f"tile {args.ocr_tile_size}, overlap {args.ocr_tile_overlap})...")
        words = ocr_image(
            im,
            upscale=args.ocr_scale,
            tile_size=args.ocr_tile_size,
            overlap=args.ocr_tile_overlap,
        )
        print(f"  detections={len(words)}")

    # Per-room-strip OCR runs FIRST — its results feed both title detection
    # (to filter out keyword-cluster false positives that turn out to be
    # regular rooms with title-like words in their strips) and credits
    # detection (to correlate candidate body content against strip titles).
    strip_titles: dict[tuple[int, int], dict] = {}
    if not args.no_ocr and grid.title_strip > 0:
        print("Per-room-strip OCR for room titles...")
        strip_titles = ocr_room_title_strips(im, grid, cell_kind)

    print("Detecting title-screen block(s)...")
    titles = detect_title_screens(
        grid, cell_kind, has_floor_grid, words, strip_titles
    )
    if titles:
        for t in titles:
            tw_cells = t.bbox[2] // grid.cell_w
            th_cells = t.bbox[3] // grid.cell_h
            print(f"  title screen: bbox={t.bbox} "
                  f"({tw_cells}x{th_cells} cells)")
            bx, by, _, _ = t.bbox
            r0, c0 = grid.cell_at(bx, by)
            for r in range(r0, r0 + th_cells):
                for c in range(c0, c0 + tw_cells):
                    if 0 <= r < grid.rows and 0 <= c < grid.cols:
                        if cell_kind[r][c] == "room":
                            cell_kind[r][c] = "title"
    else:
        print("  no title screen detected")

    # Drop strip-title entries inside any title cell — they're not real
    # room titles, they're title-screen content that happened to fall in
    # the under-strip area.
    strip_titles = {
        (r, c): v for (r, c), v in strip_titles.items()
        if cell_kind[r][c] == "room"
    }

    # Words harvested from the title-screen block(s) — used by
    # detect_credits to disambiguate stylized rooms from real credits.
    title_screen_words: set[str] = set()
    for t in titles:
        title_screen_words |= _title_screen_words(words, t)
    if title_screen_words:
        print(f"  title-screen words: {sorted(title_screen_words)}")

    print("Detecting credits cells "
          "(bottom-row + big-glyph + title-correlation)...")
    credits_regions = detect_credits(grid, words, cell_kind,
                                     strip_titles, title_screen_words)
    print(f"  credits cells flagged: {len(credits_regions)}")
    for cr in credits_regions:
        if cr.cell is not None:
            row, col = cr.cell
            cell_kind[row][col] = "credits"

    # Now that title/credits have been overridden, build per-cell room regions
    # and assign sequential numbers.
    room_regions, cell_to_number = build_room_regions(
        grid, cell_kind, has_floor_grid, density_grid
    )

    # Attach the matching room_number to each per-strip room title so the
    # overlay can show "#7 title" and the JSON cross-references room IDs.
    room_title_regions: list[Region] = []
    for (row, col), v in strip_titles.items():
        if not v["text"]:
            continue
        room_title_regions.append(Region(
            type="room_title",
            bbox=v["bbox"],
            confidence=0.55 + 0.4 * v["conf"],
            ocr_text=v["text"],
            cell=(row, col),
            room_number=cell_to_number.get((row, col)),
            notes="focused per-strip OCR",
        ))

    # Attach matching room_number to each credits region as well.
    for cr in credits_regions:
        if cr.cell is not None:
            cr.room_number = cell_to_number.get(cr.cell)

    # Re-classify OCR detections after cell_kind has been updated. Skip
    # title-strip detections since strip_titles already covers them.
    if not args.no_ocr:
        ocr_regions = classify_ocr(
            words, grid, cell_kind,
            skip_title_strips=bool(strip_titles),
        )

    block_regions: list[Region] = list(titles) + list(credits_regions)

    if args.no_classify:
        print("Skipping room-content classification (--no-classify)")
        sprite_regions: list[Region] = []
    else:
        print("Classifying room contents (tile signatures + sprites)...")
        sprite_regions = classify_room_contents(im, grid, room_regions)

    n_items = sum(1 for r in sprite_regions if r.type == "item")
    n_guardians = sum(1 for r in sprite_regions if r.type == "guardian")

    all_regions: list[Region] = (
        room_regions + block_regions + room_title_regions
        + ocr_regions + sprite_regions
    )

    print(f"Rendering overlay -> {out_png}")
    overlay = render_overlay(im, grid, all_regions)
    overlay.save(out_png)

    payload = {
        "input": str(in_path.resolve()),
        "image_size": list(im.size),
        "grid": grid.to_json(),
        "counts": {
            "rooms": n_room,
            "rooms_with_floor": n_floor,
            "credits_cells": len(credits_regions),
            "ocr_detections": len(words),
            "item_cells": n_items,
            "guardian_cells": n_guardians,
            "regions_total": len(all_regions),
        },
        "regions": [r.to_json() for r in all_regions],
    }
    out_json.write_text(json.dumps(payload, indent=2))
    print(f"Wrote {out_json}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Import a JSW-style map screenshot.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    pd = sub.add_parser(
        "detect-metadata",
        help="Detect title screen, credits, rooms and labels in a map image.",
    )
    pd.add_argument("input", type=Path, help="Path to map screenshot PNG.")
    pd.add_argument("--output-png", type=Path, default=None,
                    help="Annotated overlay PNG (default: <input>.metadata.png)")
    pd.add_argument("--output-json", type=Path, default=None,
                    help="Region JSON sidecar (default: <input>.metadata.json)")
    pd.add_argument("--ocr-scale", type=int, default=OCR_UPSCALE,
                    help=f"OCR upscale factor (default {OCR_UPSCALE})")
    pd.add_argument("--ocr-tile-size", type=int, default=960,
                    help="OCR tile size in upscaled pixels (default 960)")
    pd.add_argument("--ocr-tile-overlap", type=int, default=96,
                    help="OCR tile overlap in upscaled pixels (default 96)")
    pd.add_argument("--no-ocr", action="store_true",
                    help="Skip OCR entirely (visual heuristics only).")
    pd.add_argument("--no-classify", action="store_true",
                    help="Skip per-room item/guardian classification.")
    pd.set_defaults(func=cmd_detect_metadata)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())