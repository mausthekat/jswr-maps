# Standalone Map Packs

This document describes how to create and use self-contained map packs with custom tile graphics. The shipping reference implementation is **`tmx/content/jsw-gorgeous`** (packed into `assets/maps/jsw-gorgeous.jsw`) — refer back to it whenever the description below is ambiguous.

## Overview

A standalone map pack (`.jsw` file) bundles:
- Room data (layout, enemies, pickups, connections)
- One or more **JSWC tileset collections** — the base collection plus zero or more variants (e.g. 2x high-res, ZX color-clash, alternate art style)
- Optional **per-room tileset overrides** — distinct tile PNGs for individual rooms, packed as `tiles_<suffix>_room<NNN>` entries
- V5 custom data (`default_tileset` — the tileset the game activates on load)

This allows a map to travel as a single `.jsw` file without relying on the base game's tile graphics, and lets the player cycle between variants with F9.

### Prerequisites

Before packing, you need:
- **TMX room files** (`NNN.tmx`) — created in Tiled. See [JSWR_ROOM_FILE_FORMAT.md](../../docs/formats/JSWR_ROOM_FILE_FORMAT.md) for room format details.
- **Category tileset PNGs** (`tiles_solid.png`, `tiles_stairs.png`, etc.) — tile graphics organized by category, 16 tiles per row.
- **TSX tileset definitions** (`tiles_solid.tsx`, etc.) — optional, only required when `tilesets.json` is absent.
- **`tilesets.json`** — the preferred manifest listing variants (see below).
- **`.tiled-project`** with `DefaultTileset` set if the pack has more than one variant.

See [TILESET_PROPERTIES.md](TILESET_PROPERTIES.md) for tileset property details.

---

## Pack Creation

### Canonical command: `tmx_to_jsw.py --pack`

The build pipeline autodetects standalone maps by calling `_detect_custom_tilesets()`: if any TMX file in the folder references a **local** `tiles_<category>.tsx` (i.e. not via `../../tilesets/`), the `--pack` output is wrapped in a `ContentType.PACKS` pack with a `tiles` entry plus every variant listed in `tilesets.json`. No separate command is required.

```bash
# Build jsw-gorgeous (the shipping reference) into a standalone pack
uv run python build_scripts/tmx/tmx_to_jsw.py tmx/content/jsw-gorgeous --pack
# → assets/maps/jsw-gorgeous.jsw  (≈493 KB, content_type=PACKS)
```

**Important:** do **not** run the converter without `--pack` for a standalone map. The folder-mode output (`assets/maps/<mapname>/NNN.jsw`) is loaded by `load_rooms_from_folder()`, which has no `tile_loader` hook and will silently fall back to the base game's tiles — the map will look wrong. If you accidentally create a per-room folder for a standalone map, delete it so the resolver falls through to the pack.

### Legacy: `scripts/pack_map_standalone.py`

An older standalone-only packer script still ships at `scripts/pack_map_standalone.py`. It reuses the shared helpers from `tmx_to_jsw.py` (`parse_tmx_room`, `pack_tileset_variants`, etc.) but **does not read `DefaultTileset`, does not emit V5 custom data, and does not validate game modes**. Prefer `tmx_to_jsw.py --pack` unless you have a specific reason to use the legacy path.

### Input Folder Structure (jsw-gorgeous example)

