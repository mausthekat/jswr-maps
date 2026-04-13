# Map Authoring Docs

Reference documentation for authoring Jet Set Willy: Redux maps in Tiled.
Start with [`TILED_MAP_CREATION.md`](TILED_MAP_CREATION.md) for the end-to-end
workflow; the other docs are topic-specific deep dives you'll need as you add
features to a map.

## Getting Started

| Document | Description |
|----------|-------------|
| [Tiled Map Creation](TILED_MAP_CREATION.md) | The main authoring guide — setup, creating maps, placing guardians, routes, spawns, game modes, and building. |

## Spawns, Flags & Game Modes

| Document | Description |
|----------|-------------|
| [TMX Spawn Points and Flags](TMX_SPAWN_POINTS_AND_FLAGS.md) | Spawn point and flag object layer — templates, per-spawn properties, and build-time validation rules. |
| [Map Flags](MAP_FLAGS.md) | The three flag systems every map declares — `ValidGameModes`, `SinglePlayerModes`, per-room `RoomFlags` — with bit layouts and storage locations. |
| [Game Mode Validation](GAME_MODE_VALIDATION.md) | How the pack-time converter derives `ValidGameModes` from spawn data and `RoomPurpose`, and what errors it raises. |

## Guardians, Routes & Triggers

| Document | Description |
|----------|-------------|
| [Route Details](ROUTE_DETAILS.md) | Guardian and lift route configuration — path geometry, movement modes, speed, and traversal behaviour. |
| [Map Triggers](MAP_TRIGGERS.md) | Data-driven events defined in TMX Special layers — conditions, actions, dependency chains, and per-player vs. unique triggers. |

## Tilesets & Standalone Packs

| Document | Description |
|----------|-------------|
| [Tileset Properties](TILESET_PROPERTIES.md) | Properties set on TSX files — `TilesetName`, `SupportsColorClash`, tile categorization, and graphics-style behaviour. |
| [Standalone Maps](STANDALONE_MAPS.md) | Building self-contained map packs that bundle custom tile graphics — tile manifest, per-room overrides, `DefaultTileset`, runtime loading. Reference implementation: `tmx/content/jsw-gorgeous`. |

## Cross-references

Binary format specs, runtime systems, network protocol, and operations docs
live in the outer repo under [`docs/formats/`](../../docs/formats/README.md).
Map authors typically only need:

- [JSWR Room File Format](../../docs/formats/JSWR_ROOM_FILE_FORMAT.md) — the binary format each TMX compiles to
- [JSWP Pack Format](../../docs/formats/JSWP_PACK_FORMAT.md) — the outer container wrapping rooms + tiles + custom data
- [JSWC/JSWX Tileset Collection Format](../../docs/formats/JSWC_TILESET_COLLECTION_FORMAT.md) — the tile graphics container used by standalone packs
- [Maps](../../docs/formats/MAPS.md) — shipping map catalog (game mode × map matrix)
