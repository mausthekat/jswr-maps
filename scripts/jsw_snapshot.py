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

import dataclasses
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

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
    # How many of `slots`'s reserved capacity actually contains real
    # game rooms. Set by `detect_engine` from a strict-heuristic
    # `_count_rooms_in_slot` pass; `iter_rooms` stops yielding once
    # this many rooms have been emitted, so callers don't see phantom
    # rooms in slot capacity past the end of the actual game.
    # `None` on the `_KNOWN_ENGINES` constants — only set on the
    # detected engine returned by `detect_engine`.
    populated_rooms: int | None = None
    # JSW2-specific: room blobs are variable-length and indexed by a
    # 16-bit pointer table whose base address itself lives at this
    # address (LE word). When set, `iter_rooms` and `read_room` walk
    # the directory instead of using fixed-stride slot math.
    jsw2_directory_ptr_addr: int | None = None
    # Per-room offsets for the JSWED-style air-supply pair (coarse byte
    # `air_supply_offset[0]`, fine-bits byte `air_supply_offset[1]`).
    # JSW64 uses `($DF, $E0)`; stock Manic Miner uses `(700, 701)`. None
    # means the engine doesn't carry an air-supply field.
    air_supply_offset: tuple[int, int] | None = None
    # Manic Miner-style content marker. When True, `_score_engine`
    # waives the `exit_roundtrip_rate >= 0.4` filter and uses a lower
    # `title_pop_frac` threshold (caverns are sequential — navigation
    # is via MM_EXIT portals, not L/R/U/D bytes; one or more banks may
    # be fully empty in MM-style packs like MMDD).
    is_manic_style: bool = False

    @property
    def room_count(self) -> int:
        """Slot capacity (NOT actual game-room count). For "real
        rooms in this snapshot" use `populated_rooms`."""
        return sum(s[2] for s in self.slots)


def _looks_like_jsw_room(buf: np.ndarray, addr: int,
                         title_offset: int = 128,
                         title_length: int = 32,
                         strict: bool = False) -> bool:
    """
    Plausibility check: a JSW room block has a printable title at the
    family-specific offset. Layout bytes alone aren't distinctive
    (packed data is always "valid"), so the title is the signature.

    `strict=True` is for "this is an actual game room, not a tail
    fragment" — used by `_count_rooms_in_slot` (and thus
    `Engine.populated_rooms`). It tightens the non-printable budget
    from `title_length - 8` to `1`. Empirically this rejects JSW1's
    phantom rooms 61+ (2+ non-print) while keeping every real room
    across JSW1 / JSW128 / WFP (max observed: 1 non-print, in WFP's
    "TENEBRIS" room).
    """
    if addr + title_offset + title_length > len(buf):
        return False
    title = buf[addr + title_offset: addr + title_offset + title_length].tobytes()
    title = bytes(b & 0x7F for b in title)
    printable = sum(1 for b in title if 0x20 <= b < 0x7F)
    threshold = title_length - 1 if strict else title_length - 8
    if printable < threshold:
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
                         engine: Engine, strict: bool = False) -> int:
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
            strict=strict,
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
    # JSW2 — Jet Set Willy II - The Final Frontier. Variable-length
    # per-room blobs indexed by a directory pointer at $7E69; 9
    # cell-types per layout cell (vs JSW48's 4 from 2-bit packing);
    # global cell-graphic table at $8C78. Room iteration is via
    # `_walk_jsw2_directory`, NOT `_walk_slots` — the empty `slots`
    # tuple here is a marker. See `docs/JSW2_FORMAT_NOTES.md`.
    Engine(name="JSW2",
           slots=(),
           room_size=0,            # variable; not used by walker
           title_offset=0,         # title is RLE-tokenised in the blob
           tile_palette_offset=0,
           tile_palette_count=9,   # 9 cell types (0..8)
           tile_palette_stride=9,  # not used; cells live at $8C78
           # Layout cell value → canonical Category enum (1-shifted) per
           # `Category` definition. None ⇒ EMPTY. Index = layout value 0..8.
           # JSWED labels cell 1 "CB_WATER" and cell 2 "CB_EARTH", but
           # those names are editor lore and don't reflect the JSW2
           # runtime: cell 1 is the dominant walkable surface in every
           # playable room (e.g. 32/512 cells in The Off Licence,
           # rendered with grass-tuft pixels = JSW1's PLATFORM tile),
           # while cell 2 is the structural / wall fill. So the
           # role-map below treats cell 1 as PLATFORM and cell 2 as
           # SOLID — matching JSW1 semantics and the visible game.
           tile_role_map=(None,    # 0 AIR
                          2,       # 1 PLATFORM  (JSWED label: CB_WATER)
                          0,       # 2 SOLID     (JSWED label: CB_EARTH)
                          3,       # 3 HAZARD    (JSWED label: CB_FIRE)
                          1,       # 4 RRAMP  → STAIRS (default-direction)
                          5,       # 5 LCONV  → CONVEYOR (mirrored = leftward)
                          None,    # 6 AIR+ITEM (item placement, no static tile)
                          1,       # 7 LRAMP  → STAIRS (mirrored = ascending left)
                          5),      # 8 RCONV  → CONVEYOR (default-direction = right)
           tile_mirror_map=(False, False, False, False,
                            False,  # 4 RRAMP — default direction
                            True,   # 5 LCONV — mirrored
                            False,  # 6 ITEM
                            True,   # 7 LRAMP — mirrored
                            False), # 8 RCONV — default direction
           jsw2_directory_ptr_addr=0x7E69),
    # Manic Miner (Matthew Smith, 48K Spectrum). 20 caverns × 1024
    # bytes each, located at $B000..$EFFF in default-banking RAM
    # (per JSWED's `ManicGame::getRoom = memoryAt(0xB000 + 1024 * n)`).
    # Cavern layout — completely different from JSW1's:
    #   $000..$1FF  cell layout (32×16, 1 byte per cell = ZX attribute
    #               byte, matched against palette like JSW64-Z)
    #   $200..$21F  cavern title (32 bytes ASCII)
    #   $220..$267  cell palette (8 cells × 9 bytes each)
    #   $267        background colour byte (in tile #0 attr; bits 3-5)
    #   $277        conveyor direction (bit 0)
    #   $278..$279  conveyor location word
    #   $27A        conveyor length
    #   $27B        border colour (bits 0-2)
    #   $27D..$295  items (5 × 5 bytes)
    #   $28F        portal attribute (= room[655])
    #   $290..$2AF  portal sprite (32 bytes)
    #   $2B0..$2B3  portal position (packed across 688..691)
    #   $2B4..$2BB  item bitmap (8 rows)
    #   $2BC..$2BD  AIR SUPPLY — see docs/MANIC_MINER_FORMAT_NOTES.md
    #   $2BE..$2DA  4 horizontal guardians × 7 bytes
    #   $2DD..$2F9  4 vertical guardians × 7 bytes
    # MM has no Left/Right/Up/Down exit bytes — caverns play in a fixed
    # sequence keyed by cavern id, with a portal sprite as the exit.
    # `exits_offset` is therefore not meaningful here; the engine
    # detector's exit-roundtrip filter will reject Manic snapshots
    # (which is fine — auto-detect on a stock MM snapshot needs a
    # follow-up to relax that filter for content with no roomgraph).
    # `tile_role_map` follows JSWED `ManicRoom::getCellBehaviour`:
    #   0 AIR, 1 WATER (=PLATFORM), 2 CRUMBLY (=COLLAPSIBLE),
    #   3 EARTH (=SOLID), 4 CONVEYOR, 5 FIRE (=HAZARD),
    #   6 FIRE (=HAZARD), 7 WATER (=PLATFORM).
    Engine(name="Manic",
           slots=(("ram", 0xB000, 20),),
           room_size=1024,
           title_offset=0x200,
           title_length=32,
           layout_offset=0,
           layout_bits_per_cell=8,
           tile_palette_offset=0x220,
           tile_palette_count=8,
           tile_palette_stride=9,
           layout_is_attributes=True,
           exits_offset=0,            # MM caverns navigate via MM_EXIT
                                       # portal in the Spawn layer, not
                                       # via L/R/U/D byte fields.
           air_supply_offset=(700, 701),
           is_manic_style=True,
           tile_role_map=(None, 2, 7, 0, 5, 3, 3, 2),
           tile_mirror_map=(False, False, False, False, False, False, False, False)),
    # Manic-DD: the JSW64-Z packaging used by Manic Miner: Deeper and
    # Down (MMDD) and Manic Miner: Lost Levels (MMLL). Layout, palette,
    # and guardian decode are identical to JSW64-Z (the readme is
    # explicit: "this time using the JSW64 game engine"; bank 2 carries
    # the literal string "JET-SET WILLY Room format is Z"). The
    # difference is gameplay: sequential caverns navigated via the
    # MM_EXIT portal rather than directional exits, and a per-cavern
    # air clock at the JSW64 `$DF`/`$E0` location (per JSWED's
    # `j64roomform.cxx:89-100`). Detection: the `is_manic_style` flag
    # waives the exit-roundtrip + title-pop filters so MMDD/MMLL —
    # which have one fully-empty room bank and no roundtrip exits —
    # pass scoring; plain JSW64-Z snapshots (Willy's Fun Park) still
    # detect as Z because Z scores higher on a fully-populated map.
    Engine(name="Manic-DD",
           slots=((1, 0, 16), (3, 0, 16), (4, 0, 16), (6, 0, 16)),
           room_size=1024,
           title_offset=0xB6,
           layout_offset=0x200,
           layout_bits_per_cell=8,
           tile_palette_offset=0x41,
           tile_palette_count=13,
           layout_is_attributes=True,
           air_supply_offset=(0xDF, 0xE0),
           is_manic_style=True,
           # Per JSWED's `Jsw64Room::getCellBehaviour` (`j64room.cxx:437`)
           # the cell-behaviour map for variants W/Y/Z is stored at
           # bank 7 offset `$F4FF` (16 bytes). Each entry maps a
           # palette index → CB_* constant (see room.hxx:60-70):
           #   CB_AIR=0, CB_WATER=1, CB_EARTH=2, CB_FIRE=3,
           #   CB_LRAMP=4, CB_RRAMP=5, CB_LCONV=6, CB_RCONV=7,
           #   CB_CRUMBLY=8, CB_TRAMP=9, CB_TRAP=10.
           #
           # Extracted from MMDD's bank 7 $F4FF:
           #   [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 5, 1, 3, 2, 1, 1]
           # → slot 10 = CB_RRAMP (STAIRS), slot 11 = CB_WATER
           # (PLATFORM — Manic engines treat "water" cells as the
           # standard walkable surface), slot 12 = CB_FIRE (HAZARD).
           # Slots 13..15 unused by MMDD's 13-entry palette.
           #
           # Translated to canonical category roles (0=SOLID,
           # 1=STAIRS, 2=PLATFORM, 3=HAZARD, 5=CONVEYOR,
           # 7=COLLAPSIBLE, 8=TRAMPOLINE; None=AIR):
           tile_role_map=(None, 2, 0, 3, 1, 1, 5, 5, 7, 8, 1, 2, 3),
           # Mirror flag tracks direction variants:
           #   slot 4 (LRAMP) mirrored; slot 5 (RRAMP) not.
           #   slot 6 (LCONV) mirrored; slot 7 (RCONV) not.
           #   slot 10 = RRAMP (same as slot 5, not mirrored).
           tile_mirror_map=(False, False, False, False, True, False, True, False, False, False, False, False, False)),
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
    # Manic-style packs (stock MM, MMDD, MMLL) navigate via the
    # MM_EXIT portal in the Spawn layer instead of L/R/U/D byte
    # exits — so the exit-roundtrip filter doesn't apply. They also
    # tend to leave one or more banks empty (MMDD uses 3 of 4 JSW64
    # banks → 0.66 title_pop), so the title threshold drops to 0.50.
    if engine.is_manic_style:
        title_threshold = 0.50
    elif snap.is_128k and is_48k_engine:
        title_threshold = 0.95
    else:
        title_threshold = 0.70
    if metrics.title_pop_frac < title_threshold:
        return False, ()
    if not engine.is_manic_style and metrics.exit_roundtrip_rate < 0.4:
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
    # JSW2 detection short-circuit: the magic at $7089 is unambiguous,
    # the variant has a wholly different per-room structure, and the
    # generic structural-fitness scoring doesn't apply (no fixed
    # palette, no fixed room stride). Decrypt the snapshot in-place if
    # needed, then return the JSW2 engine pre-loaded with a populated-
    # rooms count read from the directory.
    if _is_jsw2_snapshot(snap):
        _jsw2_decrypt_inplace_if_needed(snap)
        jsw2 = next(e for e in _KNOWN_ENGINES if e.name == "JSW2")
        populated = _jsw2_count_rooms(snap)
        return dataclasses.replace(jsw2, populated_rooms=populated)

    best: tuple[tuple[float, ...], Engine] | None = None
    for cand in _KNOWN_ENGINES:
        if cand.jsw2_directory_ptr_addr is not None:
            continue  # JSW2 is handled above
        metrics = _engine_metrics(snap, cand)
        ok, score = _score_engine(metrics, cand, snap)
        if not ok:
            continue
        if best is None or score < best[0]:
            best = (score, cand)
    if best is None:
        return None
    chosen = best[1]
    populated = sum(
        _count_rooms_in_slot(snap, src, off, n, chosen, strict=True)
        for (src, off, n) in chosen.slots
    )
    # JSW64 W/Y/Z and Manic-DD: per JSWED `Jsw64Room::getCellBehaviour`
    # (`j64room.cxx:437`), the palette→behaviour map for these variants
    # is stored at bank 7 offset `$F4FF` (16 bytes). When present and
    # non-default, derive `tile_role_map`/`tile_mirror_map` from it so
    # each game's per-cavern palette semantics round-trip exactly. The
    # variant byte at `$85C9` selects the addressing scheme.
    dynamic_role = _read_jsw64_cb_role_map(snap, chosen)
    if dynamic_role is not None:
        role_map, mirror_map = dynamic_role
        return dataclasses.replace(
            chosen,
            populated_rooms=populated,
            tile_role_map=role_map,
            tile_mirror_map=mirror_map,
        )
    return dataclasses.replace(chosen, populated_rooms=populated)