```
tmx/content/jsw-gorgeous/
├── jsw-gorgeous.tiled-project   # DefaultTileset = "2x", MapName = "JSW Gorgeous", …
├── tilesets.json                # Variant manifest (see below)
├── 001.tmx … 060.tmx            # 60 room files
├── tiles_solid.png              # Base 8px variant (empty suffix)
├── tiles_solid.tsx              # Tiled tileset definition
├── tiles_stairs.png / .tsx
├── tiles_platform.png / .tsx
├── tiles_hazard.png / .tsx
├── tiles_decoration.png / .tsx
├── tiles_conveyor.png / .tsx
├── tiles_solid_2x.png           # "2x" variant — 16px version of each category
├── tiles_stairs_2x.png
├── …
├── tiles_solid_jsw1.png         # "jsw1" variant — ZX color-clash art
├── …
├── tiles_solid_jsw1-e.png       # "jsw1-e" variant — "Noble" enhanced JSW1 style
├── …
└── tilesets/
    ├── jsw1/                    # Per-room overrides for the jsw1 variant
    │   ├── tiles_conveyor_jsw1_001.png
    │   ├── tiles_conveyor_jsw1_002.png
    │   └── …                    # ~232 files: one per (category, room) with custom art
    └── jsw1-e/                  # Same, for the jsw1-e variant
```

Room filenames are `NNN.tmx`. Category PNGs follow `tiles_<category>[_<suffix>].png`. Per-room overrides live under `tilesets/<suffix>/tiles_<category>_<suffix>_<NNN>.png`.

### Tileset Manifest (`tilesets.json`)

Preferred source of variant metadata. The key `""` is the base variant; other keys are the filename suffixes that identify additional variants. Each entry declares its own display name and `color_clash` flag independently.

**jsw-gorgeous's manifest:**

```json
{
    "": {"name": "Gorgeous (8px)", "color_clash": false},
    "2x": {"name": "Gorgeous (16px)", "color_clash": false},
    "jsw1": {"name": "JSW1 Old School", "color_clash": true},
    "jsw1-e": {"name": "JSW1 Noble", "color_clash": false}
}
```

This produces four pack entries — `tiles` (base 8px), `tiles_2x`, `tiles_jsw1`, `tiles_jsw1-e` — plus one per-room `tiles_jsw1_room<NNN>` / `tiles_jsw1-e_room<NNN>` entry for every PNG under `tilesets/<suffix>/`. Each variant's `color_clash` flag is honoured independently, so the player can F9-cycle between an enhanced mode and a ZX-emulation mode within the same pack.

**TSX fallback:** if `tilesets.json` is absent, `collect_tileset_properties()` reads `TilesetName` and `SupportsColorClash` from `tiles_solid.tsx`. This only yields a single-variant pack (the base), plus whatever `_2x` files `_detect_2x_tilesets()` picks up. Used by a few legacy maps; manifest is preferred for everything new.

### Default Tileset Selection

The `DefaultTileset` property in `.tiled-project` controls which variant the game activates when the map loads. **You can set it to either the manifest *suffix* or the variant's display *name*** — `tmx_to_jsw.py` (in the `--pack` flow, around the `_read_project_default_tileset()` call) resolves a suffix to its name via the manifest before writing the pack.

```
.tiled-project:                        →  resolved display name stored in pack
  "DefaultTileset": "2x"               →  "Gorgeous (16px)"
  "DefaultTileset": "Gorgeous (16px)"  →  "Gorgeous (16px)" (unchanged)
  "DefaultTileset": ""                 →  (empty — game uses first loaded)
```

jsw-gorgeous uses `"2x"`, so the 16px variant is the default on load and the player can F9-cycle to `Gorgeous (8px)`, `JSW1 Old School`, or `JSW1 Noble`.

The resolved name is stored as V5 pack custom data under the key `default_tileset` (UTF-8 encoded) and read by the map registry at startup — see `src/map_registry.py:default_tileset` and `src/map_loading_service.py:_get_default_tileset`.

### GID Validation and Remapping

The script automatically validates that TMX files use the expected 2048-spaced firstGid scheme:

| Tileset | Expected firstGid |
|---------|-------------------|
| tiles_solid | 1 |
| tiles_stairs | 2049 |
| tiles_platform | 4097 |
| tiles_hazard | 6145 |
| tiles_decoration | 8193 |
| tiles_conveyor | 10241 |

If firstGid values don't match, the script:
1. Detects the mismatch and logs it
2. Builds an in-memory GID remap table
3. Applies remapping to all tile data during conversion
4. **Does NOT modify the source TMX files**

