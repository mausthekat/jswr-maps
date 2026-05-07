"""
JSW-engine snapshot library.

Loads a ZX Spectrum snapshot or tape image of a JSW-style game and
exposes the engine's room data (titles, layout, tile palette) through
a small API:

    from jsw_snapshot import load_snapshot, detect_engine, iter_rooms

    snap = load_snapshot("JetSetWilly1.z80")
    engine = detect_engine(snap)
    for room in iter_rooms(snap, engine):
        print(room.id, room.title)

Snapshot loading (`.z80` / `.sna` / `.szx`) and tape simulation
(`.tap` / `.tzx` / `.pzx`) are handled by `skoolkit` — for tape files
the loader is simulated through to a 128K memory image and we read
back via `skoolkit.snapshot.get_snapshot`. That keeps every JSW-era
loader (stock, JGH-style, JSW128, JSW64) in scope without us having
to reinvent any of it.

Engine families understood today (see seasip.info/Jsw/taxonomy.html
for the broader taxonomy):

  * JSW48        -- original 48K JSW. 64 rooms x 256 bytes at 0xC000.
  * JSW48-JGH    -- JGH-mode relocation, rooms at 0x8000-0xBFFF.
  * JSW128       -- 128K rerelease and its hacklevels (incl. JSW in
                    Paris, hacklevel 9). Rooms split across RAM banks
                    1, 3 and 4 (z80 pages 4, 6, 7), 64 per bank, 256
                    bytes each, paged in by the engine as the player
                    crosses bank boundaries.

JSW64-family variants (V/W/X/Y/Z/[) exist with quite different shape:
512- or 1024-byte room records, title at offset 0xB6 instead of 0x80,
layout at the END of the record at variable offset, and 3/4/8-bit cell
encoding instead of 2-bit. They're not handled yet — the `Engine`
class only models the JSW48/JSW128 schema today; widening it to JSW64
is a TODO once we have a snapshot to validate against. See
https://seasip.info/Jsw/jsw64room.html

The `.z80` loader supports v1 (single 48 KB RAM block) and v2 / v3
(paged blocks). For v2 / v3 we keep every RAM bank in `Snapshot.banks`
so room data sitting in paged-out banks is still reachable, while
`Snapshot.ram` exposes the default-banking 64 KB image (pages 3 / 5 / 8
at 0xC000 / 0x8000 / 0x4000) for compatibility with 48K-style probes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Iterator

import numpy as np


# ---------------------------------------------------------------------------
# .z80 loader
# ---------------------------------------------------------------------------


@dataclass
class Snapshot:
    """
    A loaded snapshot.

    `ram` is the 64 KB default-banking image (Spectrum 48K layout, or
    128K with $7FFD = 0). `banks[n]` holds RAM bank n as a 16 KB uint8
    array — populated for both 48K (banks 0, 2, 5) and 128K (all eight
    banks 0..7), so room data living in paged-out banks is reachable.
    """

    ram: np.ndarray
    banks: dict[int, np.ndarray] = field(default_factory=dict)
    is_128k: bool = False
    source_path: str = ""


# Default Spectrum banking after reset / no $7FFD: banks 5, 2, 0 are
# fixed at 0x4000 / 0x8000 / 0xC000. Other banks need paging to be seen.
_BANK_DEFAULT_ADDR = {0: 0xC000, 2: 0x8000, 5: 0x4000}

_TAPE_EXTS = {".tap", ".tzx", ".pzx"}
_SNAPSHOT_EXTS = {".z80", ".sna", ".szx"}


def _snapshot_from_skoolkit_ram(ram_list: list[int],
                                source: str) -> Snapshot:
    """
    Build a `Snapshot` from whatever `skoolkit.snapshot.get_snapshot`
    returns. For 128K (page=-1) it's 131072 bytes (banks 0..7 in
    order); for 48K it's 65536 bytes (16K ROM + 48K RAM in default
    banking).
    """
    arr = np.asarray(ram_list, dtype=np.uint8)
    banks: dict[int, np.ndarray] = {}
    if len(arr) == 0x20000:
        # 128K — eight 16 KB banks in order.
        for n in range(8):
            banks[n] = arr[n * 0x4000:(n + 1) * 0x4000].copy()
        ram = np.zeros(0x10000, dtype=np.uint8)
        ram[0x4000:0x8000] = banks[5]
        ram[0x8000:0xC000] = banks[2]
        ram[0xC000:0x10000] = banks[0]
        return Snapshot(ram=ram, banks=banks, is_128k=True,
                        source_path=source)
    if len(arr) == 0x10000:
        # 48K — ROM + 48K RAM in default banking.
        ram = arr.copy()
        for bank, addr in _BANK_DEFAULT_ADDR.items():
            banks[bank] = ram[addr:addr + 0x4000].copy()
        return Snapshot(ram=ram, banks=banks, is_128k=False,
                        source_path=source)
    raise ValueError(
        f"{source}: unexpected snapshot length {len(arr)} (want 65536 or 131072)"
    )


def _load_static(path: Path) -> Snapshot:
    """
    Load a static snapshot (.z80 / .sna / .szx). Tries 128K-mode first
    so all RAM banks come back populated; falls back to 48K mode on
    error or if the resulting image isn't 128K-shaped.
    """
    from skoolkit.snapshot import get_snapshot
    try:
        ram_full = get_snapshot(str(path), page=-1)
        if ram_full and len(ram_full) == 0x20000:
            return _snapshot_from_skoolkit_ram(ram_full, str(path))
    except Exception:
        pass
    ram48 = get_snapshot(str(path))
    return _snapshot_from_skoolkit_ram(ram48, str(path))


def _load_tape(path: Path) -> Snapshot:
    """
    Load a tape file (.tap / .tzx / .pzx) by driving skoolkit's
    `tap2sna` simulated loader through to a temporary `.z80`, then
    reading that back. Tries 128K mode first (the JSW128 / JSW64
    families need it), falls back to 48K on simulator error.
    """
    import tempfile
    from skoolkit.tap2sna import main as tap2sna_main

    def _run(machine: str) -> Path | None:
        td = tempfile.mkdtemp(prefix="jsw_snap_")
        out = Path(td) / (path.stem + ".z80")
        argv = [
            "-c", f"machine={machine}",
            "-c", "timeout=600",
            str(path), str(out),
        ]
        try:
            tap2sna_main(argv)
        except SystemExit:
            return None
        except Exception:
            return None
        return out if out.exists() and out.stat().st_size > 0 else None

    out = _run("128")
    if out is None:
        out = _run("48")
    if out is None:
        raise RuntimeError(f"{path}: tap2sna failed in both 128K and 48K modes")
    return _load_static(out)


def load_snapshot(path: str | Path) -> Snapshot:
    """
    Load a JSW-style snapshot or tape file. Supports `.z80`, `.sna`,
    `.szx`, `.tap`, `.tzx`, `.pzx`. Always attempts 128K mode first so
    multi-bank room data (JSW128, JSW64) lands in `Snapshot.banks` —
    falls back to 48K only when the 128K path fails or doesn't apply.
    """
    p = Path(path).resolve()
    ext = p.suffix.lower()
    if ext in _TAPE_EXTS:
        return _load_tape(p)
    if ext in _SNAPSHOT_EXTS:
        return _load_static(p)
    raise ValueError(
        f"{p}: unsupported format {ext!r} "
        f"(expected one of {sorted(_TAPE_EXTS | _SNAPSHOT_EXTS)})"
    )


# Backwards-compatible alias — older callers (and the importer)
# already import `load_z80`. New code should use `load_snapshot`.
def load_z80(path: str | Path) -> Snapshot:
    return load_snapshot(path)


# ---------------------------------------------------------------------------
# Engine detection
# ---------------------------------------------------------------------------


# Each engine variant describes where its room blocks live, as an
# ordered list of (source, offset, count) slots. `source` is either
# "ram" (use the default-banking 64 KB image) with `offset` being an
# absolute address in [0x4000..0xFFFF), or a bank number 0..7 with
# `offset` being relative to the bank's start (always 0 in practice).
RoomSlot = tuple[str | int, int, int]


@dataclass(frozen=True)
class Engine:
    """
    Where this engine's room table lives, and how each room block is
    laid out internally. Different JSW-engine families use different
    record sizes and place the title / layout at different offsets:

      JSW48 / JSW128: 256 byte records, title at +0x80, layout at +0x00
                     (32x16 cells, 2 bits each = 128 bytes).
      JSW64-V/W:      512 byte records, title at +0xB6.
      JSW64-X/Y/Z/[:  1024 byte records, title at +0xB6.

    Setting `room_size` and `title_offset` is enough for the detector
    and `Room.title` to work; the per-room layout / tile decoders need
    `layout_offset` and `layout_bits_per_cell` once we wire them up
    for a new family.
    """

    name: str
    slots: tuple[RoomSlot, ...]
    room_size: int = 256
    title_offset: int = 128
    title_length: int = 32
    layout_offset: int = 0
    layout_bits_per_cell: int = 2
    # Tile palette: contiguous run of (1 attr byte + 8 bitmap bytes)
    # per tile type, starting at `tile_palette_offset` and stepping
    # in `tile_palette_stride` bytes for `tile_palette_count` types.
    # JSW48 / JSW128: 6 entries (BG, FLOOR, WALL, NASTY, RAMP,
    # CONVEYOR) at +0xA0..+0xD5. JSW64 families pack 8 / 13 / 16 tile
    # types depending on variant.
    tile_palette_offset: int = 0xA0
    tile_palette_count: int = 6
    tile_palette_stride: int = 9
    # Exit table: 4 contiguous bytes giving neighbour room ids in the
    # order LEFT, RIGHT, ABOVE, BELOW. JSW48 / JSW128 / JSW64 all
    # share the +0xE9 location.
    exits_offset: int = 0xE9
    # JSW64-Z's "layout" stores raw ZX attribute bytes per cell, not
    # palette indices. The renderer matches each byte against the
    # palette's attribute bytes; matched cells use that palette entry's
    # bitmap, unmatched cells use a global "water" graphic coloured by
    # the cell's attribute. See https://seasip.info/Jsw/jsw64room.html
    layout_is_attributes: bool = False
    # JSW48 / JSW128 encode the room's single conveyor and ramp as
    # (direction, location, length) records at room offsets 0xD6..0xDD
    # rather than as cells in the layout grid. JSW64 variants put both
    # in the layout palette directly so this flag is False there.
    has_separate_stairs_conveyors: bool = False
    # Per-tile-index mapping into the canonical category palette
    # documented in docs/formats/CANONICAL_TILE_CATEGORY_COLORS.md:
    #   0 SOLID 1 STAIRS 2 PLATFORM 3 HAZARD 4 DECORATION 5 CONVEYOR
    #   6 PENROSE 7 COLLAPSIBLE 8 TRAMPOLINE
    # `None` means "render as background" (don't colour the cell).
    # `tile_role_map[i]` is the category for palette index `i`; tile
    # indices past the end of the tuple fall through to None.
    # Empty tuple = no documented role mapping (used for JSW64 V/X
    # whose 8-tile palette is per-room and whose cell-class bytes we
    # haven't decoded yet).
    tile_role_map: tuple[int | None, ...] = ()
    # Parallel to `tile_role_map`: for slots that share a canonical
    # category but differ in direction (JSW64 W/Y/YY/Z slots 4 vs 5
    # = ramp \ vs /, slots 6 vs 7 = conveyor << vs >>), True flags the
    # MIRROR bit in the categorical layout. Empty / shorter than role
    # map = no slot is mirrored.
    tile_mirror_map: tuple[bool, ...] = ()

    @property
    def room_count(self) -> int:
        return sum(s[2] for s in self.slots)


def _looks_like_jsw_room(buf: np.ndarray, addr: int,
                         title_offset: int = 128,
                         title_length: int = 32) -> bool:
    """
    Plausibility check: a JSW room block has a printable title at the
    family-specific offset. Layout bytes alone aren't distinctive
    (packed data is always "valid"), so the title is the signature.
    """
    if addr + title_offset + title_length > len(buf):
        return False
    title = buf[addr + title_offset: addr + title_offset + title_length].tobytes()
    title = bytes(b & 0x7F for b in title)
    printable = sum(1 for b in title if 0x20 <= b < 0x7F)
    if printable < title_length - 8:
        return False
    if not any(chr(b).isalpha() for b in title):
        return False
    return True


def _slot_buffer(snap: Snapshot, source: str | int) -> np.ndarray | None:
    if source == "ram":
        return snap.ram
    if isinstance(source, int):
        return snap.banks.get(source)
    return None


def _count_rooms_in_slot(snap: Snapshot, source: str | int,
                         offset: int, count: int,
                         engine: Engine) -> int:
    buf = _slot_buffer(snap, source)
    if buf is None:
        return 0
    return sum(
        1 for n in range(count)
        if _looks_like_jsw_room(
            buf,
            offset + n * engine.room_size,
            engine.title_offset,
            engine.title_length,
        )
    )


# Engine variants tried in priority order. First one whose slots are
# at least half-populated with valid room titles wins.
_KNOWN_ENGINES: tuple[Engine, ...] = (
    # JSW48: the original 48K JSW. 64 rooms in default-banking RAM at
    # 0xC000..0xFFFF. Tile palette is the canonical 6-entry sequence
    # BG / FLOOR / WALL / NASTY / RAMP / CONVEYOR — see
    # `TILE_TYPE_NAMES`. Stairs and conveyors are stored as separate
    # (direction, location, length) records at room offsets
    # 0xD6..0xDD; they are NOT in the layout grid (which only carries
    # BG / FLOOR / WALL / NASTY).
    Engine(name="JSW48",
           slots=(("ram", 0xC000, 64),),
           tile_role_map=(None, 2, 0, 3, 1, 5),
           has_separate_stairs_conveyors=True),
    # JSW48-JGH: JGH-mode relocation. Rooms moved 16 KB lower into
    # the 0x8000..0xBFFF range. Used by some 48K hacks. Same
    # stairs/conveyor encoding as JSW48.
    Engine(name="JSW48-JGH",
           slots=(("ram", 0x8000, 64),),
           tile_role_map=(None, 2, 0, 3, 1, 5),
           has_separate_stairs_conveyors=True),
    # JSW128: 128K rerelease and its hacklevel descendants (e.g. JSW
    # in Paris, hacklevel 9). 64 rooms in each of FOUR RAM banks
    # (1, 3, 4, 6 — z80 pages 4, 6, 7, 9), 256 rooms total, paged in
    # by the engine as the player crosses bank boundaries.
    # See https://seasip.info/Jsw/doc128.html
    Engine(name="JSW128",
           slots=((1, 0, 64), (3, 0, 64), (4, 0, 64), (6, 0, 64)),
           tile_role_map=(None, 2, 0, 3, 1, 5),
           has_separate_stairs_conveyors=True),
    # JSW64-V: 512-byte room records, title at +0xB6, layout at +0x140
    # (3 bits per cell), 8 cell types at +0x6E. Banks 1/3/4/6 with
    # 32 records per bank = 128 rooms.
    # https://seasip.info/Jsw/jsw64room.html
    Engine(name="JSW64-V",
           slots=((1, 0, 32), (3, 0, 32), (4, 0, 32), (6, 0, 32)),
           room_size=512,
           title_offset=0xB6,
           layout_offset=0x140,
           layout_bits_per_cell=3,
           tile_palette_offset=0x6E,
           tile_palette_count=8),
    # JSW64-W: 512-byte records, title at +0xB6, layout at +0x100
    # (4 bits per cell), 13 cell types at +0x41. 128 rooms.
    # Slot roles per https://seasip.info/Jsw/jsw64room.html:
    #   0 Air, 1 Water, 2 Earth, 3 Fire, 4 Ramp \, 5 Ramp /,
    #   6 Conveyor <<, 7 Conveyor >>, 8 Crumbling, 9 Trampoline,
    #   10..15 reserved. Mapped to canonical categories
    #   (SOLID=0, STAIRS=1, HAZARD=3, CONVEYOR=5, COLLAPSIBLE=7,
    #   TRAMPOLINE=8 — see CANONICAL_TILE_CATEGORY_COLORS.md).
    Engine(name="JSW64-W",
           slots=((1, 0, 32), (3, 0, 32), (4, 0, 32), (6, 0, 32)),
           room_size=512,
           title_offset=0xB6,
           layout_offset=0x100,
           layout_bits_per_cell=4,
           tile_palette_offset=0x41,
           tile_palette_count=13,
           tile_role_map=(None, 3, 0, 3, 1, 1, 5, 5, 7, 8),
           tile_mirror_map=(False, False, False, False, True, False, True, False, False, False)),
    # JSW64-X: 1024-byte records, title at +0xB6, layout at +0x340
    # (3 bits per cell), 8 cell types. 64 rooms across 4 banks.
    Engine(name="JSW64-X",
           slots=((1, 0, 16), (3, 0, 16), (4, 0, 16), (6, 0, 16)),
           room_size=1024,
           title_offset=0xB6,
           layout_offset=0x340,
           layout_bits_per_cell=3,
           tile_palette_offset=0x6E,
           tile_palette_count=8),
    # JSW64-Y: 1024-byte records, title at +0xB6, layout at +0x300
    # (4 bits per cell), 13 cell types. 64 rooms. Same Seasip slot
    # roles as JSW64-W.
    Engine(name="JSW64-Y",
           slots=((1, 0, 16), (3, 0, 16), (4, 0, 16), (6, 0, 16)),
           room_size=1024,
           title_offset=0xB6,
           layout_offset=0x300,
           layout_bits_per_cell=4,
           tile_palette_offset=0x41,
           tile_palette_count=13,
           tile_role_map=(None, 3, 0, 3, 1, 1, 5, 5, 7, 8),
           tile_mirror_map=(False, False, False, False, True, False, True, False, False, False)),
    # JSW64-YY: 1024-byte records, same shape as Y but the palette is
    # widened to 16 tiles (4-bit cell range fully used) starting at
    # +0x26. Tiles 0..12 share content with Y; the three extras live
    # at the end of the palette range. Slot roles 0..9 same as Y/W/Z;
    # extras 10..15 are reserved (no documented roles), so they fall
    # through to None.
    Engine(name="JSW64-YY",
           slots=((1, 0, 16), (3, 0, 16), (4, 0, 16), (6, 0, 16)),
           room_size=1024,
           title_offset=0xB6,
           layout_offset=0x300,
           layout_bits_per_cell=4,
           tile_palette_offset=0x26,
           tile_palette_count=16,
           tile_role_map=(None, 3, 0, 3, 1, 1, 5, 5, 7, 8),
           tile_mirror_map=(False, False, False, False, True, False, True, False, False, False)),
    # JSW64-Z: 1024-byte records, title at +0xB6, layout at +0x200
    # (8 bits per cell, but values are ZX attribute bytes — see
    # `layout_is_attributes`). 13-tile palette at +0x41 like W / Y.
    # Same Seasip slot roles as W/Y.
    Engine(name="JSW64-Z",
           slots=((1, 0, 16), (3, 0, 16), (4, 0, 16), (6, 0, 16)),
           room_size=1024,
           title_offset=0xB6,
           layout_offset=0x200,
           layout_bits_per_cell=8,
           tile_palette_offset=0x41,
           tile_palette_count=13,
           layout_is_attributes=True,
           tile_role_map=(None, 3, 0, 3, 1, 1, 5, 5, 7, 8),
           tile_mirror_map=(False, False, False, False, True, False, True, False, False, False)),
)


@dataclass
class _EngineMetrics:
    """Structural-fitness metrics for one engine candidate against a snapshot."""

    rooms: int
    title_pop_frac: float        # fraction of slot entries with valid titles
    palette_complete: float      # avg non-empty palette entries / palette_count
    layout_max: float            # avg per-room max layout cell value
    layout_runs_per_row: float   # avg run-count per row (low = coherent)
    exit_roundtrip_rate: float   # fraction of exits that round-trip
    pre_palette_tile_frac: float # fraction of rooms whose 9 bytes immediately
                                 # before the engine's palette look like a real
                                 # tile entry (non-empty bitmap). High value =
                                 # engine's palette boundary is too late;
                                 # there's a "ghost" tile sitting just before
                                 # the declared start. Discriminates Y from YY:
                                 # YY's palette starts 3 tiles earlier than Y's,
                                 # so Y on a YY snapshot reports a ghost tile
                                 # in nearly every room.


_DIR_REVERSE_T = (1, 0, 3, 2)


def _engine_metrics(snap: Snapshot, engine: Engine) -> _EngineMetrics:
    """
    Compute the structural-fitness metrics for `engine` against `snap`.
    No filtering yet — `_score_engine` interprets these into a verdict.
    """
    palette_n = engine.tile_palette_count
    title_pop = 0
    pal_sum = 0.0
    layout_max_sum = 0
    layout_runs_sum = 0.0
    rooms_decoded = 0
    pre_tile_rooms = 0
    rooms_for_exits: dict[int, tuple[int, ...]] = {}
    total_slots = engine.room_count
    pre_off_in_record = engine.tile_palette_offset - engine.tile_palette_stride

    for rid, src, off in _walk_slots(engine):
        buf = _slot_buffer(snap, src)
        if buf is None:
            continue
        if not _looks_like_jsw_room(
            buf, off, engine.title_offset, engine.title_length
        ):
            continue
        title_pop += 1
        # Palette completeness for this room.
        if palette_n > 0:
            nonempty = 0
            for n in range(palette_n):
                entry = off + engine.tile_palette_offset + n * engine.tile_palette_stride
                if entry + 9 > len(buf):
                    continue
                if int(buf[entry]) or int(buf[entry + 1: entry + 9].sum()):
                    nonempty += 1
            pal_sum += nonempty / palette_n
        # Pre-palette ghost-tile check: if the 9 bytes immediately
        # before the engine's claimed palette start look like a real
        # tile (non-zero attr AND non-zero bitmap) AND don't overlap
        # the title region, the palette boundary is wrong (palette
        # extends earlier). Both checks matter — V's "other data"
        # right before its 0x6E palette has bitmap-side bytes set but
        # attr=0, which is metadata, not a tile.
        title_start = engine.title_offset
        if pre_off_in_record >= 0 and pre_off_in_record + 9 <= title_start:
            pre_entry = off + pre_off_in_record
            if pre_entry + 9 <= len(buf):
                attr = int(buf[pre_entry])
                bm = int(buf[pre_entry + 1: pre_entry + 9].sum())
                if attr > 0 and bm > 0:
                    pre_tile_rooms += 1
        # Layout decode + spatial coherence.
        try:
            layout = _read_layout(buf, off, engine)
        except Exception:
            continue
        layout_max_sum += int(layout.max())
        runs = 0
        for r in range(layout.shape[0]):
            row = layout[r]
            runs += 1 + int((row[1:] != row[:-1]).sum())
        layout_runs_sum += runs / layout.shape[0]
        # Exit table for round-trip check.
        ex_off = off + engine.exits_offset
        rooms_for_exits[rid] = (
            int(buf[ex_off]), int(buf[ex_off + 1]),
            int(buf[ex_off + 2]), int(buf[ex_off + 3]),
        )
        rooms_decoded += 1

    rt_total = 0
    rt_match = 0
    for rid, exits in rooms_for_exits.items():
        for d in range(4):
            tgt = exits[d]
            if tgt == 0 or tgt == rid:
                continue
            tgt_exits = rooms_for_exits.get(tgt)
            if tgt_exits is None:
                continue
            rt_total += 1
            if tgt_exits[_DIR_REVERSE_T[d]] == rid:
                rt_match += 1

    return _EngineMetrics(
        rooms=rooms_decoded,
        title_pop_frac=title_pop / total_slots if total_slots else 0.0,
        palette_complete=pal_sum / rooms_decoded if rooms_decoded else 0.0,
        layout_max=layout_max_sum / rooms_decoded if rooms_decoded else 0.0,
        layout_runs_per_row=(layout_runs_sum / rooms_decoded
                             if rooms_decoded else 0.0),
        exit_roundtrip_rate=rt_match / rt_total if rt_total else 0.0,
        pre_palette_tile_frac=(pre_tile_rooms / rooms_decoded
                               if rooms_decoded else 0.0),
    )


def _score_engine(metrics: _EngineMetrics, engine: Engine,
                  snap: Snapshot) -> tuple[bool, tuple[float, ...]]:
    """
    Decide whether `engine` is a plausible match for the snapshot, and
    score it for tiebreaking.

    Filters that any correct engine MUST pass:

    * `title_pop_frac >= threshold` — the stride and title offset land
      on real titles. Catches obvious mismatches (JSW48's 256-byte
      stride against a JSW64 1024-byte file). Threshold is 70% in
      general, but 95% for a 48K-style engine (RAM-only slots) on a
      128K snapshot — bank-0 ($C000..$FFFF) on 128K maps sometimes
      carries loader-relic room-shaped bytes that hit ~80% on a
      256-byte probe yet aren't the real room table.

    * `exit_roundtrip_rate >= 0.4` — the engine's stride is aligned
      with the file's actual record size. Catches V/X confusion: V on
      a V file scores ~64%, but X (1024-byte stride on a 512-byte
      file) reads "room 0 title with room 1 layout" — exit IDs are in
      the wrong room space and round-trip rate collapses to 0%.

    * `layout_runs_per_row <= 7.5` — bit-width is right and the layout
      bytes haven't been read at the wrong offset. Real JSW rooms
      have ~4.7 runs/row (long uniform stretches: floor, walls, sky);
      wrong decodes look noisy at >8.

    * `layout_max <= max(palette_count, 8) * 2` — the layout values
      reference real palette entries. Catches Y/Z confusion: Z's 8-bit
      decode of Y's 4-bit-packed bytes gives max ≈ 93 vs palette of
      13–16; the right engine has max ≤ palette_count.

      JSW64-Z genuinely violates this filter because the variant
      stores per-cell ZX attribute bytes, not palette indices — see
      the engine table. The current generic decoder doesn't model Z's
      attribute-array format, so a Z snapshot legitimately fails to
      detect; this is preferable to silent misdetection.

    Tiebreak among survivors uses spatial coherence (lowest runs per
    row), with palette completeness as secondary.
    """
    if metrics.rooms == 0:
        return False, ()
    is_48k_engine = all(s[0] == "ram" for s in engine.slots)
    title_threshold = 0.95 if (snap.is_128k and is_48k_engine) else 0.70
    if metrics.title_pop_frac < title_threshold:
        return False, ()
    if metrics.exit_roundtrip_rate < 0.4:
        return False, ()
    # Palette-index layouts have low runs/row by construction (long
    # uniform stretches of floor / wall / sky). Attribute-byte layouts
    # (Z) naturally vary more — adjacent cells often carry different
    # ZX colour attributes for visual contrast — so allow more headroom
    # there. WillysFunPark scores 7.70 on Z; the JSW64-Y/YY misdetection
    # noise floor on Z files is 12+, so 10.0 is a safe widening.
    runs_threshold = 10.0 if engine.layout_is_attributes else 7.5
    if metrics.layout_runs_per_row > runs_threshold:
        return False, ()
    if metrics.pre_palette_tile_frac > 0.5:
        # The 9 bytes before the engine's palette look like a real
        # tile entry in most rooms — palette extends earlier than the
        # engine claims. Reject so a wider-palette sibling can win
        # (Y vs YY).
        return False, ()
    if not engine.layout_is_attributes:
        # Layout values index into the palette — they must stay within
        # range. Catches Y/Z confusion. Skip when the layout actually
        # stores raw attribute bytes (Z).
        palette_bound = max(engine.tile_palette_count, 8) * 2
        if metrics.layout_max > palette_bound:
            return False, ()
    # Tiebreak: prefer simpler models (palette-index layouts) over
    # attribute-array layouts, then lowest runs, then highest palette
    # completeness. The attribute-mode preference matters because Z's
    # `layout_is_attributes` skips the max-in-range gate, which makes
    # Z plausibly fit any 1024-byte file with low-runs random byte
    # pairings (Y/YY decode as Z look coherent because adjacent 4-bit
    # cells often tile up). Z should win only when no simpler model
    # passes — i.e. only on real Z snapshots, where Y/YY get rejected
    # by layout_runs (their 4-bit decoder reads Z's 8-bit attr stream
    # at the wrong stride and produces noise).
    return True, (
        1 if engine.layout_is_attributes else 0,
        metrics.layout_runs_per_row,
        -metrics.palette_complete,
    )


def detect_engine(snap: Snapshot) -> Engine | None:
    """
    Identify which JSW-engine variant produced this snapshot.

    Each candidate engine is scored on four structural-fitness signals
    that together pin down the right variant even when several share
    `room_size` + `title_offset`:

      1. title-stride population (gating)
      2. exit-graph round-trip rate (gating — stride alignment)
      3. layout cell values within palette range (gating — bit-width)
      4. layout spatial coherence (tiebreak — low runs-per-row wins)

    See `_score_engine` for thresholds and rationale.
    """
    best: tuple[tuple[float, ...], Engine] | None = None
    for cand in _KNOWN_ENGINES:
        metrics = _engine_metrics(snap, cand)
        ok, score = _score_engine(metrics, cand, snap)
        if not ok:
            continue
        if best is None or score < best[0]:
            best = (score, cand)
    return best[1] if best else None


# ---------------------------------------------------------------------------
# Per-room data
# ---------------------------------------------------------------------------


# JSW48 / JSW128 per-room layout (256-byte block, per the canonical
# Software Projects disassembly + https://seasip.info/Jsw/doc128.html):
#
#   0x00 .. 0x7F  Layout: 32x16 cells, 2 bits per cell.
#   0x80 .. 0x9F  Title (32 ASCII bytes; top bit may flag terminator).
#   0xA0 .. 0xD5  Tile palette: 6 entries x 9 bytes each
#                 (BG, FLOOR, WALL, NASTY, RAMP, CONVEYOR), each entry
#                 1 attribute byte + 8 bitmap bytes.
#   0xD6 .. 0xD9  Conveyor: direction, location, length.
#   0xDA .. 0xDD  Ramp: direction, location, length.
#   0xDE          Border colour (bit 7 = superjump).
#   0xDF .. 0xE0  Guardian-table pointer (16-bit).
#   0xE1 .. 0xE8  Item graphic.
#   0xE9 .. 0xEC  Exits: LEFT, RIGHT, ABOVE, BELOW (room ids).
#   0xF0 .. 0xFF  Guardian instances.
#
# JSW64 keeps the same exit / border conventions but moves layout,
# title and tile palette around per variant — the fields on `Engine`
# capture each engine's specific offsets.
TILE_TYPE_NAMES = ("background", "floor", "wall", "nasty",
                   "ramp", "conveyor")

ROOM_BORDER_OFFSET = 0xDE
ROOM_GUARDIAN_PTR_OFFSET = 0xDF


@dataclass
class TileGraphic:
    """One 8x8 tile graphic from a room palette: attribute + bitmap."""

    attr: int                # raw ZX attribute byte (PAPER/INK/BRIGHT/FLASH)
    bitmap: tuple[int, ...]  # 8 bytes, MSB = leftmost pixel


# JSW48 / JSW128 store room-buffer addresses (location of stairs base
# / conveyor leftmost cell) as 16-bit pointers into the engine's
# expanded-attribute work area at 0x5E00..0x5FFF — 32 cols * 16 rows
# laid out row-major.
_ROOM_BUFFER_BASE = 0x5E00
_ROOM_BUFFER_END = 0x6000


def _addr_to_room_xy(loc: int) -> tuple[int, int] | None:
    """
    Convert a JSW48/128 room-buffer address to (x, y) tile coords, or
    None if the address falls outside the room buffer.
    """
    if not (_ROOM_BUFFER_BASE <= loc < _ROOM_BUFFER_END):
        return None
    offset = loc - _ROOM_BUFFER_BASE
    return (offset % 32, offset // 32)


@dataclass
class ConveyorData:
    """
    A horizontal conveyor in a JSW48/JSW128 room. Cells run along
    one row from (x, y) to (x+length-1, y) and the conveyor's motion
    direction is given by `direction`:

      direction == 1  : motion RIGHT (canonical default)
      direction == 0  : motion LEFT  (mirrored from canonical)

    Verified empirically against JSW1 + Paris snapshots — Paris
    'Welcome to Paris!' has a length-15 ramp at base x=5 with dir=1
    that fits the room only when dir=1 means up-and-right; conveyor
    direction follows the same byte convention.
    """

    direction: int
    x: int
    y: int
    length: int

    @property
    def mirrored(self) -> bool:
        """True if motion is LEFT (mirrored from canonical default)."""
        return self.direction != 1


@dataclass
class RampData:
    """
    A diagonal ramp / staircase in a JSW48/JSW128 room. Each step
    moves diagonally up-and-`direction` from base (x, y):

      direction == 1  : ascending RIGHT (canonical default — `/` shape)
      direction == 0  : ascending LEFT  (`\\\\` shape, mirrored)
    """

    direction: int
    x: int
    y: int
    length: int

    @property
    def mirrored(self) -> bool:
        """True if the ramp ascends LEFT (mirrored from canonical)."""
        return self.direction != 1

    def cells(self) -> Iterator[tuple[int, int]]:
        """Yield (x, y) for every cell occupied by this ramp."""
        dx = 1 if self.direction == 1 else -1
        cx, cy = self.x, self.y
        for _ in range(self.length):
            yield cx, cy
            cx += dx
            cy -= 1


@dataclass(frozen=True)
class ItemData:
    """A collectible item placed at (x, y) tile coords inside a room."""

    x: int
    y: int


@dataclass(frozen=True)
class GuardianRef:
    """One guardian entry referenced from a room's `$F0..$FF` list.

    JSW48 / JSW128 store an 8-entry table per room: each pair is
    (def_idx, ix) where def_idx indexes the global entity-def table
    at $A000 and `ix` carries the per-instance initial x / y bits.
    Decoded fields here are derived from the def + ix and are in
    pixel/tile units relative to the room.
    """
    def_idx: int                 # index into the global def table
    ix: int                      # per-instance byte from $F0..$FF
    kind: str                    # "horiz" / "vert" / "rope" / "arrow"
    x: int                       # initial x in pixels (0..255)
    y: int                       # initial y in pixels (0..127)
    direction: int | None        # Tiled Direction enum: 0=Up 1=Down 2=Left 3=Right; None for rope
    mirrored: bool               # MIRROR flag for stairs/conveyor-style direction
    sprite_page: int             # `defb[5]` — engine sprite page (high byte of address)
    initial_frame: int           # `defb[0]` bits 5-6 — starting frame in the page
    frame_mask: int              # `defb[1]` bits 5-7 — animation cycle mask
    raw_def: tuple[int, ...]     # full 8 def bytes, for debugging


# JSW48 / JSW128 store all collectibles as 16-bit words in two parallel
# byte arrays at default-banking 0xA400 (low byte) and 0xA500 (high
# byte), indexed by N = 173..255 (= 83 item slots). Per the SkoolKit
# JSW48 disassembly (https://skoolkit.ca/disassemblies/jet_set_willy/
# asm/41984.html) the bit layout of word = (high << 8) | low is:
#
#   bit 15    : MSB of y-coordinate
#   bit 14    : "uncollected" flag (1 = present, 0 = already taken)
#   bits 13-8 : room number (0..63)
#   bits 7-5  : low 3 bits of y-coordinate
#   bits 4-0  : x-coordinate (0..31)
#
# JSW128 keeps the same layout and only places items in rooms 0..63
# (the first bank), so the 6-bit room field still covers every item.
# We deliberately ignore the "uncollected" flag — it reflects runtime
# game state, but the structure pack records the at-game-start
# positions, which the position bits preserve regardless of state.
_ITEMS_TABLE_LOW_ADDR = 0xA400
_ITEMS_TABLE_HIGH_ADDR = 0xA500
_ITEMS_FIRST_INDEX = 173
_ITEMS_LAST_INDEX = 255


# JSW64 (all six variants V/W/X/Y/YY/Z) keep the parallel-array idea
# but split the high byte into a separate 256-byte page that lives in
# bank 0 — per https://seasip.info/Jsw/doc128.html: "Object at 0A4xxh
# is in location at 0C0xxh". Low byte is still at default-banking
# 0xA400+N (bank 2's view); high byte is at bank-0 offset N (mapped
# to 0xC000+N when bank 0 is paged).
#
# Bit layout (verified empirically across JSW64-V/W/X/Y/YY/Z snapshots):
#   bit 15    : "collected" flag (set = collected — items zeroed when
#               collected, so this is 0 across all live entries)
#   bits 14-8 : room number (0..127) — wide enough for V/W's 128
#               rooms; X/Y/YY/Z fit in the lower 6 bits
#   bits 7-5  : y-coordinate (0..7) — items always live in the upper
#               half of a room in JSW64
#   bits 4-0  : x-coordinate (0..31)
#
# Total table size is 256 entries (V/W use slots 76..255 = 180 items;
# X/Y/YY/Z use slots 166..255 = 90 items). Trailing slots may be
# zeroed because the player has collected those items in the
# snapshot — we just iterate the whole 256-entry range and skip
# zeroes, which is robust whether or not the snapshot is mid-game.
_JSW64_ITEMS_LOW_ADDR = 0xA400
_JSW64_ITEMS_HIGH_BANK = 0


def _engine_has_jsw48_items_table(engine: Engine) -> bool:
    """Engines that share JSW48's items-table format and address."""
    return engine.name in ("JSW48", "JSW48-JGH", "JSW128")


def _engine_has_jsw64_items_table(engine: Engine) -> bool:
    """Engines that use the JSW64 split-bank items table."""
    return engine.name.startswith("JSW64-")


def _parse_items_jsw48(snap: Snapshot) -> dict[int, list[ItemData]]:
    by_room: dict[int, list[ItemData]] = {}
    ram = snap.ram
    if (_ITEMS_TABLE_LOW_ADDR + _ITEMS_LAST_INDEX >= len(ram) or
        _ITEMS_TABLE_HIGH_ADDR + _ITEMS_LAST_INDEX >= len(ram)):
        return by_room
    for n in range(_ITEMS_FIRST_INDEX, _ITEMS_LAST_INDEX + 1):
        lo = int(ram[_ITEMS_TABLE_LOW_ADDR + n])
        hi = int(ram[_ITEMS_TABLE_HIGH_ADDR + n])
        word = (hi << 8) | lo
        if word == 0:
            continue
        room = (word >> 8) & 0x3F
        y_high_bit = (word >> 12) & 0x08
        y_low_bits = (word >> 5) & 0x07
        y = y_high_bit | y_low_bits
        x = word & 0x1F
        by_room.setdefault(room, []).append(ItemData(x=x, y=y))
    return by_room


def _parse_items_jsw64(snap: Snapshot) -> dict[int, list[ItemData]]:
    by_room: dict[int, list[ItemData]] = {}
    ram = snap.ram
    high_bank = snap.banks.get(_JSW64_ITEMS_HIGH_BANK)
    if high_bank is None or len(high_bank) < 256:
        return by_room
    if _JSW64_ITEMS_LOW_ADDR + 255 >= len(ram):
        return by_room
    for n in range(256):
        lo = int(ram[_JSW64_ITEMS_LOW_ADDR + n])
        hi = int(high_bank[n])
        if (hi << 8 | lo) == 0:
            continue
        room = hi & 0x7F  # 7-bit room; bit 7 is the (zeroed) collected flag
        y = (lo >> 5) & 0x07
        x = lo & 0x1F
        by_room.setdefault(room, []).append(ItemData(x=x, y=y))
    return by_room


# JSW48 / JSW128 store the collectible item bitmap *per room* at room
# offset $E1..$E8 (8 bytes). The engine copies the current room's
# bitmap to the fixed working address $80E1 when entering the room;
# the routine at $93F1 then renders items from that working address.
# Different rooms have different item graphics (cross, bottle, cigar,
# trophy, etc.) — anyone calling `engine_item_bitmap(snap, engine)`
# (no room) gets the engine working-area copy, which only reflects
# whichever room was last entered before the snapshot was taken; for
# real per-room access use `room_item_bitmap(room)`.
_JSW48_ITEM_BITMAP_ADDR = 0x80E1
_JSW48_ROOM_ITEM_BITMAP_OFFSET = 0xE1


def engine_item_bitmap(snap: Snapshot, engine: Engine) -> tuple[int, ...] | None:
    """Return the 8-byte working-copy item bitmap from the engine area.

    For JSW48 / JSW128 this is the bitmap of whichever room was last
    entered when the snapshot was taken — fine as a fallback when no
    Room object is available, but per-room callers should prefer
    `room_item_bitmap(room)`.

    Returns None for engines whose item-graphic location isn't yet
    decoded. JSW64 variants don't have a fixed engine working-area
    address but DO have a per-room bitmap at the same offset; callers
    that just need to gate "can we decode items at all?" get a
    zero-bitmap sentinel for JSW64 so the gate flips on, with the
    real bitmap pulled per room via `room_item_bitmap`.
    """
    if _engine_has_jsw48_items_table(engine):
        if _JSW48_ITEM_BITMAP_ADDR + 8 > len(snap.ram):
            return None
        return tuple(int(b) for b in snap.ram[_JSW48_ITEM_BITMAP_ADDR:
                                              _JSW48_ITEM_BITMAP_ADDR + 8])
    if engine.name.startswith("JSW64-"):
        return (0,) * 8
    return None


# JSW48 / JSW128 entity-def table at $A000 — 96 entries × 8 bytes.
# Each room's `$F0..$FF` is 8 (def_idx, ix) pairs. Sprite frames live
# in the page named by `defb[5]` (high byte of address); each frame is
# 32 bytes (16×16 monochrome). The frame count comes from
# `defb[1]` bits 5-7 (mask: 0=1f, 1=2f, 3=4f, 7=8f).
_JSW48_DEF_TABLE_ADDR = 0xA000
_JSW48_DEF_BYTES = 8
_JSW48_GUARDIAN_FRAME_BYTES = 32  # 16×16 mono = 32 bytes


def _decode_jsw48_def(def_idx: int, ix: int, defb: tuple[int, ...]
                      ) -> GuardianRef | None:
    """Build a `GuardianRef` from one (def_idx, ix) pair + its 8 def
    bytes. Returns None for "unused" slots (def_idx 0xFF or all-zero
    def bytes)."""
    if def_idx == 0xFF:
        return None
    type_bits = defb[0] & 0x07
    bit7 = (defb[0] >> 7) & 1
    initial_frame = (defb[0] >> 5) & 0x03
    frame_mask = (defb[1] >> 5) & 0x07
    if type_bits == 1:           # horizontal patrol
        x = (ix & 0x1F) * 8
        y = ((defb[3] >> 3) << 2) + 16
        kind = "horiz"
        direction = 3 if bit7 else 2
        mirrored = not bit7
    elif type_bits == 2:         # vertical patrol
        x = (ix & 0x1F) * 8
        y = ((defb[3] >> 3) << 2) + 16
        kind = "vert"
        y_inc = defb[4] if defb[4] < 128 else defb[4] - 256
        direction = 0 if y_inc < 0 else 1
        mirrored = False
    elif type_bits == 3:         # rope
        x = (ix & 0x1F) * 8
        y = 16
        kind = "rope"
        direction = None
        mirrored = False
    elif type_bits == 4:         # arrow
        x = 0 if bit7 else 240
        y = ((ix >> 3) << 2) + 8
        kind = "arrow"
        direction = 3 if bit7 else 2
        mirrored = not bit7
    else:
        return None
    return GuardianRef(
        def_idx=def_idx, ix=ix, kind=kind, x=x, y=y,
        direction=direction, mirrored=mirrored,
        sprite_page=int(defb[5]), initial_frame=initial_frame,
        frame_mask=frame_mask, raw_def=tuple(int(b) for b in defb),
    )


def parse_room_guardians(snap: Snapshot, engine: Engine,
                         room: "Room") -> list[GuardianRef]:
    """Decode the per-room guardian list. Format depends on engine:

    * **JSW48 / JSW128** — 8 (def_idx, ix) pairs at room offset
      `$F0..$FF`; each pair references the global 8-byte entity-def
      table at `$A000 + def_idx*8`. List terminates at `def_idx=0xFF`.
    * **JSW64-V/W/X/Y/YY/Z** — up to N 8-byte FULL definitions stored
      inline at the START of the room block (offset `$00`), terminated
      by `0xFF`. N = 13 for V/X, 8 for W/Y/Z, 4 for `[`. Per
      [Seasip](https://seasip.info/Jsw/jsw64room.html). The (def_idx,
      ix) abstraction doesn't apply — each room carries its own
      guardian definitions, so we synthesise a fake def_idx from the
      list position purely for `GuardianRef` bookkeeping.

    The resolved x / y / direction / mirrored fields use the same
    decode as JSW48 (the JSW64 entity-def byte layout matches), so
    callers handle both engine families uniformly.
    """
    if _engine_has_jsw48_items_table(engine):
        # JSW48 / JSW128 — references into the global $A000 table.
        raw = room.raw
        if not raw or len(raw) < 0x100:
            return []
        out: list[GuardianRef] = []
        for i in range(0, 16, 2):
            def_idx = raw[0xF0 + i]
            ix = raw[0xF0 + i + 1]
            if def_idx == 0xFF:
                break
            addr = _JSW48_DEF_TABLE_ADDR + def_idx * _JSW48_DEF_BYTES
            if addr + _JSW48_DEF_BYTES > len(snap.ram):
                continue
            defb = tuple(int(b) for b in snap.ram[addr:addr + _JSW48_DEF_BYTES])
            gref = _decode_jsw48_def(def_idx, ix, defb)
            if gref is not None:
                out.append(gref)
        return out

    if engine.name.startswith("JSW64-"):
        # Inline 8-byte defs starting at room offset 0, terminated by
        # 0xFF. Cap by the documented max-instance count per variant.
        max_instances = {
            "JSW64-V": 13, "JSW64-X": 13,
            "JSW64-W": 8,  "JSW64-Y": 8, "JSW64-YY": 8, "JSW64-Z": 8,
        }.get(engine.name, 0)
        if max_instances == 0:
            return []
        raw = room.raw
        if not raw or len(raw) < max_instances * _JSW48_DEF_BYTES:
            return []
        out: list[GuardianRef] = []
        for slot in range(max_instances):
            base = slot * _JSW48_DEF_BYTES
            if raw[base] == 0xFF:
                break
            defb = tuple(int(b) for b in raw[base:base + _JSW48_DEF_BYTES])
            # JSW64 stores the initial X/Y inside the def itself rather
            # than carrying a separate per-instance ix byte. Reuse the
            # JSW48 decoder by passing the def's own byte 3 high-bits
            # as a synthetic ix — the type-bit branch in the decoder
            # already reads x and y from the bytes it has.
            gref = _decode_jsw48_def(slot, defb[3], defb)
            if gref is not None:
                out.append(gref)
        return out

    return []


def guardian_sprite_frames(snap: Snapshot, gref: GuardianRef) -> list[bytes]:
    """Return the list of 32-byte frame bitmaps for `gref`, one entry
    per animation frame.

    Sprite frames are at `gref.sprite_page << 8` + `frame * 32`. The
    frame count comes from the def's animation mask (bits 5-7 of
    `defb[1]`): mask 0→1 frame, 1→2, 3→4, 7→8. Initial-frame offset
    isn't applied here — callers that want the runtime starting frame
    can index by `gref.initial_frame`."""
    # Cast to Python int — `gref.sprite_page` is a numpy uint8 from
    # the snapshot slice; shifting a uint8 by 8 wraps to 0.
    page_addr = int(gref.sprite_page) << 8
    # The "frame mask" is the runtime's bitmask: displayed frame is
    # `(animation_counter & mask)`. So the set of reachable frame
    # indices is `{v for v in 0..mask if (v & mask) == v}` — for the
    # common power-of-2-minus-1 masks (0, 1, 3, 7) this is the
    # straightforward `0..mask`, but for sparse masks (e.g. 2 → {0,2}
    # or 6 → {0,2,4,6}) we skip the unreachable slots so we don't
    # accidentally pull bytes belonging to a different guardian
    # sharing the same sprite page.
    mask = gref.frame_mask
    reachable = [v for v in range(mask + 1) if (v & mask) == v] if mask else [0]
    frames: list[bytes] = []
    for f in reachable:
        addr = page_addr + f * _JSW48_GUARDIAN_FRAME_BYTES
        if addr + _JSW48_GUARDIAN_FRAME_BYTES > len(snap.ram):
            break
        frames.append(bytes(snap.ram[addr:addr + _JSW48_GUARDIAN_FRAME_BYTES]))
    return frames


def room_item_bitmap(room: "Room") -> tuple[int, ...] | None:
    """Return the 8-byte item bitmap for a specific room.

    JSW48 / JSW128 / JSW64 all store one bitmap per room at room
    offset `$E1..$E8`. (Despite Seasip's note that JSW64 uses just
    1 byte at `$E1`, empirical inspection of WFP / hacklevel-12
    snapshots shows the same 8-byte layout as JSW48 — e.g. WFP
    "The Clowns" room has a clown-face bitmap at `$E1..$E8`.)
    Returns None only when the room block is too short to contain
    the field. Many rooms share the same bitmap (or none, when the
    room has no items); callers typically dedup by the returned tuple."""
    raw = room.raw
    if not raw or len(raw) < _JSW48_ROOM_ITEM_BITMAP_OFFSET + 8:
        return None
    return tuple(raw[_JSW48_ROOM_ITEM_BITMAP_OFFSET:
                     _JSW48_ROOM_ITEM_BITMAP_OFFSET + 8])


def parse_items(snap: Snapshot, engine: Engine
                ) -> dict[int, list[ItemData]]:
    """
    Decode the items table for `engine` and group items by room.
    Returns a dict mapping room id -> list of `ItemData(x, y)` in
    tile coordinates. Different engine families use different table
    formats:

      * JSW48 / JSW48-JGH / JSW128 — both bytes at default-banking
        $A400 / $A500 (parallel arrays), 6-bit room, 4-bit y, 5-bit x.
      * JSW64-V/W/X/Y/YY/Z — low byte at default-banking $A400,
        high byte in bank 0 (= $C000 when paged), 7-bit room (max
        127), 3-bit y, 5-bit x.

    Returns an empty dict for engines whose items table we don't
    decode yet.
    """
    if _engine_has_jsw48_items_table(engine):
        return _parse_items_jsw48(snap)
    if _engine_has_jsw64_items_table(engine):
        return _parse_items_jsw64(snap)
    return {}


@dataclass
class Room:
    """One JSW room as stored in the snapshot."""

    id: int                 # sequential room id across all engine slots
    source: str | int       # "ram" or bank number
    addr: int               # offset within the source buffer
    title: str
    # 16x32 array of tile-type indices. The valid range depends on
    # `engine.layout_bits_per_cell` (2 -> 0..3, 3 -> 0..7, 4 -> 0..15,
    # 8 -> 0..255). Out-of-range cells should fall through to a "no
    # tile" rendering.
    layout: np.ndarray = field(repr=False)
    # Per-engine tile palette. Index by the value found in `layout` to
    # get the (attribute, bitmap) pair for that cell. JSW48 / JSW128
    # have 6 entries (BG, FLOOR, WALL, NASTY, RAMP, CONVEYOR); JSW64
    # variants have 8, 13 or 16 depending on hacklevel.
    tile_palette: list["TileGraphic"] = field(repr=False, default_factory=list)
    # Convenience lookup by the JSW48/JSW128 names — same TileGraphic
    # objects as in `tile_palette[0..5]`. Empty for JSW64.
    tiles: dict[str, "TileGraphic"] = field(repr=False, default_factory=dict)
    # Neighbour ids in (LEFT, RIGHT, ABOVE, BELOW) order. 0 is a valid
    # room id; the engine treats it as "no exit" indirectly when the
    # destination room itself is unused, but for our purposes we keep
    # all four bytes verbatim and let the layout walker decide.
    exits: tuple[int, int, int, int] = (0, 0, 0, 0)
    border: int = 0          # border-colour byte (low bits) + superjump (bit 7)
    guardian_table: int = 0  # 16-bit pointer into the snapshot RAM
    raw: bytes = field(repr=False, default=b"")
    # True when `layout` cells are ZX attribute bytes rather than
    # palette indices (JSW64-Z). Renderers need this to decide how to
    # interpret each cell.
    is_attribute_layout: bool = False
    # Mirror of `engine.tile_role_map` so renderers can colour cells
    # by canonical category without re-passing the engine spec.
    tile_role_map: tuple[int | None, ...] = ()
    # Mirror of `engine.tile_mirror_map` so the structure exporter can
    # set the MIRROR bit per cell without re-consulting the engine spec.
    tile_mirror_map: tuple[bool, ...] = ()
    # JSW48/JSW128 only — the single conveyor and ramp record each
    # room can carry, stored as separate fields rather than as cells
    # in `layout`. None when the engine doesn't use this encoding
    # (JSW64 V/W/X/Y/YY/Z), or when the field is empty (length=0).
    conveyor: "ConveyorData | None" = None
    ramp: "RampData | None" = None
    # Collectible items placed in this room, in tile coordinates.
    # Populated by `iter_rooms` from the global items table for
    # engines that have one (JSW48/128). JSW64 variants currently
    # leave this empty.
    items: list["ItemData"] = field(default_factory=list)

    @property
    def superjump(self) -> bool:
        """True when the room has the superjump flag set in border byte."""
        return bool(self.border & 0x80)


def _read_title(buf: np.ndarray, addr: int,
                title_offset: int = 128, title_length: int = 32) -> str:
    bs = buf[addr + title_offset: addr + title_offset + title_length].tobytes()
    bs = bytes(b & 0x7F for b in bs)
    return bs.decode("ascii", errors="replace").strip()


def _read_layout(buf: np.ndarray, addr: int,
                 engine: "Engine") -> np.ndarray:
    """
    Decode the per-room layout into a 16x32 uint8 grid of tile-type
    indices, handling 2 / 3 / 4 / 8 bits per cell as configured on
    the engine.

    Within a row the leftmost cell occupies the highest bits of the
    earliest byte (MSB-first packing), matching every JSW-engine
    convention seen so far.
    """
    out = np.zeros((16, 32), dtype=np.uint8)
    bits = engine.layout_bits_per_cell
    base = addr + engine.layout_offset
    if bits == 2:
        for row in range(16):
            for col_byte in range(8):
                b = int(buf[base + row * 8 + col_byte])
                for sub in range(4):
                    shift = (3 - sub) * 2
                    out[row, col_byte * 4 + sub] = (b >> shift) & 0x03
    elif bits == 4:
        for row in range(16):
            for col_byte in range(16):
                b = int(buf[base + row * 16 + col_byte])
                out[row, col_byte * 2] = (b >> 4) & 0x0F
                out[row, col_byte * 2 + 1] = b & 0x0F
    elif bits == 8:
        for row in range(16):
            for col in range(32):
                out[row, col] = int(buf[base + row * 32 + col])
    elif bits == 3:
        # 32 cells x 3 bits = 96 bits = 12 bytes per row, MSB first.
        for row in range(16):
            row_bits = 0
            row_addr = base + row * 12
            for n in range(12):
                row_bits = (row_bits << 8) | int(buf[row_addr + n])
            # Now row_bits is a 96-bit number, leftmost cell in the
            # 3 most-significant bits.
            for col in range(32):
                shift = (31 - col) * 3
                out[row, col] = (row_bits >> shift) & 0x07
    else:
        raise ValueError(
            f"unsupported layout_bits_per_cell={bits} for engine {engine.name}"
        )
    return out


def _read_tile(buf: np.ndarray, addr: int, off: int) -> TileGraphic:
    return TileGraphic(
        attr=int(buf[addr + off]),
        bitmap=tuple(int(b) for b in buf[addr + off + 1: addr + off + 9]),
    )


def _read_tile_palette(buf: np.ndarray, addr: int,
                       engine: "Engine") -> list[TileGraphic]:
    """Read the engine's tile palette as a list of TileGraphic."""
    base = engine.tile_palette_offset
    stride = engine.tile_palette_stride
    return [
        _read_tile(buf, addr, base + n * stride)
        for n in range(engine.tile_palette_count)
    ]


def _read_exits(buf: np.ndarray, addr: int,
                engine: "Engine") -> tuple[int, int, int, int]:
    """Read the 4-byte exit table (LEFT, RIGHT, ABOVE, BELOW)."""
    off = addr + engine.exits_offset
    return (int(buf[off]), int(buf[off + 1]),
            int(buf[off + 2]), int(buf[off + 3]))


def _walk_slots(engine: Engine) -> Iterator[tuple[int, str | int, int]]:
    """Yield (room_id, source, offset) for every slot entry in order."""
    rid = 0
    for (src, off, count) in engine.slots:
        for n in range(count):
            yield rid, src, off + n * engine.room_size
            rid += 1


# JSW64-V / JSW64-X store an 8-cell role table per room at room offset
# $69..$6C. Each nibble is one cell's behaviour; cell N's nibble is
# `(buf[off + 0x69 + N//2] >> ((N % 2) * 4)) & 0x0F`. Values 0..9 match
# the canonical Seasip slot roles (Air/Water/Earth/Fire/Ramp\\/Ramp//
# Conveyor<</Conveyor>>/Crumbling/Trampoline). Byte $6D is unused.
_JSW64_VX_ROLE_TABLE_OFFSET = 0x69
_JSW64_VX_ROLE_BYTE_COUNT = 4


# Same Seasip-slot → canonical-category mapping as JSW64-W/Y/YY/Z (None
# means EMPTY/background). Index = Seasip slot 0..15.
_JSW64_SLOT_TO_CATEGORY = (
    None,  # 0 Air → empty
    3,     # 1 Water → HAZARD
    0,     # 2 Earth → SOLID
    3,     # 3 Fire → HAZARD
    1,     # 4 Ramp \\ → STAIRS (mirrored)
    1,     # 5 Ramp / → STAIRS
    5,     # 6 Conveyor << → CONVEYOR (mirrored)
    5,     # 7 Conveyor >> → CONVEYOR
    7,     # 8 Crumbling → COLLAPSIBLE
    8,     # 9 Trampoline → TRAMPOLINE
)
_JSW64_SLOT_MIRRORED = (
    False, False, False, False, True, False, True, False, False, False,
)


def _decode_jsw64_vx_role_map(raw: bytes
                              ) -> tuple[tuple[int | None, ...],
                                         tuple[bool, ...]] | None:
    """Decode a JSW64-V/X per-room class table into role + mirror maps.

    Returns `None` when the room block is too small. Each of the 8
    palette indices maps to one of the canonical Seasip categories
    using the per-room cell-class nibbles at `$69..$6C`.
    """
    base = _JSW64_VX_ROLE_TABLE_OFFSET
    if base + _JSW64_VX_ROLE_BYTE_COUNT > len(raw):
        return None
    role_map: list[int | None] = []
    mirror_map: list[bool] = []
    for n in range(8):
        byte = raw[base + n // 2]
        slot = (byte >> ((n % 2) * 4)) & 0x0F
        if 0 <= slot < len(_JSW64_SLOT_TO_CATEGORY):
            role_map.append(_JSW64_SLOT_TO_CATEGORY[slot])
            mirror_map.append(_JSW64_SLOT_MIRRORED[slot])
        else:
            role_map.append(None)   # reserved 10..15
            mirror_map.append(False)
    return tuple(role_map), tuple(mirror_map)


def _build_room(snap: Snapshot, engine: Engine, rid: int,
                src: str | int, off: int) -> Room:
    buf = _slot_buffer(snap, src)
    if buf is None:
        raise KeyError(f"snapshot is missing source {src!r}")
    title = _read_title(buf, off, engine.title_offset, engine.title_length)
    layout = _read_layout(buf, off, engine)
    palette = _read_tile_palette(buf, off, engine)
    exits = _read_exits(buf, off, engine)
    border = int(buf[off + ROOM_BORDER_OFFSET])
    gptr = (int(buf[off + ROOM_GUARDIAN_PTR_OFFSET])
            | (int(buf[off + ROOM_GUARDIAN_PTR_OFFSET + 1]) << 8))
    # Convenience name lookup for the first six entries of the palette
    # (matches the JSW48 / JSW128 ordering BG, FLOOR, WALL, NASTY,
    # RAMP, CONVEYOR). JSW64 palettes are bigger but the first four
    # entries still tend to map to background-like / floor-like /
    # wall-like / nasty-like roles, so the lookup is still useful.
    tiles_named: dict[str, TileGraphic] = {}
    for n, name in enumerate(TILE_TYPE_NAMES):
        if n < len(palette):
            tiles_named[name] = palette[n]
    conveyor: ConveyorData | None = None
    ramp: RampData | None = None
    if engine.has_separate_stairs_conveyors:
        c_dir = int(buf[off + 0xD6])
        c_loc = int(buf[off + 0xD7]) | (int(buf[off + 0xD8]) << 8)
        c_len = int(buf[off + 0xD9])
        if c_len > 0:
            xy = _addr_to_room_xy(c_loc)
            if xy is not None:
                conveyor = ConveyorData(direction=c_dir,
                                        x=xy[0], y=xy[1], length=c_len)
        r_dir = int(buf[off + 0xDA])
        r_loc = int(buf[off + 0xDB]) | (int(buf[off + 0xDC]) << 8)
        r_len = int(buf[off + 0xDD])
        if r_len > 0:
            xy = _addr_to_room_xy(r_loc)
            if xy is not None:
                ramp = RampData(direction=r_dir,
                                x=xy[0], y=xy[1], length=r_len)

    raw_room = bytes(buf[off:off + engine.room_size])
    # JSW64-V / JSW64-X have a per-room class table (8 cells × 4 bits)
    # rather than a fixed engine-level role map. Decode it here so the
    # room carries a *concrete* role/mirror map that matches its own
    # palette, and downstream tools (renderer, structure exporter) get
    # real categories instead of the palette-index fallback.
    if engine.name in ("JSW64-V", "JSW64-X"):
        decoded = _decode_jsw64_vx_role_map(raw_room)
        if decoded is not None:
            role_map, mirror_map = decoded
        else:
            role_map = engine.tile_role_map
            mirror_map = engine.tile_mirror_map
    else:
        role_map = engine.tile_role_map
        mirror_map = engine.tile_mirror_map

    return Room(
        id=rid,
        source=src,
        addr=off,
        title=title,
        layout=layout,
        tile_palette=palette,
        tiles=tiles_named,
        exits=exits,
        border=border,
        guardian_table=gptr,
        raw=raw_room,
        is_attribute_layout=engine.layout_is_attributes,
        tile_role_map=role_map,
        tile_mirror_map=mirror_map,
        conveyor=conveyor,
        ramp=ramp,
    )


def read_room(snap: Snapshot, engine: Engine, room_id: int) -> Room:
    """Decode a single room block by its sequential id across all slots."""
    items_by_room = parse_items(snap, engine)
    for rid, src, off in _walk_slots(engine):
        if rid == room_id:
            room = _build_room(snap, engine, rid, src, off)
            room.items = list(items_by_room.get(rid, ()))
            return room
    raise IndexError(
        f"room_id {room_id} outside engine.room_count={engine.room_count}"
    )


def iter_rooms(snap: Snapshot, engine: Engine,
               skip_empty: bool = True) -> Iterator[Room]:
    """
    Yield every room defined by the engine's slot list. `skip_empty=True`
    drops blocks whose title is unprintable AND whose layout is all
    zeros — common for unused tail entries in 128K / Paris maps.

    The global items table is parsed once per call and items are
    dispatched to their owning rooms via `Room.items`.
    """
    items_by_room = parse_items(snap, engine)
    for rid, src, off in _walk_slots(engine):
        buf = _slot_buffer(snap, src)
        if buf is None:
            continue
        if skip_empty and not _looks_like_jsw_room(
            buf, off, engine.title_offset, engine.title_length
        ):
            continue
        room = _build_room(snap, engine, rid, src, off)
        room.items = list(items_by_room.get(rid, ()))
        yield room


# ---------------------------------------------------------------------------
# Debug helpers — useful for `python jsw_snapshot.py <path>` style probing.
# ---------------------------------------------------------------------------


def text_at(ram: np.ndarray, addr: int, length: int) -> str:
    """ASCII view of `length` bytes at `addr`, non-printables shown as `.`."""
    bs = ram[addr:addr + length].tobytes()
    return "".join(chr(b) if 0x20 <= b < 0x7F else "." for b in bs)


def find_text(ram: np.ndarray, needle: str,
              start: int = 0x4000, end: int = 0x10000) -> list[int]:
    """Addresses in [start, end) where `needle` appears as ASCII."""
    body = ram[start:end].tobytes()
    needle_bytes = needle.encode("ascii", errors="replace")
    out: list[int] = []
    i = 0
    while True:
        j = body.find(needle_bytes, i)
        if j < 0:
            break
        out.append(start + j)
        i = j + 1
    return out


def main(argv: list[str] | None = None) -> int:
    """
    `python jsw_snapshot.py <path>` — dump engine + room titles for any
    supported snapshot or tape file (.z80 / .sna / .szx / .tap / .tzx
    / .pzx).
    """
    import argparse
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("path", type=Path,
                   help="snapshot or tape file (.z80/.sna/.szx/.tap/.tzx/.pzx)")
    p.add_argument("--rooms", action="store_true",
                   help="print one line per room (id, source, addr, title)")
    args = p.parse_args(argv)

    snap = load_snapshot(args.path)
    engine = detect_engine(snap)
    if engine is None:
        print(f"{args.path}: no JSW engine variant matched")
        return 1
    populated = sum(
        _count_rooms_in_slot(snap, src, off, n, engine)
        for (src, off, n) in engine.slots
    )
    slot_desc = ", ".join(
        f"{src if src != 'ram' else 'ram'}@{off:#06x}x{n}"
        for (src, off, n) in engine.slots
    )
    print(f"{args.path.name}: engine={engine.name}  "
          f"slots=[{slot_desc}]  "
          f"populated={populated}/{engine.room_count}  "
          f"is_128k={snap.is_128k}")
    if args.rooms:
        for room in iter_rooms(snap, engine):
            src = (f"ram@{room.addr:#06x}"
                   if room.source == "ram"
                   else f"bank{room.source}@{room.addr:#06x}")
            print(f"  [{room.id:3d}] {src}  {room.title!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