# JSWED CB_* constants (`room.hxx:60-70`) — palette cell behaviours.
# Mapped to our canonical category roles (0=SOLID, 1=STAIRS, 2=PLATFORM,
# 3=HAZARD, 5=CONVEYOR, 7=COLLAPSIBLE, 8=TRAMPOLINE; None=AIR). Manic-
# engine games treat CB_WATER as the walkable surface, so the canonical
# role is PLATFORM. CB_TRAP (10) has no canonical mapping — surfaced as
# HAZARD until we wire trap-specific semantics.
_JSW64_CB_TO_ROLE: dict[int, int | None] = {
    0: None,   # CB_AIR
    1: 2,      # CB_WATER  → PLATFORM
    2: 0,      # CB_EARTH  → SOLID
    3: 3,      # CB_FIRE   → HAZARD
    4: 1,      # CB_LRAMP  → STAIRS (mirror)
    5: 1,      # CB_RRAMP  → STAIRS
    6: 5,      # CB_LCONV  → CONVEYOR (mirror)
    7: 5,      # CB_RCONV  → CONVEYOR
    8: 7,      # CB_CRUMBLY → COLLAPSIBLE
    9: 8,      # CB_TRAMP  → TRAMPOLINE
    10: 3,     # CB_TRAP   → HAZARD (fallback)
}
# Which CB_* values are the mirrored direction variant of their canonical
# role — used to populate `tile_mirror_map` entries.
_JSW64_CB_MIRRORED = {4, 6}


def _read_jsw64_cb_role_map(snap: Snapshot, engine: Engine
                            ) -> tuple[tuple[int | None, ...],
                                       tuple[bool, ...]] | None:
    """Read the per-game cell-behaviour map for JSW64 W/Y/Z variants
    (and Manic-DD which inherits the Z packaging) and translate it into
    `(tile_role_map, tile_mirror_map)` tuples. Returns None when the
    map isn't applicable (wrong engine, missing bank 7, or all-zero
    map indicating an uninitialized snapshot) — caller falls back to
    the engine's hardcoded role map.
    """
    if not (engine.name.startswith("JSW64-") or engine.name == "Manic-DD"):
        return None
    bank7 = snap.banks.get(7)
    if bank7 is None or len(bank7) < 0x4000:
        return None
    # JSWED's `memoryAt(0xF4FF, 7)` reads bank 7 at offset $34FF for
    # variants W/Y/Z. Variant `[` uses $F519 (offset $3519). V/X store
    # the map per-room, not globally — they don't reach this helper.
    variant = chr(int(snap.ram[0x85C9])) if 0x85C9 < len(snap.ram) else ''
    if variant == '[':
        offset = 0xF519 - 0xC000
    else:
        offset = 0xF4FF - 0xC000
    cb_map = [int(bank7[offset + i]) for i in range(16)]
    if not any(cb_map):
        return None  # uninitialized — fall back to hardcoded
    palette_n = engine.tile_palette_count
    role_map = tuple(_JSW64_CB_TO_ROLE.get(cb_map[i]) for i in range(palette_n))
    mirror_map = tuple(cb_map[i] in _JSW64_CB_MIRRORED for i in range(palette_n))
    return role_map, mirror_map


# ---------------------------------------------------------------------------
# JSW2 — Jet Set Willy II - The Final Frontier
# ---------------------------------------------------------------------------

_JSW2_MAGIC_ADDR = 0x7089
_JSW2_MAGIC_DECRYPTED = bytes((0xC0, 0x50, 0xC0, 0x51, 0xC0, 0x52,
                               0xC0, 0x53, 0xC0, 0x54, 0xC0, 0x55))
_JSW2_MAGIC_ENCRYPTED = bytes((0xEC, 0x93, 0x75, 0xDA, 0x7C, 0xED,
                               0x88, 0x3B, 0xC6, 0x49, 0xF3, 0x8E))