This means you can pack TMX files with non-standard firstGid values without editing them first.

### What `tmx_to_jsw.py --pack` Does For Standalone Maps

1. `_detect_custom_tilesets()` scans the first TMX and flips the pack builder into standalone mode if any `tiles_<category>.tsx` reference is local rather than `../../tilesets/…`
2. Reads `tilesets.json` (falls back to `tiles_solid.tsx` properties if absent)
3. Detects tile size from the TMX `tilewidth`/`tileheight` attribute (8 or 16)
4. Converts each TMX to a binary room record (JSWR) and bundles them into an inner `rooms` sub-pack
5. Creates a JSWC collection for the base variant from `tiles_<category>.png`
6. Calls `pack_tileset_variants()` to build a JSWC collection per additional manifest key and per-room override PNGs from `tilesets/<suffix>/`
7. Reads `DefaultTileset` from `.tiled-project`, resolves a suffix via the manifest, and writes the resolved name as V5 pack custom data `default_tileset`
8. Wraps everything in a `ContentType.PACKS` outer pack: `rooms`, `tiles`, `tiles_<suffix>` entries, and `tiles_<suffix>_room<NNN>` entries

### Tileset Variant Detection

**With manifest (`tilesets.json`):** Each non-empty key in the manifest defines a
variant. The packer looks for PNGs named `tiles_<category>_<suffix>.png` matching
each key. Each variant is packed as a separate JSWC collection entry (`tiles_<suffix>`).
Files under `tilesets/<suffix>/tiles_<category>_<suffix>_<NNN>.png` become per-room
override entries named `tiles_<suffix>_room<NNN>`.

**Without manifest (legacy):** only `_2x` PNGs are auto-detected. For each tileset
type, if both the base PNG and the `_2x` PNG exist, the 2x variant is included as
`tiles_2x`. Orphaned `_2x` files are ignored. Per-room overrides are not supported
in this mode.

### Troubleshooting

**Problem: "No TMX files found"**
- Ensure TMX files are named as `NNN.tmx` (e.g., `001.tmx`, `002.tmx`)
- Check the input folder path is correct

**Problem: "tiles_*.png not found"**
- The script expects specific filenames: `tiles_solid.png`, `tiles_stairs.png`, etc.
- Check the tile files exist in the input folder

**Problem: Pack loads but tiles look wrong**
- Verify tile size matches between TMX and PNGs
- Check that the JSWC header tile dimensions match the actual PNG tile dimensions

**Problem: "GID remapping needed" message**
- This is informational, not an error
- The script detected non-standard firstGid values and is correcting them automatically
- Source TMX files are NOT modified; remapping happens in-memory during packing
- The output pack will use the correct 2048-spaced GID scheme

---

## Pack File Structure

```
my-map.jsw (JSWP format, ContentType.PACKS)
│
├── rooms (inner JSWP, ContentType.ROOMS — one JSWR blob per room)
│   ├── Header: "JSWP" + version + room_count + ValidGameModes + …
│   ├── Custom data:
│   │    ├── default_tileset (UTF-8 string)     — V5, set from DefaultTileset
│   │    └── chain_groups / sp_* / …             — other per-map flags
│   ├── Table: [room_id, offset, size] for each room
│   └── Data: Binary room data (tiles, enemies, pickups, spawns, specials)
│
├── tiles (JSWC format — base tileset, manifest key "")
│   ├── Header: tileset_name, supports_color_clash flag
│   └── Tilesets: 6 category tilesets (solid, stairs, platform, hazard, decoration, conveyor)
│       Each tileset contains: type, tile_width, tile_height, tile_count, PNG data
│
├── tiles_<suffix> (JSWC format — additional variants, one per non-empty manifest key)
│   ├── Header: variant name, per-variant supports_color_clash flag
│   └── Tilesets: category tilesets (may differ in resolution/tile count)
│
├── tiles_<suffix>_room<NNN> (JSWC format — per-room override for a variant) [optional]
│   └── One entry per PNG under tilesets/<suffix>/tiles_<category>_<suffix>_<NNN>.png
│
│   Examples (from jsw-gorgeous):
│     tiles                      — "Gorgeous (8px)"    base, color_clash=false
│     tiles_2x                   — "Gorgeous (16px)"   high-res, color_clash=false
│     tiles_jsw1                 — "JSW1 Old School"   color_clash=true
│     tiles_jsw1-e               — "JSW1 Noble"        color_clash=false
│     tiles_jsw1_room001…060     — per-room JSW1 overrides (one per room that customises)
│     tiles_jsw1-e_room001…060   — per-room JSW1 Noble overrides
│
│   Variant names and color_clash flags come from tilesets.json manifest.
│   Without a manifest, only tiles_2x is auto-detected and per-room overrides are not supported.
```

