# Tileset Properties Specification

## Overview

Tilesets in JSW Redux can define properties that control graphics style behavior and tile categorization. These properties are read from Tiled TSX (tileset) files.

## Property Locations

Properties can be defined at two levels:

1. **Tileset-level properties** - Apply to the entire tileset
2. **Per-tile properties** - Apply to individual tiles

---

## Tileset-Level Properties

These properties are defined in the `<properties>` element at the root of a TSX file:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<tileset name="tiles_solid" tilewidth="8" tileheight="8" tilecount="208" columns="16">
  <properties>
    <property name="supports_color_clash" type="bool" value="true"/>
    <property name="tileset_name" value="original"/>
  </properties>
  <image source="tiles_solid.png" width="128" height="104"/>
</tileset>
```

### `supports_color_clash` (Boolean)

Indicates whether the tileset supports the ZX Spectrum color clash shader effect.

| Value | Behavior |
|-------|----------|
| `true` | A "(ZX)" variant style is added to the graphics menu |
| `false` | No color clash variant (default) |

**Example:**
- Tileset "original" with `supports_color_clash=true` creates styles: "original", "original_zx"
- Tileset "enhanced" with `supports_color_clash=false` creates only: "enhanced"

### `tileset_name` (String)

Groups related tileset files under a common name for the graphics style menu.

If not specified, defaults to the asset folder name (e.g., "enhanced", "original").

**Use case:** Multiple TSX files (tiles_solid.tsx, tiles_stairs.tsx, etc.) in the same style folder should use the same `tileset_name` so they appear as one option in the menu.

> **Note:** For standalone map packs, these TSX properties are superseded by the
> `tilesets.json` manifest file when present. The manifest allows per-variant
> names and color clash settings. See [STANDALONE_MAPS.md](STANDALONE_MAPS.md).

---

## Per-Tile Properties

Individual tiles can have properties that override their default categorization.

```xml
<tile id="5">
  <properties>
    <property name="tile_type" value="decoration"/>
    <property name="Direction" type="int" value="2"/>
  </properties>
</tile>
```

### `tile_type` (String)

Overrides the tile's category, which is normally determined by which tileset file it belongs to.

| Value | Tileset Type | Description |
|-------|--------------|-------------|
| `solid` | TILESET_SOLID | Blocks movement from all directions |
| `stairs` | TILESET_STAIRS | Diagonal movement tiles |
| `platform` | TILESET_PLATFORM | One-way platforms (pass through from below) |
| `hazard` | TILESET_HAZARD | Kills the player on contact |
| `deadly` | TILESET_HAZARD | Alias for hazard |
| `decoration` | TILESET_DECORATION | Non-solid background tiles |
| `background` | TILESET_DECORATION | Alias for decoration |
| `conveyor` | TILESET_CONVEYOR | Moving platforms |

**Use case:** A stairs tileset may contain decorative stair-like tiles that shouldn't function as stairs. Setting `tile_type="decoration"` on those tiles excludes them from stair behavior.

### `Direction` (Integer) - Stairs Only

For tiles in the stairs tileset, specifies the stair direction:

| Value | Direction | Visual |
|-------|-----------|--------|
| `2` | Left | Walk left to ascend (\\) |
| `3` | Right | Walk right to ascend (/) |

If no `Direction` property is set on any tile in a stairs tileset, direction is determined by column position (even columns = right, odd columns = left).

---

## Graphics Style System

### Built-in Tilesets

JSW Redux includes built-in tilesets that are always available:

| Tileset | Color Clash Support | Styles Created |
|---------|---------------------|----------------|
| enhanced | No | "ENHANCED" |
| original | Yes | "ORIGINAL", "ORIGINAL (ZX)" |

### Custom Map Packs

When a map pack includes its own tiles (in a `tiles` sub-pack), those tilesets **replace** the built-in ones:

1. Pack is loaded with custom tiles
2. Built-in tilesets are cleared
3. Pack's tileset is registered from its TSX properties
4. Graphics style switches to the pack's tileset

When the pack is unloaded (switching to a map without custom tiles), the built-in tilesets are restored.

**Example:** A "gorgeous" map pack with `supports_color_clash=true` would show menu options: "GORGEOUS", "GORGEOUS (ZX)"

### Sprite Fallback for Custom Packs

Map packs may include only tiles without custom guardians, collectibles, or Willy sprites. In this case, the game uses smart fallback to built-in sprite styles:

| Pack Tileset Name | Pack Has Sprites? | SupportsColorClash | Fallback Sprite Style |
|-------------------|-------------------|-------------------|----------------------|
| "original" | No | Any | Built-in "original" |
| "enhanced" | No | Any | Built-in "enhanced" |
| Custom (e.g., "Gorgeous") | No | `true` | Built-in "original" |
| Custom (e.g., "Gorgeous") | No | `false` | Built-in "enhanced" |
| Any | Yes | Any | Pack's sprites |

**Key rule:** If a custom pack supports color clash, it implies the tiles are ZX-style, so sprites fall back to "original" style to match. Otherwise, sprites fall back to "enhanced" (the default).

The game detects pack sprite content by checking for these folders in the sprite path:
- `{tileset_name}/guardians/` - Guardian sprites
- `{tileset_name}/collectibles/` - Collectible sprites
- `{tileset_name}/willy/` - Player sprites

Each category falls back independently - a pack could provide custom guardians but use built-in collectibles.

### Style Naming Convention

- Base styles: Use tileset name directly (e.g., "enhanced", "original", "gorgeous")
- ZX variants: Append `_zx` suffix (e.g., "original_zx", "gorgeous_zx")

The menu displays these as:
- Base: "ENHANCED", "ORIGINAL", "GORGEOUS"
- ZX variant: "ORIGINAL (ZX)", "GORGEOUS (ZX)"

---

## File Locations

For built-in styles, TSX files are read from:
```
assets/sprites/{style}/tiles/tiles_solid.tsx
```

For map packs, TSX files are read from within the pack's `tiles` sub-pack.

---

## Implementation Notes

### Reading Properties

Properties are read at two points:

1. **Asset loading** (`assets.py`): Registers available tilesets and their color clash support
2. **TMX conversion** (`tmx_to_jsw.py`): Reads per-tile properties for encoding

### Fallback Behavior

- If `tileset_name` is not set, the folder name is used
- If `supports_color_clash` is not set, defaults to `false`
- If `tile_type` is not set on a tile, the tileset file determines the type
- If `Direction` is not set on stairs, column parity determines direction

### Cache Considerations

Tileset properties are cached after first read. Call `clear_tileset_property_caches()` in tmx_to_jsw.py if reprocessing tilesets with changed properties.