# Address constants (see docs/JSW2_FORMAT_NOTES.md).
JSW2_GUARDINKS = 0x70A9     # 4-byte palette indexed by CG6 bits 2-3
JSW2_CELLS = 0x8C78
JSW2_CELLSEND = 0x9A2E
JSW2_SPRITES = 0xD4A1
JSW2_DICT = 0xFA81
JSW2_DIRECTORY_PTR = 0x7E69
# Patch-vector specials.
JSW2_TOILET_RECORD = 0x83C9   # 7-byte HV-guardian record for T5==9 (Bathroom)
JSW2_LIFT_TABLE = 0xFB30      # 7 pairs × 14 bytes = lift HV-guardian records
# T5 patch-vector index → byte offset into JSW2_LIFT_TABLE. JSWED's
# `Jsw2RoomDraw::checkSpecials` switch hand-codes this mapping (the
# pair index isn't a linear function of the patch ID).
JSW2_LIFT_PAIR_OFFSET = {2: 0, 3: 14, 4: 28, 5: 42, 24: 56, 19: 70, 21: 84}

# ZX palette → RGBA for the GUARDINKS lookup. INK 0..7; bright variant
# adds the BRIGHT suffix. Matches `src/rendering/color_clash.py`'s
# canonical _ZX_NON_BRIGHT / _ZX_BRIGHT.
_ZX_INK_RGBA = {
    (False, 0): "#ff000000", (False, 1): "#ff0000d7",
    (False, 2): "#ffd40204", (False, 3): "#ffd700d7",
    (False, 4): "#ff00d700", (False, 5): "#ff00d7d7",
    (False, 6): "#ffd7d700", (False, 7): "#ffd7d7d7",
    (True,  0): "#ff000000", (True,  1): "#ff0000ff",
    (True,  2): "#fffc0104", (True,  3): "#ffff00ff",
    (True,  4): "#ff00ff00", (True,  5): "#ff00ffff",
    (True,  6): "#ffffff00", (True,  7): "#ffffffff",
}


def _zx_attr_to_rgba(attr: int) -> str:
    """Convert a 4-bit JSW guardian ink field to a Tiled `#AARRGGBB`
    string. Per JSWED's `JswGuardian::getInk() = m_guard[1] & 0x0F`:
    bits 0-2 are INK (0..7), bit 3 acts as a BRIGHT flag (verified
    against FG_WILLY/MARIA = 0xF7 = bright-white, FG_RESET = 0xF4 =
    bright-green, FG_TOILET = 0x07 = non-bright white).
    """
    ink = attr & 7
    bright = bool(attr & 0x08)
    return _ZX_INK_RGBA.get((bright, ink), "#ffffffff")


def _jsw2_guardian_color(ram, cg6: int) -> str:
    """Resolve a JSW2 guardian's ZX colour through the per-game palette
    at `$70A9`. Per JSWED `Jsw2HVGuardian::constructSprites`:
        ink_index = (CG6 & 0x0C) >> 2          # 0..3
        attr      = peek($70A9 + ink_index)
        ink_bits  = (attr & 7) | ((attr & 0x40) >> 3)   # bits 0-2 INK, bit 6 BRIGHT → bit 3
    Returns a 32-bit `#AARRGGBB` hex string suitable for Tiled's
    `Color` property.
    """
    ink_index = (cg6 & 0x0C) >> 2
    attr = int(ram[JSW2_GUARDINKS + ink_index])
    ink = attr & 7
    bright = bool(attr & 0x40)
    return _ZX_INK_RGBA.get((bright, ink), "#ffffffff")