See [JSWP_PACK_FORMAT.md](../../docs/formats/JSWP_PACK_FORMAT.md) for the JSWP container format and [JSWC_TILESET_COLLECTION_FORMAT.md](../../docs/formats/JSWC_TILESET_COLLECTION_FORMAT.md) for the JSWC tileset format.

---

## Tile Encoding

Tiles are encoded as 16-bit values:

```
Bits 15-11: Tileset type (0-5)
Bits 10-0:  Local index within tileset (0-2047)

Encoding: (tileset_type << 11) | local_index
```

| Type | Value | Tileset | TMX firstgid |
|------|-------|---------|--------------|
| 0 | SOLID | tiles_solid.png | 1 |
| 1 | STAIRS | tiles_stairs.png | 2049 |
| 2 | PLATFORM | tiles_platform.png | 4097 |
| 3 | HAZARD | tiles_hazard.png | 6145 |
| 4 | DECORATION | tiles_decoration.png | 8193 |
| 5 | CONVEYOR | tiles_conveyor.png | 10241 |

The TMX firstgid values are spaced 2048 apart to match the encoding scheme.

---

## Runtime Loading

When the game loads a standalone pack:

1. Detects JSWP format (ContentType.PACKS)
2. Reads `tiles` entry and detects JSWC format from magic bytes
3. Parses JSWC header for metadata (`tileset_name`, `supports_color_clash`)
4. Reads tile size from each JSWC tileset's `tile_width`/`tile_height` fields
5. Loads tile graphics into `TileManager._pack_tilesets` dict under the tileset name
6. Scans for additional `tiles_*` entries (e.g. `tiles_2x`, `tiles_jsw1`), loading each as a separate JSWC collection. All styles are registered for F9 cycling
7. If `DefaultTileset` is set in the map registry, activates that style; otherwise uses the first loaded
8. Sets `AssetManager._current_pack_name` for cache keying
9. Detects pack sprite content (checks for `{tileset_name}/guardians`, `/collectibles`, `/willy` folders)
10. Reloads sprites with fallback logic applied
11. Loads rooms from `rooms` sub-pack
12. During rendering, `get_tile_texture()` checks active pack style first, falls back to base pack style, then to global

The pack tiles override global tiles only for the current map. All loaded tileset variants are available for style cycling (F9). Each variant can have its own `supports_color_clash` flag, enabling color clash (ZX) variants independently. Switching maps or returning to the lobby clears all pack tilesets.

### Sprite Fallback Behavior

Standalone packs typically include only custom tiles, not custom sprites. The game automatically uses built-in sprites based on the pack's configuration:

| Pack Configuration | Sprite Fallback |
|-------------------|-----------------|
| `supports_color_clash=true` | Built-in "original" sprites (ZX-style) |
| `supports_color_clash=false` | Built-in "enhanced" sprites (default) |
| Pack includes sprites | Pack's own sprites |

This is detected per-category (guardians, collectibles, willy), so a pack could provide custom guardians while using built-in collectibles.

See [TILESET_PROPERTIES.md](TILESET_PROPERTIES.md) for detailed fallback rules.