def _jsw2_decode_hv_record(ram, defb: tuple[int, ...], slot: int,
                           kind_override: str | None = None,
                           ) -> "GuardianRef":
    """Decode one 7-byte JSW2 HV-guardian record into a GuardianRef
    (including the bouncing-bounds simulator → route_override).
    Shared by inline-room guardians and patch-vector specials (lift
    pairs at `$FB30`, toilet at `$83C9`). `kind_override` forces the
    GuardianRef.kind for lift / toilet emission; otherwise the kind
    falls out of CG6 bit 7 (`horiz` / `vert`).
    """
    b0, b1, b2, b3, b4, b5, b6 = defb
    is_horiz = bool(b6 & 0x80)
    sprite_frame_idx = b2 | ((b4 & 0x80) << 1)
    major_step = b3 - 256 if b3 >= 128 else b3
    minor_step = (b6 >> 4) & 0x03
    x_native = b4 & 0x7F
    y_native = b5 & 0x7F
    x_px = x_native * 2
    y_px = y_native
    if is_horiz:
        direction = 3 if major_step >= 0 else 2
    else:
        direction = 1 if major_step >= 0 else 0
    mirrored = major_step < 0
    kind = kind_override or ("horiz" if is_horiz else "vert")
    frame_mask = b6 & 0x03

    # Bouncing-bounds simulator — produces (x_min, x_max, y_min, y_max)
    # for axis-aligned guardians and a multi-vertex waypoint list for
    # diagonals. See the long comment that used to live in
    # _parse_room_guardians_jsw2 for the rationale (Eggoids, JSW2 edge
    # bouncing). Forces 45° on diagonal motion — the actual JSW2
    # `minor_step` value (1/2/3) sets a different angle each, but
    # we approximate as 45° pending a full per-axis slope fix.
    sim_x, sim_y = x_native, y_native
    if is_horiz:
        dx = major_step
        dy = 2 if minor_step > 0 else 0
    else:
        dy = major_step
        dx = 1 if minor_step > 0 else 0
    X_MAX_NATIVE = 120   # (256 - 16 sprite) / 2
    Y_MAX_NATIVE = 112   # 128 - 16 sprite

    x_min = x_max = sim_x
    y_min = y_max = sim_y
    waypoints: list[tuple[int, int]] = []
    if minor_step != 0:
        waypoints.append((sim_x, sim_y))
    count = b0 if b0 else 256
    reversals = 0
    for _ in range(512):
        if reversals >= 2:
            break
        next_x = sim_x + dx
        next_y = sim_y + dy
        bounced = False
        if next_x < 0 or next_x > X_MAX_NATIVE:
            dx = -dx
            next_x = sim_x + dx
            bounced = True
        if next_y < 0 or next_y > Y_MAX_NATIVE:
            dy = -dy
            next_y = sim_y + dy
            bounced = True
        if bounced and minor_step != 0:
            waypoints.append((sim_x, sim_y))
        sim_x, sim_y = next_x, next_y
        if sim_x < x_min: x_min = sim_x
        if sim_x > x_max: x_max = sim_x
        if sim_y < y_min: y_min = sim_y
        if sim_y > y_max: y_max = sim_y
        count -= 1
        if count <= 0:
            if minor_step != 0:
                waypoints.append((sim_x, sim_y))
            dx, dy = -dx, -dy
            reversals += 1
            count = b1 if b1 else 256
    if minor_step != 0 and waypoints and waypoints[-1] != (sim_x, sim_y):
        waypoints.append((sim_x, sim_y))

    # Pack bounds into JSW1-style raw_def[6]/[7] so the importer's
    # axis-aligned route emitter reads them directly.
    if is_horiz:
        r6 = (max(x_min, 0) // 4) & 0x1F
        r7 = (max(x_max, 0) // 4) & 0x1F
    else:
        r6 = max(y_min, 0) * 2
        r7 = max(y_max, 0) * 2
    r6 = max(0, min(255, r6))
    r7 = max(0, min(255, r7))
    r4 = abs(major_step) & 0x7F

    synth_raw = (defb[0], defb[1], defb[2], defb[3],
                 r4, defb[5], r6, r7)

    route_override = None
    if minor_step != 0 and len(waypoints) >= 2:
        pixel_waypoints: list[tuple[int, int]] = []
        for wx, wy in waypoints:
            px = (wx * 2, wy)
            if not pixel_waypoints or pixel_waypoints[-1] != px:
                pixel_waypoints.append(px)
        if len(pixel_waypoints) >= 2:
            route_override = tuple(pixel_waypoints)

    sprite_frame0 = JSW2_SPRITES + 32 * sprite_frame_idx
    return GuardianRef(
        def_idx=slot,
        ix=b4,
        kind=kind,
        x=x_px,
        y=y_px,
        direction=direction,
        mirrored=mirrored,
        sprite_page=sprite_frame_idx,
        base_sprite=0,
        initial_frame=0,
        frame_mask=frame_mask,
        raw_def=synth_raw,
        sprite_frame0_addr=sprite_frame0,
        route_override=route_override,
        color_rgba=_jsw2_guardian_color(ram, b6),
    )


def _jsw2_synth_lift(ram, defb: tuple[int, ...], pair_index: int
                     ) -> "GuardianRef":
    """Decode one of the two HV-guardian records that make up a JSW2
    lift pair. The kind is forced to `"lift"` so the emitter labels the
    object `Lift N` and drops the GuardianFlags property (no HARMLESS,
    no harm) per the main-map convention.
    """
    # Use a high-bit def_idx so the dedup key doesn't collide with
    # inline room guardians (which use slots 0..7).
    gref = _jsw2_decode_hv_record(ram, defb, 0xC0 + pair_index,
                                  kind_override="lift")
    return gref


def _jsw2_synth_toilet(ram, defb: tuple[int, ...]) -> "GuardianRef":
    """Decode the JSW2 toilet at `$83C9`. Stationary single guardian;
    we mark it `kind="toilet"` so the emitter names it `Toilet` and
    omits the route. JSW2's toilet is *deadly* (no HARMLESS flag)."""
    return _jsw2_decode_hv_record(ram, defb, 0xE0,
                                  kind_override="toilet")
# JSW1's Z80 RAM-mapped origin. snap.ram is indexed from 0x0000 in our
# module (verified earlier — `snap.ram[0xC000]` returns the byte at
# Z80 address $C000). JSW2 lives entirely in 48K RAM, so the same
# direct addressing applies.

_JSW2_DECRYPT_KEY_ADDR = 0x6480
_JSW2_DECRYPT_KEY_LEN = 0x22       # 34 bytes
_JSW2_DECRYPT_DATA_ADDR = 0x7000
_JSW2_DECRYPT_DATA_LEN = 0x8F00
_JSW2_RELOC_DST = 0xFFB0
_JSW2_RELOC_SRC = 0xF4B0
_JSW2_RELOC_LEN = 0x8FB3


def _is_jsw2_snapshot(snap: "Snapshot") -> bool:
    """Magic-bytes check at $7089. Matches both encrypted and
    decrypted JSW2 builds."""
    if len(snap.ram) < _JSW2_MAGIC_ADDR + 12:
        return False
    blob = bytes(snap.ram[_JSW2_MAGIC_ADDR:_JSW2_MAGIC_ADDR + 12])
    return blob == _JSW2_MAGIC_DECRYPTED or blob == _JSW2_MAGIC_ENCRYPTED


def _jsw2_decrypt_inplace_if_needed(snap: "Snapshot") -> None:
    """Apply JSWED's two-step decryption when the snapshot's $7089
    magic is the encrypted form. Mutates `snap.ram` in place. No-op on
    already-decrypted snapshots. The init-fragment patch at $7000 is
    NOT applied — we don't run the snapshot, only read its data, and
    the post-decrypt bytes at $7000 are stable game data either way."""
    blob = bytes(snap.ram[_JSW2_MAGIC_ADDR:_JSW2_MAGIC_ADDR + 12])
    if blob != _JSW2_MAGIC_ENCRYPTED:
        return
    ram = snap.ram
    # Step 1: relocate $8FB3 bytes from $F4B0 down to $FFB0 (both
    # pointers decrement; data moves UPWARD in memory).
    src = _JSW2_RELOC_SRC
    dst = _JSW2_RELOC_DST
    for _ in range(_JSW2_RELOC_LEN):
        ram[dst] = ram[src]
        dst -= 1
        src -= 1
    # Step 2: XOR-decrypt with the 34-byte repeating key at $6480.
    key = bytes(ram[_JSW2_DECRYPT_KEY_ADDR:
                    _JSW2_DECRYPT_KEY_ADDR + _JSW2_DECRYPT_KEY_LEN])
    for n in range(_JSW2_DECRYPT_DATA_LEN):
        ram[_JSW2_DECRYPT_DATA_ADDR + n] ^= key[n % _JSW2_DECRYPT_KEY_LEN]


def _jsw2_read16(ram: np.ndarray, addr: int) -> int:
    """Little-endian word at `addr`."""
    return int(ram[addr]) | (int(ram[addr + 1]) << 8)


def _jsw2_directory_base(snap: "Snapshot") -> int:
    return _jsw2_read16(snap.ram, JSW2_DIRECTORY_PTR)


def _jsw2_count_rooms(snap: "Snapshot") -> int:
    """The directory's first entry is a pointer to room 0; the
    directory ends right where room 0 begins, so the entry count is
    `(room0_offset - directory_base) / 2`."""
    base = _jsw2_directory_base(snap)
    room0 = _jsw2_read16(snap.ram, base)
    if room0 <= base:
        return 0
    return (room0 - base) // 2


def _jsw2_room_offset(snap: "Snapshot", rid: int) -> int:
    """Address (in RAM-space, i.e. the same indices as `snap.ram`) of
    the start of the room blob for `rid`."""
    base = _jsw2_directory_base(snap)
    return _jsw2_read16(snap.ram, base + 2 * rid)


def _jsw2_walk_directory(snap: "Snapshot",
                         engine: "Engine"
                         ) -> Iterator[tuple[int, str, int]]:
    """Yield `(room_id, "ram", blob_offset)` for every JSW2 room. Cap
    by `engine.populated_rooms` so callers see exactly the playable
    set."""
    n = _jsw2_count_rooms(snap)
    cap = engine.populated_rooms if engine.populated_rooms is not None else n
    for rid in range(min(n, cap)):
        yield rid, "ram", _jsw2_room_offset(snap, rid)


# Token dictionary expansion (see docs/JSW2_FORMAT_NOTES.md §9).
def _jsw2_expand_token(ram: np.ndarray, token_id: int,
                       buf: list[str], remaining_cap: list[int]) -> None:
    """Expand token `token_id` from the dictionary at $FA81 into
    `buf` (consuming `remaining_cap[0]` characters max). Recursive."""
    addr = JSW2_DICT
    walked = token_id
    # Walk the dictionary forward until we've passed `walked` bit-7
    # markers (= we're at the start of token #token_id).
    while walked > 0:
        # Skip until end-of-token marker, then step past it.
        while addr < len(ram) and not (int(ram[addr]) & 0x80):
            addr += 1
        addr += 1
        walked -= 1
        if addr >= len(ram):
            return
    # Now expand from `addr`.
    _jsw2_expand_string(ram, addr, buf, remaining_cap)
    # Each token is followed by a single space.
    if remaining_cap[0] > 0:
        buf.append(" ")
        remaining_cap[0] -= 1


def _jsw2_expand_string(ram: np.ndarray, addr: int,
                        buf: list[str], remaining_cap: list[int]) -> None:
    """Expand a JSW2-tokenised string starting at `addr` into `buf`,
    stopping at the first byte with bit-7 set (inclusive — that byte
    contributes its low 7 bits as the final character) or when
    `remaining_cap[0]` is exhausted. Tokens (`< 0x1F`) recurse via
    `_jsw2_expand_token`."""
    while addr < len(ram) and remaining_cap[0] > 0:
        b = int(ram[addr])
        if (b & 0x7F) < 0x1F:
            _jsw2_expand_token(ram, b & 0x7F, buf, remaining_cap)
        else:
            buf.append(chr(b & 0x7F))
            remaining_cap[0] -= 1
        addr += 1
        if b & 0x80:
            break


def _jsw2_decode_title(ram: np.ndarray, blob_off: int) -> tuple[str, int]:
    """Decode the per-room title. Returns (title_string,
    bytes_consumed) so the caller can advance past it to the exits.

    The decoded title is left-padded to start at column
    `(blob[$0B] & 0x1F)` within a 32-char buffer (matching JSWED's
    rendering)."""
    anchor = int(ram[blob_off + 0x0B]) & 0x1F
    addr = blob_off + 0x0C
    chars: list[str] = []
    cap = [32 - anchor]
    consumed_start = addr
    # Walk bytes ourselves (not via `_jsw2_expand_string`) so we can
    # report the exact byte count consumed including the terminator.
    while addr < len(ram) and cap[0] > 0:
        b = int(ram[addr])
        if (b & 0x7F) < 0x1F:
            _jsw2_expand_token(ram, b & 0x7F, chars, cap)
        else:
            chars.append(chr(b & 0x7F))
            cap[0] -= 1
        addr += 1
        if b & 0x80:
            break
    title_chars = " " * anchor + "".join(chars)
    title = (title_chars + " " * 32)[:32].rstrip()
    return title, addr - consumed_start + 0x0C  # bytes from blob start


def _jsw2_decode_shape(ram: np.ndarray, shape_addr: int) -> np.ndarray:
    """Decompress the JSW2 shape RLE into a 16x32 uint8 grid. Each
    cell value is in 0..8 (see canonical category mapping in the
    `JSW2` engine's `tile_role_map`)."""
    out = np.zeros((16, 32), dtype=np.uint8)
    src = shape_addr
    dst = 0
    while dst < 512 and src < len(ram):
        b = int(ram[src])
        src += 1
        if b < 0x90:
            rep = (b & 0x0F) + 1
            cell = (b & 0xF0) >> 4
        else:
            rep = b - 0x7F
            cell = 0
        for _ in range(rep):
            if dst >= 512:
                break
            out[dst // 32, dst % 32] = cell
            dst += 1
    return out


def _jsw2_decode_cell_numbers(ram: np.ndarray, blob_off: int) -> tuple[int, ...]:
    """Per-room cell-number table (8 entries for cell types 1..8).
    Each entry is a 9-bit index into the global cell-graphic table at
    `JSW2_CELLS`. Bit 8 is read from the overflow byte at blob[$02]:
    MSB of overflow = cell type 1's overflow bit, LSB = cell type 8.

    Returns a 9-tuple where index 0 is reserved (no cell for AIR).
    Indices 1..8 hold the resolved cell numbers."""
    overflow = int(ram[blob_off + 2])
    out = [0] * 9
    for n in range(8):  # cell types 1..8
        cell_no = int(ram[blob_off + 3 + n])
        if overflow & (0x80 >> n):
            cell_no += 256
        out[n + 1] = cell_no
    return tuple(out)


def _jsw2_read_cell_graphic(ram: np.ndarray, cell_no: int) -> "TileGraphic":
    """Fetch the 9-byte cell-graphic entry at `JSW2_CELLS + 9*cell_no`,
    apply the invert flag, and return as a `TileGraphic`."""
    addr = JSW2_CELLS + 9 * cell_no
    if addr + 9 > len(ram):
        return TileGraphic(attr=0, bitmap=tuple([0] * 8))
    attr = int(ram[addr])
    bm = [int(ram[addr + 1 + i]) for i in range(8)]
    if attr & 0x80:
        bm = [(b ^ 0xFF) & 0xFF for b in bm]
    # Per JSWED: clear bit 7 (invert), force bit 6 (BRIGHT).
    eff_attr = (attr & 0x7F) | 0x40
    return TileGraphic(attr=eff_attr, bitmap=tuple(bm))


def _jsw2_room_blob_size(ram: np.ndarray, blob_off: int,
                         next_blob_off: int | None) -> int:
    """Best-effort blob length. Used to fill `Room.raw`. We don't
    actually need to walk every field — the next room's blob offset
    (or end of RAM) caps it."""
    if next_blob_off is not None and next_blob_off > blob_off:
        return next_blob_off - blob_off
    return min(len(ram) - blob_off, 1024)


def _build_room_jsw2(snap: "Snapshot", engine: "Engine",
                     rid: int, blob_off: int) -> "Room":
    """Construct a `Room` for a single JSW2 room blob."""
    ram = snap.ram
    # Header
    shape_ptr = _jsw2_read16(ram, blob_off)
    cell_numbers = _jsw2_decode_cell_numbers(ram, blob_off)
    # Layout
    layout = _jsw2_decode_shape(ram, shape_ptr)
    # Title (and offset of post-title bytes)
    title, post_title_offset = _jsw2_decode_title(ram, blob_off)
    after_title = blob_off + post_title_offset
    # Exits: 4 bytes in JSW2 order (LEFT, UP, RIGHT, DOWN) — confirmed
    # against `st_exnames[4] = {"left", "up", "right", "down"}` in
    # JSWED's `Jsw2Room::exportExits` (jsw2room.cxx:762). Values are
    # 1-indexed (subtract 1 for a 0-indexed room id), and a self-loop
    # (`raw == rid + 1`) is the "no exit" convention (verified by
    # cross-link reciprocity: room 2 → room 1, room 1 → room 2). We
    # store the final tuple in our canonical (LEFT, RIGHT, ABOVE,
    # BELOW) ordering, mapping self-loops to `-1` so downstream
    # filename lookups miss and emit empty strings.
    raw_l = int(ram[after_title])     - 1
    raw_u = int(ram[after_title + 1]) - 1
    raw_r = int(ram[after_title + 2]) - 1
    raw_d = int(ram[after_title + 3]) - 1
    def _exit_or_none(v: int) -> int:
        return -1 if v < 0 or v == rid else v
    exits = (_exit_or_none(raw_l),
             _exit_or_none(raw_r),
             _exit_or_none(raw_u),
             _exit_or_none(raw_d))
    # T4 / T5
    t4 = int(ram[after_title + 4])
    n_guardians = t4 & 0x0F
    if n_guardians > 8:
        n_guardians = 0  # JSWED rejects >8 as "invalid room"
    cursor = after_title + 5
    t5 = 0
    if t4 & 0x10:
        t5 = int(ram[cursor])
        cursor += 1
    # Guardians: N × 7 bytes, parsed lazily via parse_room_guardians.
    cursor += 7 * n_guardians
    # Arrows: present iff T5 bit 7
    arrow_count = 0
    if t5 & 0x80:
        arrow_count = min(int(ram[cursor]), 8)
        cursor += 1 + 2 * arrow_count
    blob_end = cursor

    # Build a 9-entry tile palette (one per cell type). Index 0 is the
    # AIR placeholder (empty bitmap); 1..8 read from `JSW2_CELLS`.
    palette: list[TileGraphic] = [TileGraphic(attr=0, bitmap=tuple([0] * 8))]
    for n in range(1, 9):
        palette.append(_jsw2_read_cell_graphic(ram, cell_numbers[n]))

    # Items: cells with layout value == 6 are item placements.
    items: list[ItemData] = []
    for cy in range(16):
        for cx in range(32):
            if int(layout[cy, cx]) == 6:
                items.append(ItemData(x=cx, y=cy))

    raw_room = bytes(ram[blob_off:blob_end])

    # JSW2 border colour: no explicit byte in the room blob; per
    # JSWED's `Jsw2Room::getBorder` it's derived from the title's
    # leading-space count: `border = (leading_spaces) & 7`. This
    # gives a ZX-style INK index 0..7 for the room's border colour.
    leading_spaces = 0
    for c in title:
        if c == " ":
            leading_spaces += 1
        else:
            break
    border = leading_spaces & 7

    # Parse JSW2 arrow defs (2 bytes each). T5 bit 7 = "has arrows";
    # arrow count follows guardians, then 2 bytes per arrow:
    #   byte 0: starting `m_x` (cycle counter, 0..255) — only matters
    #           for flight phase, NOT the visible spawn column.
    #   byte 1: bit 7 = direction (0=right, 1=left); bits 0-6 = y in
    #           pixels (0..127).
    #
    # JSW2's runtime moves `m_x` by ±1 per tick and renders the arrow
    # only when `0 <= m_x < 32`. So the visible spawn-edge is the
    # entry side of the room, and the arrow walks across to the
    # opposite edge then wraps. We place each arrow at the entry
    # edge: right-flying → x=0 (left edge), left-flying → x=240
    # (= 256 - 16, the right edge minus the 16-px sprite width).
    arrows: list[tuple[int, int, int]] = []  # (x_px, y_px, direction)
    if t5 & 0x80 and arrow_count:
        arrow_addr = after_title + 5 + (1 if t4 & 0x10 else 0) + 7 * n_guardians + 1
        for k in range(arrow_count):
            ay = int(ram[arrow_addr + 2 * k + 1])
            direction = 2 if (ay & 0x80) else 3   # 2=Left, 3=Right
            ax_px = 240 if direction == 2 else 0
            arrows.append((ax_px, ay & 0x7F, direction))

    room = Room(
        id=rid,
        source="ram",
        addr=blob_off,
        title=title,
        layout=layout,
        tile_palette=palette,
        tiles={},
        exits=exits,
        border=border,
        guardian_table=after_title + 4,  # for parse_room_guardians_jsw2
        raw=raw_room,
        is_attribute_layout=False,
        tile_role_map=engine.tile_role_map,
        tile_mirror_map=engine.tile_mirror_map,
        conveyor=None,
        ramp=None,
        items=items,
    )
    # Attach JSW2-specific metadata for downstream consumers via
    # named attributes (so importer can reuse without reparsing).
    room._jsw2_cell_numbers = cell_numbers  # type: ignore[attr-defined]
    room._jsw2_t4 = t4                       # type: ignore[attr-defined]
    room._jsw2_t5 = t5                       # type: ignore[attr-defined]
    room._jsw2_arrows = arrows               # type: ignore[attr-defined]
    room._jsw2_has_rope = bool(t4 & 0x80)    # type: ignore[attr-defined]
    return room


def _parse_room_guardians_jsw2(snap: "Snapshot",
                               room: "Room") -> list["GuardianRef"]:
    """Decode JSW2's 7-byte guardian definitions for one room. Each
    guardian is a fully self-contained def (no ix indirection).
    `room.guardian_table` was set during room build to the address of
    the room's `T4` byte; guardians follow `T4` (and optionally `T5`).

    Maps the JSW2 packed format onto our `GuardianRef` so downstream
    consumers handle JSW2 and JSW48/64 uniformly. Notes on field
    correspondence (JSW2 → GuardianRef):

    * JSW2 has no global entity-def table; we synthesise `def_idx`
      from the per-room slot index (0..7) and `ix` from `byte[4]`.
    * `kind` ∈ {"horiz", "vert"}: from byte[6] bit 7.
    * `x` (px): `(byte[4] & 0x7F) * 2`. JSW2 stores X in 2-px units.
    * `y` (px): `(byte[5] & 0x7F)`. JSW2 stores Y in 1-px units.
    * `direction`: 1=down/3=right when major-step is positive; 0=up
      / 2=left when negative. Our Tiled Direction enum
      (0=Up,1=Down,2=Left,3=Right) is the same as for JSW48.
    * `mirrored`: True when major-step is negative (so the runtime
      has to draw the sprite mirrored from the canonical pose).
    * `sprite_page`: 9-bit field
      `byte[2] | ((byte[4] >> 7) << 8)` — see §12 of
      `docs/JSW2_FORMAT_NOTES.md`.
    * `base_sprite`: 0 (JSW2 frames are sequential within the
      sprite-page index space; there is no JSW1-style "base in
      high-nibble of `ix`" packing).
    * `frame_mask`: `byte[6] & 3` (animation-cycle mask; reachable
      frames are `0..mask`, doubled to `4..4+mask` if byte[6] bit 6
      is set for direction-dependent frames).
    * `initial_frame`: 0 — the "starting frame" inside the cycle
      doesn't apply the same way; mostly a JSW1 concept. The JSW2
      runtime uses `byte[0]` (initial tick countdown) for movement
      phasing, not animation phasing.
    * `raw_def`: the original 7 bytes, padded to 8 (extra byte = 0)
      so callers that index `raw_def[0..7]` still work.
    """
    ram = snap.ram
    t4_addr = room.guardian_table
    if t4_addr <= 0 or t4_addr + 1 > len(ram):
        return []
    t4 = int(ram[t4_addr])
    if not (t4 & 0x10):
        cursor = t4_addr + 1
    else:
        cursor = t4_addr + 2
    n = t4 & 0x0F
    if n > 8:
        return []
    out: list[GuardianRef] = []
    for slot in range(n):
        off = cursor + 7 * slot
        if off + 7 > len(ram):
            break
        defb = tuple(int(b) for b in ram[off:off + 7])
        out.append(_jsw2_decode_hv_record(ram, defb, slot))

    # JSW2 patch-vector specials. T5's low 5 bits select a special-case
    # routine in the dispatch table at `$8361`. A handful of those
    # specials inject extra guardians at room load:
    #   * Lift pairs — IDs {2, 3, 4, 5, 19, 21, 24}, two HV-guardian
    #     records sourced from JSW2_LIFT_TABLE at the offset given by
    #     JSW2_LIFT_PAIR_OFFSET (per JSWED's `checkSpecials` switch).
    #   * Toilet — ID 9, one stationary HV-guardian record at
    #     JSW2_TOILET_RECORD. The JSW2 toilet is *deadly*, unlike the
    #     `HARMLESS`-flagged jsw-gorgeous toilet that mirrors JSW1's.
    # Emit each as a synthetic GuardianRef so the existing emitter
    # path handles sprite resolution + (for lifts) route generation.
    t5 = getattr(room, "_jsw2_t5", 0) or 0
    patch_idx = t5 & 0x1F
    lift_offset = JSW2_LIFT_PAIR_OFFSET.get(patch_idx)
    if lift_offset is not None:
        for li in range(2):
            off = JSW2_LIFT_TABLE + lift_offset + 7 * li
            if off + 7 > len(ram):
                break
            defb = tuple(int(b) for b in ram[off:off + 7])
            out.append(_jsw2_synth_lift(ram, defb, li))
    elif patch_idx == 9:
        if JSW2_TOILET_RECORD + 7 <= len(ram):
            defb = tuple(int(b) for b in ram[JSW2_TOILET_RECORD:
                                             JSW2_TOILET_RECORD + 7])
            out.append(_jsw2_synth_toilet(ram, defb))

    # JSW2 arrows — stored after guardians, parsed during _build_room
    # and stashed on room._jsw2_arrows as a list of (x_px, y_px, dir).
    # Emit each as an Arrow-kind GuardianRef so the importer pipeline
    # handles them uniformly with JSW2's other entities.
    arrows = getattr(room, "_jsw2_arrows", None) or []
    for ai, (ax, ay, adir) in enumerate(arrows):
        out.append(GuardianRef(
            def_idx=0x80 + ai,   # synthetic def_idx so dedup keys
                                 # don't collide with real guardians
            ix=0,
            kind="arrow",
            x=ax, y=ay,
            direction=adir,
            mirrored=(adir == 2),
            sprite_page=0,
            base_sprite=0,
            initial_frame=0,
            frame_mask=0,
            raw_def=(0, 0, 0, 0, 0, 0, 0, 0),
            sprite_frame0_addr=0,
            route_override=None,
        ))
    return out


# ---------------------------------------------------------------------------
# end JSW2
# ---------------------------------------------------------------------------


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
class PortalData:
    """A cavern's exit/portal — the `MM_EXIT` cell in Manic-style packs
    and the door/gate in JSW64. Coordinates are in tiles. `attribute`
    is the ZX colour byte for the portal sprite.
    """

    x: int
    y: int
    attribute: int
    target_room: int = 0
    target_x: int = 0
    target_y: int = 0


def parse_portal(room: "Room") -> PortalData | None:
    """Decode the JSW64/Manic-DD portal from a room's raw bytes.

    Per JSWED `Jsw64Room::getPortal` (`j64room.cxx:331`):
      $EE..$EF : 16-bit sprite address (`0` = no portal)
      $F0       : x in bits 0-4, y_low3 in bits 5-7
      $F1 bit 0 : y_high1
      $F4       : portal attribute (ZX colour byte)
      $F5       : target room id
      $F6       : target x in bits 0-4, target y_low3 in bits 5-7
      $F8 bits 4-7 : target y_high

    Returns None when the room block has no portal address set (cavern
    has no exit) or the raw block is too short.
    """
    raw = room.raw
    if not raw or len(raw) < 0xF9:
        return None
    sprite_addr = int(raw[0xEE]) | (int(raw[0xEF]) << 8)
    if sprite_addr == 0:
        return None
    f0 = int(raw[0xF0])
    f1 = int(raw[0xF1])
    x = f0 & 0x1F
    y = ((f0 & 0xE0) >> 5) | ((f1 & 1) << 3)
    attribute = int(raw[0xF4])
    target_room = int(raw[0xF5])
    f6 = int(raw[0xF6])
    f8 = int(raw[0xF8])
    target_x = f6 & 0x1F
    target_y = ((f6 & 0xE0) >> 5) | ((f8 >> 4) & 0x08)
    return PortalData(x=x, y=y, attribute=attribute,
                      target_room=target_room,
                      target_x=target_x, target_y=target_y)


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
    kind: str                    # one of: horiz / vert / rope / arrow / lift / toilet
                                 # / diag_nw_se / diag_ne_sw / scenery / switch / opening_wall
    x: int                       # initial x in pixels (0..255)
    y: int                       # initial y in pixels (0..127)
    direction: int | None        # Tiled Direction enum: 0=Up 1=Down 2=Left 3=Right; None for rope
    mirrored: bool               # MIRROR flag for stairs/conveyor-style direction
    sprite_page: int             # `defb[5]` — engine sprite page (high byte of address)
    base_sprite: int             # `(ix >> 5) & 7` — non-cycling bits of frame index
    initial_frame: int           # `defb[0]` bits 5-6 — starting animation-counter value
    frame_mask: int              # `defb[1]` bits 5-7 — animation cycle mask
    raw_def: tuple[int, ...]     # full 8 def bytes, for debugging
    # JSW2-only: address of frame 0 of this guardian's sprite. JSW2
    # stores a 9-bit *frame index* (not a Z80 page) in its 7-byte def
    # and the runtime computes `JSW2_SPRITES + 32 * frame_index`. JSW1
    # / JSW128 / JSW64 leave this 0 and `guardian_sprite_frames` falls
    # back to the `(sprite_page << 8) + frame * 32` formula.
    sprite_frame0_addr: int = 0
    # JSW2 diagonal-guardian override. When set, the importer skips
    # `raw_def[6]/[7]`-based axis-aligned route synthesis and emits
    # the polyline directly from these waypoints. Each tuple is
    # (x_px, y_px) — sprite top-left absolute coords. The first
    # waypoint is the route object's origin in the TMX; subsequent
    # waypoints become signed relative `dx,dy` polyline points.
    # Edge bounces and forced reversals each add a waypoint, so the
    # multi-step path is preserved (e.g. Eggoids bouncing off walls,
    # INCREDIBLE-'s simple back-and-forth along the staircase).
    # None on JSW1/128/64 and on pure-horiz/pure-vert JSW2 guardians.
    route_override: tuple[tuple[int, int], ...] | None = None
    # JSW2 per-guardian colour resolved through the GUARDINKS palette
    # at `$70A9`. Stored as a Tiled-ready `#AARRGGBB` hex string. Other
    # engines leave this at the default (white = `#ffffffff`).
    color_rgba: str = "#ffffffff"

    @property
    def displayed_frame_at(self) -> int:
        """Frame index *currently visible* given this instance's
        `base_sprite` + `initial_frame` + `frame_mask`. JSW1 computes
        the live frame as `(counter & mask) | (base_sprite & ~mask)` —
        mask bits cycle, the rest stay fixed at `base_sprite`. So a
        guardian with `base_sprite=3, mask=0` always shows frame 3
        (the barrel); one with `base_sprite=0, mask=2` cycles 0↔2."""
        m = self.frame_mask
        return (self.initial_frame & m) | (self.base_sprite & ~m & 0x07)


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
# Per skoolkit `analysis/jsw_annotated_source/jsw_to_tmx.py:660-662` and
# the JSW1 disassembly: byte at $A500+N is the LOW byte of the 16-bit
# word (carries x and y_low_bits), byte at $A400+N is the HIGH byte
# (carries room and y_high_bit). Confirmed against item 240 (the first
# of "The Off Licence"'s wine bottles, expected at room 0 / x=19 / y=4).
_ITEMS_TABLE_HIGH_ADDR = 0xA400
_ITEMS_TABLE_LOW_ADDR = 0xA500
_ITEMS_FIRST_INDEX = 173
_ITEMS_LAST_INDEX = 255


# JSW64 items table — schema per JSWED 2.3.7's `Jsw64Game::Jsw64Game()`
# constructor (file `j64game.cxx:61-69`) and `JswGame::itemPos`
# (`jswgame.cxx:205-219`). Two parallel 256-byte tables indexed by
# slot N ∈ 0..255:
#
#   - "stat/room" byte: room id (low 6 or 7 bits per variant mask),
#     plus Y high bit in bit 7.
#   - "xy" byte: X in low 5 bits, Y low-3-bits in upper 3 bits.
#
# The TABLE LOCATION depends on the variant byte at `$85C9`:
#
#   V / W (`m_itemBase = 0xC000`, `m_itemMask = 0x7F`)
#     stat byte: bank 0 at offset N (= `$C000+N` when bank 0 paged)
#     xy byte:   default-banking `$A500+N`
#
#   X / Y / YY / Z / Manic-DD (default case — `m_itemBase = 0xA400`,
#                              `m_itemMask = 0x3F`)
#     stat byte: default-banking `$A400+N`
#     xy byte:   default-banking `$A500+N`
#
# `itemCount` byte at `$85CA` gives the lowest valid slot index —
# entries below it are reserved engine workspace, not items. JSW1's
# 173-item-floor moved to `$A3FF`; J64 relocates to `$85CA`.
#
# Y reconstruction (4 bits in pixel units, multiples of 8):
#     Y = ((xy & 0xE0) >> 2) | ((stat & 0x80) >> 1)
#     → bits 5..3 from xy[7..5], bit 6 from stat[7]
#   range 0..120, divisible by 8 = tile rows 0..15.
_JSW64_VARIANT_ADDR = 0x85C9    # peek -> ASCII variant letter
_JSW64_ITEM_COUNT_ADDR = 0x85CA  # peek -> lowest valid slot index
_JSW64_ITEM_XY_ADDR = 0xA500     # default-banking, X/Y byte (all variants)
_JSW64_ITEM_STAT_DEFAULT_ADDR = 0xA400  # X/Y/Z/YY/Manic-DD stat byte
_JSW64_ITEM_STAT_VW_BANK = 0     # V/W stat byte lives in bank 0 at offset N


def _engine_has_jsw48_items_table(engine: Engine) -> bool:
    """Engines that share JSW48's items-table format and address."""
    return engine.name in ("JSW48", "JSW48-JGH", "JSW128")


def _engine_has_jsw64_items_table(engine: Engine) -> bool:
    """Engines that use the JSW64 split-bank items table.
    Manic-DD reuses JSW64-Z packaging end-to-end (per its readme:
    "using the JSW64 game engine"; bank 2 string
    `"JET-SET WILLY Room format is Z"`), so the same items decode
    applies."""
    return engine.name.startswith("JSW64-") or engine.name == "Manic-DD"


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


def _parse_items_jsw64(snap: Snapshot,
                       populated_rooms: int | None = None
                       ) -> dict[int, list[ItemData]]:
    """JSW64-family items decode, dispatching by variant byte at `$85C9`.

    Y comes out as a tile-row index 0..15 (the underlying field is a
    pixel y on multiples of 8 — divided here so callers get the same
    tile units as JSW48 / JSW128).

    Verified against ManicMinerRedux's MMDD level data: cavern 0 ("The
    Hollow Chamber") items at `$A400/$A500` decode to the exact (x, y)
    positions Redux lists.
    """
    by_room: dict[int, list[ItemData]] = {}
    ram = snap.ram
    if _JSW64_ITEM_XY_ADDR + 255 >= len(ram):
        return by_room
    variant = chr(int(ram[_JSW64_VARIANT_ADDR])) if _JSW64_VARIANT_ADDR < len(ram) else ''
    if variant in ('V', 'W'):
        stat_bank = snap.banks.get(_JSW64_ITEM_STAT_VW_BANK)
        if stat_bank is None or len(stat_bank) < 256:
            return by_room
        stat_bytes = [int(stat_bank[i]) for i in range(256)]
        room_mask = 0x7F
    else:
        if _JSW64_ITEM_STAT_DEFAULT_ADDR + 255 >= len(ram):
            return by_room
        stat_bytes = [int(ram[_JSW64_ITEM_STAT_DEFAULT_ADDR + i]) for i in range(256)]
        room_mask = 0x3F
    item_count = int(ram[_JSW64_ITEM_COUNT_ADDR]) if _JSW64_ITEM_COUNT_ADDR < len(ram) else 0
    for n in range(item_count, 256):
        stat = stat_bytes[n]
        xy = int(ram[_JSW64_ITEM_XY_ADDR + n])
        if stat == 0 and xy == 0:
            continue
        room = stat & room_mask
        if populated_rooms is not None and room >= populated_rooms:
            continue
        x = xy & 0x1F
        y_pix = ((xy & 0xE0) >> 2) | ((stat & 0x80) >> 1)
        by_room.setdefault(room, []).append(ItemData(x=x, y=y_pix // 8))
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
    if engine.name.startswith("JSW64-") or engine.name == "Manic-DD":
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
    def bytes).

    Mirrors JSWED `Jsw128Guard::getType()` (`j128guard.cxx:905`):
        type = defb[0] & 0x0F
        if type == 8: type = defb[0]   # full byte selects sub-type

    The low-nibble path covers classic JSW1/JSW128 guardians (horiz,
    vert, rope, arrow, diagonals). The full-byte path covers JSW64
    specials (scenery, lift, switch, opening wall).
    """
    if def_idx == 0xFF:
        return None
    low_nibble = defb[0] & 0x0F
    gtype = low_nibble if low_nibble != 8 else defb[0]
    bit7 = (defb[0] >> 7) & 1
    initial_frame = (defb[0] >> 5) & 0x03
    frame_mask = (defb[1] >> 5) & 0x07
    # Per-instance "base sprite" bits in the high nibble of `ix` —
    # these set the non-cycling bits of the displayed frame index, so
    # different guardians sharing the same `sprite_page` (Maria's
    # pieces, the JSW1 multi-entity Evil Head, the Off Licence
    # barrel that lives at frame 3 of code-remnant page $9C) draw
    # the right graphic.
    base_sprite = (ix >> 5) & 0x07
    # Default position decode (most types): JSW128 `Jsw128Guard::draw`
    # reads `x = (m_guard[2] & 0x1F) * 16` and `y = m_guard[3] & 0xFE`.
    # In our 1× pixel coords that's `(ix & 0x1F) * 8` and `defb[3] >> 1`.
    if low_nibble in (1, 9):     # horizontal patrol (1 normal, 9 cycling)
        x = (ix & 0x1F) * 8
        y = defb[3] >> 1
        kind = "horiz"
        direction = 3 if bit7 else 2
        mirrored = not bit7
    elif low_nibble in (2, 7, 10, 15):   # vertical patrol variants
        x = (ix & 0x1F) * 8
        y = defb[3] >> 1
        kind = "vert"
        y_inc = defb[4] if defb[4] < 128 else defb[4] - 256
        direction = 0 if y_inc < 0 else 1
        mirrored = False
    elif low_nibble == 3:        # rope
        x = (ix & 0x1F) * 8
        y = 16
        kind = "rope"
        direction = None
        mirrored = False
    elif low_nibble == 4:        # arrow
        x = 0 if bit7 else 240
        y = ((ix >> 3) << 2) + 8
        kind = "arrow"
        direction = 3 if bit7 else 2
        mirrored = not bit7
    elif low_nibble in (5, 13):  # NW→SE diagonal (incl. cycling)
        x = (ix & 0x1F) * 8
        y = defb[3] >> 1
        kind = "diag_nw_se"
        direction = None
        mirrored = False
    elif low_nibble in (6, 14):  # NE→SW diagonal (incl. cycling)
        x = (ix & 0x1F) * 8
        y = defb[3] >> 1
        kind = "diag_ne_sw"
        direction = None
        mirrored = False
    elif gtype in (0x08, 0x18, 0x28, 0x38, 0x68, 0x88):  # static scenery
        x = (ix & 0x1F) * 8
        y = defb[3] >> 1
        kind = "scenery"
        direction = None
        mirrored = False
    elif gtype == 0x58:          # Lift (vertical platform)
        x = (ix & 0x1F) * 8
        y = defb[3] >> 1
        kind = "lift"
        direction = None
        mirrored = False
    elif gtype == 0x98:          # Switch — interactive trigger
        x = (ix & 0x1F) * 8
        y = defb[3] >> 1
        kind = "switch"
        direction = None
        mirrored = False
    elif gtype == 0xA8:          # Opening wall — per JSWED `drawOpeningWall`
                                  # x/y come from defb[6]/defb[7]:
                                  #   x = (m_guard[6] & 0x1F) * 16
                                  #   y = m_guard[7] & 0xFE
        x = (defb[6] & 0x1F) * 8
        y = defb[7] >> 1
        kind = "opening_wall"
        direction = None
        mirrored = False
    else:
        return None
    # Guardian ink lives in `defb[1] & 0x0F` for JSW48 / JSW128 / all
    # JSW64 variants (they share `JswGuardian::getInk` in JSWED). Rope
    # and arrow entities don't have a meaningful colour at the engine
    # level — they're drawn from fixed bitmaps using room/global state,
    # not the def's ink — but we still pull bits 0-3 so the TMX has a
    # plausible value rather than the default white.
    color_rgba = _zx_attr_to_rgba(defb[1] & 0x0F)
    return GuardianRef(
        def_idx=def_idx, ix=ix, kind=kind, x=x, y=y,
        direction=direction, mirrored=mirrored,
        sprite_page=int(defb[5]), base_sprite=base_sprite,
        initial_frame=initial_frame, frame_mask=frame_mask,
        raw_def=tuple(int(b) for b in defb),
        color_rgba=color_rgba,
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
    if engine.jsw2_directory_ptr_addr is not None:
        return _parse_room_guardians_jsw2(snap, room)
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

    if engine.name.startswith("JSW64-") or engine.name == "Manic-DD":
        # Inline 8-byte defs starting at room offset 0, terminated by
        # 0xFF. Cap by the documented max-instance count per variant.
        # Manic-DD / MMLL inherit JSW64-Z's 8-instance cap (per the
        # MMDD readme: "using the JSW64 game engine"; bank 2 carries
        # the literal "JET-SET WILLY Room format is Z").
        max_instances = {
            "JSW64-V": 13, "JSW64-X": 13,
            "JSW64-W": 8,  "JSW64-Y": 8, "JSW64-YY": 8, "JSW64-Z": 8,
            "Manic-DD": 8,
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
            # JSW64 / Manic-DD store the initial X (bits 0-4) and
            # base_sprite (bits 5-7) in `defb[2]` — same encoding JSW48
            # uses for its per-instance `ix` byte. Per JSWED's
            # `Jsw128Guard::draw` (`j128guard.cxx:198`):
            #     x = (m_guard[2] & 0x1F) * 16
            #     y = (m_guard[3] & 0xFE)
            # (the *16 scaling is JSWED's 2x display; our pixel coords
            # use *8 / `>> 1` respectively, matching the JSW48 decoder).
            # Pass `defb[2]` as the synthetic `ix` so the JSW48 decoder
            # reads x and base_sprite from the right byte; `defb[3]`
            # remains the y source via the type-bit branches.
            gref = _decode_jsw48_def(slot, defb[2], defb)
            if gref is not None:
                out.append(gref)
        return out

    return []


def guardian_sprite_frames(snap: Snapshot, gref: GuardianRef) -> list[bytes]:
    """Return the list of 32-byte frame bitmaps for `gref`, one entry
    per reachable animation frame.

    JSW1 computes the displayed frame as
        `(counter & mask) | (base_sprite & ~mask)`
    so the reachable frame *indices* on this sprite page are the
    union of that formula over `counter ∈ 0..mask` (sub-mask trimmed
    for sparse masks). For `mask=0` only the static `base_sprite`
    frame is reachable — that's how the Off Licence barrel
    (`base_sprite=3, mask=0`) lands on the actual barrel graphic at
    page-offset 3 even though `initial_frame=0`."""
    if gref.sprite_frame0_addr:
        page_addr = int(gref.sprite_frame0_addr)
    else:
        page_addr = int(gref.sprite_page) << 8
    mask = int(gref.frame_mask)
    base = int(gref.base_sprite)
    fixed = base & (~mask & 0x07)
    if mask == 0:
        reachable = [fixed]
    else:
        seen: list[int] = []
        for c in range(mask + 1):
            if (c & mask) != c:
                continue  # unreachable cycling value
            f = (c & mask) | fixed
            if f not in seen:
                seen.append(f)
        reachable = seen
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
        return _parse_items_jsw64(snap, engine.populated_rooms)
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
    # Manic Miner per-cavern air supply on the JSWED 0..161 scale
    # (decoded from cavern bytes `700`/`701` per
    # `docs/MANIC_MINER_FORMAT_NOTES.md`). 0 = unset / not from a
    # Manic snapshot; non-Manic engines leave this at the default.
    air_supply: int = 0

    @property
    def superjump(self) -> bool:
        """True when the room has the superjump flag set in border byte
        (`$DE` bit 7). Effective in JSW128 at hacklevel 5+ and in
        JSW64; ignored in stock JSW48."""
        return bool(self.border & 0x80)

    @property
    def rigor_mortis(self) -> bool:
        """True when guardians in this room are frozen until all items
        in the room are collected (`$DE` bit 6). JSW128+/JSW64."""
        return bool(self.border & 0x40)

    @property
    def willy_color(self) -> int:
        """Willy's per-room ZX INK colour override (`$DE` bits 3-5).
        Standard ZX INK 0..7; 7 = white (the stock-JSW1 default). Set
        per-room in JSW128/JSW64 builds that recolour Willy for theme
        reasons (e.g. dark caverns)."""
        return (self.border >> 3) & 0x07


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


def _decode_manic_air_supply(buf: np.ndarray, off: int,
                             coarse_off: int, fine_off: int) -> int:
    """Decode JSWED-style air supply from a pair of per-cavern bytes
    into the 0..162 spin scale. Used by both the stock Manic Miner
    cavern format (`(700, 701)`) and the JSW64 family (`($DF, $E0)`,
    per JSWED `j64roomform.cxx:89-100`). Returns 0 when the bytes are
    out of the snapshot. 162 is the "no air limit" sentinel reserved
    by JSW64 (`coarse_byte == 0xFF`); MM uses the same scheme without
    that sentinel.
    """
    if off + max(coarse_off, fine_off) + 1 > len(buf):
        return 0
    coarse = int(buf[off + coarse_off])
    fine = int(buf[off + fine_off])
    if fine == 0xFF:
        return 162
    if coarse < 37:
        return 0
    air = (coarse - 37) * 6
    if   fine & 0x04: air += 5
    elif fine & 0x08: air += 4
    elif fine & 0x10: air += 3
    elif fine & 0x20: air += 2
    elif fine & 0x40: air += 1
    return max(0, min(162, air))


def _build_room(snap: Snapshot, engine: Engine, rid: int,
                src: str | int, off: int) -> Room:
    buf = _slot_buffer(snap, src)
    if buf is None:
        raise KeyError(f"snapshot is missing source {src!r}")
    title = _read_title(buf, off, engine.title_offset, engine.title_length)
    layout = _read_layout(buf, off, engine)
    palette = _read_tile_palette(buf, off, engine)
    # Stock Manic Miner has no L/R/U/D directional exits — caverns are
    # navigated via the MM_EXIT portal sprite, not via byte fields.
    # MMDD/MMLL use JSW64-Z's exit bytes but most of them are 0xFF
    # (no exit) since the portal does the work.
    if engine.name == "Manic":
        exits = (-1, -1, -1, -1)
    else:
        exits = _read_exits(buf, off, engine)
    # Border byte location differs per engine: JSW48/128/64 carry it at
    # the canonical `$DE` slot; stock Manic Miner stores it at `$27B`
    # (= cavern offset 627) in the low 3 bits. Manic-DD uses JSW64-Z's
    # `$DE` byte like its parent engine.
    if engine.name == "Manic":
        border = int(buf[off + 0x27B]) & 0x07 if off + 0x27C <= len(buf) else 0
    else:
        border = int(buf[off + ROOM_BORDER_OFFSET])
    # JSW48/128/64 carry a 16-bit guardian-table pointer at `$DF..$E0`.
    # Stock Manic Miner stores guardians inline in the cavern record
    # (h-pair at `$2BE`, v-pair at `$2DD`), so the field is unused.
    # MMDD/MMLL (Manic-DD) overload `$DF..$E0` for the air-supply pair
    # — the JSW64 runtime treats it as guardian-ptr-OR-air depending
    # on context, but for *static* extraction we just want the air
    # value and skip the gptr read.
    if engine.name == "Manic" or engine.is_manic_style:
        gptr = 0
    else:
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

    # Air supply — generic extraction driven by `engine.air_supply_offset`.
    # Stock Manic Miner reads from `(700, 701)`; Manic-DD (JSW64-Z
    # packaging used by MMDD/MMLL) reads from `($DF, $E0)`. Non-Manic
    # engines leave the offset `None` so this returns 0.
    if engine.air_supply_offset is not None:
        air_supply = _decode_manic_air_supply(
            buf, off, engine.air_supply_offset[0], engine.air_supply_offset[1]
        )
    else:
        air_supply = 0
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
        air_supply=air_supply,
    )


def read_room(snap: Snapshot, engine: Engine, room_id: int) -> Room:
    """Decode a single room block by its sequential id across all slots."""
    if engine.jsw2_directory_ptr_addr is not None:
        n = _jsw2_count_rooms(snap)
        if room_id < 0 or room_id >= n:
            raise IndexError(
                f"room_id {room_id} outside JSW2 directory count={n}"
            )
        return _build_room_jsw2(snap, engine, room_id,
                                _jsw2_room_offset(snap, room_id))
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
    if engine.jsw2_directory_ptr_addr is not None:
        for rid, _src, blob_off in _jsw2_walk_directory(snap, engine):
            yield _build_room_jsw2(snap, engine, rid, blob_off)
        return
    items_by_room = parse_items(snap, engine)
    yielded = 0
    cap = engine.populated_rooms
    for rid, src, off in _walk_slots(engine):
        if cap is not None and yielded >= cap:
            break
        buf = _slot_buffer(snap, src)
        if buf is None:
            continue
        if skip_empty and not _looks_like_jsw_room(
            buf, off, engine.title_offset, engine.title_length
        ):
            continue
        room = _build_room(snap, engine, rid, src, off)
        room.items = list(items_by_room.get(rid, ()))
        yielded += 1
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
