# Map Flag System

## Overview

Maps declare their capabilities through three independent flag systems. Each controls a different aspect of what the map supports:

| System | Scope | Storage | Controls |
|--------|-------|---------|----------|
| `GameMode` | Multiplayer gameplay | JSWP bytes 8-9 (uint16 LE) | Which MP game modes the map supports |
| `MapFlags` | Infrastructure | JSWP bytes 8-9 (uint16 LE) | Non-gameplay markers (lobby packs, MM entry points) |
| `SinglePlayerMode` | Single-player | JSWP byte 15 (uint8) | Which SP victory conditions the map supports |

`GameMode` and `MapFlags` share the same uint16 bitmask (`ValidGameModes` in the pack header). They use non-overlapping bit positions. `SinglePlayerMode` is stored in a separate byte and is completely independent — a map can support any combination of MP and SP modes.

**Source files:**

| Concept | Code | Docs |
|---------|------|------|
| Enum definitions | `src/game_settings.py` | This document |
| Pack header storage | `src/formats/jswp_pack.py` | [JSWP_PACK_FORMAT.md](../../docs/formats/JSWP_PACK_FORMAT.md) |
| Runtime registry | `src/map_registry.py` (`MapInfo`) | — |
| TMX properties | `tmx/project-template/archetype.tiled-project` | [JSWR_ROOM_FILE_FORMAT.md](../../docs/formats/JSWR_ROOM_FILE_FORMAT.md) |
| Lobby menu filtering | `src/lobby/service.py` | — |
| SP menu filtering | `src/ui/menu_screens.py` | — |

---

## GameMode (Multiplayer Gameplay Modes)

```python
class GameMode(IntFlag):
    COLLECT_X_ITEMS     = 0x0001
    TIMED_GAMES         = 0x0002
    RACE_TO_GAMES       = 0x0004
    DISCOVERY_GAMES     = 0x0008
    GOLDEN_WILLY        = 0x0010
    WILLY_TAG           = 0x0020
    BRITISH_BULLDOG     = 0x0040
    WILLY_TEAMS         = 0x0080   # Modifier: ORed with other modes
    CAPTURE_THE_FLAG    = 0x0100
    FIRST_TO_COLLECT    = 0x0400
    COLLECT_ALL         = 0x0800
    CHAIN_GAMES         = 0x1000
    IT_TAG              = 0x2000
    WILLY_BALL          = 0x8000
```

### Bitmask Table

| Bit | Value  | Name | Menu Category | Description |
|-----|--------|------|---------------|-------------|
| 0 | 0x0001 | `COLLECT_X_ITEMS` | Collection | First to collect N items wins |
| 1 | 0x0002 | `TIMED_GAMES` | Collection | Most items when timer expires |
| 2 | 0x0004 | `RACE_TO_GAMES` | Exploration | First to reach target room |
| 3 | 0x0008 | `DISCOVERY_GAMES` | Exploration | Visit X% of rooms first |
| 4 | 0x0010 | `GOLDEN_WILLY` | Collection | Find the single golden item |
| 5 | 0x0020 | `WILLY_TAG` | Tag | Last player standing |
| 6 | 0x0040 | `BRITISH_BULLDOG` | Tag | IT player catches runners |
| 7 | 0x0080 | `WILLY_TEAMS` | Teams | Team mode modifier (ORed with base mode) |
| 8 | 0x0100 | `CAPTURE_THE_FLAG` | Teams | Capture the flag |
| 10 | 0x0400 | `FIRST_TO_COLLECT` | Collection | First to collect 1 item (quick race maps) |
| 11 | 0x0800 | `COLLECT_ALL` | Collection | Collect every item on the map |
| 12 | 0x1000 | `CHAIN_GAMES` | Exploration | Visit rooms in sequence |
| 13 | 0x2000 | `IT_TAG` | Tag | Hot-potato tag (least IT time wins) |
| 15 | 0x8000 | `WILLY_BALL` | Teams | Team ball-carrying game — carry to opposing goal |

Bits 9 and 14 are used by `MapFlags` (see below). Bit 9 is `LOBBY` (0x0200), bit 14 is `MM_START` (0x4000).

### Menu Categories

The lobby host menu uses a two-level branch structure:

```
Individual Games → Game Type → Map → [Settings] → Start
Team Games       → Game Type → Map → [Settings] → Start
```

Modes with `branch: "both"` appear in **both** branches (e.g., Collect X Items appears under Individual and Team). Modes with `branch: "individual"` or `branch: "team"` appear only in their respective branch. A mode entry only appears if at least one registered map supports it.

The mode registry (`MODE_REGISTRY` in `game_mode_utils.py`) is the single source of truth for menu generation — display name, branch, settings type, and extra flags are all defined there.

### Special Modes

**WILLY_TEAMS (0x0080)** is a modifier, not a standalone mode. At runtime it is ORed with a base gameplay mode (e.g., `WILLY_TEAMS | COLLECT_X_ITEMS` for Team Collect). It is stored in per-spawn `GameModes` bitmasks in TMX but is NOT stored in per-spawn data in the binary JSWR format — team spawns are identified by their team assignment (RED, BLUE, etc.) instead. The Team Games branch automatically sets `WILLY_TEAMS` on entry.

**GOLDEN_WILLY (0x0010)** appears under Individual Games. On selection, `COLLECT_X_ITEMS` is ORed in as an extra flag for scoring.

**FIRST_TO_COLLECT (0x0400)** marks small maps designed for quick "first to collect 1 item" races. Appears in both Individual and Team branches.

**WILLY_BALL (0x8000)** is a team ball-carrying game. Two teams compete to carry a ball to the opposing team's goal. The ball spawns at a `BALL_SPAWN` point (SpawnKind 3) defined in the map. The ball can be thrown, dropped on death, and intercepted by tackles. A possession timer forces the carrier to drop the ball if they hold it too long. WILLY_BALL implies team play — maps must also set `WILLY_TEAMS` (0x0080) and include CTF-style team spawns and flags alongside the `BALL_SPAWN`. See [CAPTURE_THE_FLAG](#special-modes) for team spawn requirements.

### Additional Data Requirements

Some modes require V5 custom data in the JSWP pack beyond just setting the flag bit:

| Mode | Requirement |
|------|-------------|
| `RACE_TO_GAMES` | `race_targets` custom data (target room list with labels) |
| `CHAIN_GAMES` | `chain_groups` custom data (auto-generated from BFS distances at build time, minimum 2 groups) |

See [JSWP_PACK_FORMAT.md](../../docs/formats/JSWP_PACK_FORMAT.md) for custom data key formats.

---

## MapFlags (Infrastructure Flags)

```python
class MapFlags(IntFlag):
    LOBBY    = 0x0200    # Gaming lounge infrastructure pack
    MM_START = 0x4000    # Has Manic Miner entry/exit points
```

### Bitmask Table

| Bit | Value  | Name | Description |
|-----|--------|------|-------------|
| 9 | 0x0200 | `LOBBY` | Pack is a gaming lounge (lobby, briefing, team select rooms) |
| 14 | 0x4000 | `MM_START` | Pack contains Manic Miner entry/exit spawn points |

These flags share the uint16 `ValidGameModes` bitmask with `GameMode` but are **not** gameplay modes. Code that queries available gameplay modes should mask these out. Code that queries infrastructure properties should test against `MapFlags`.

### LOBBY

Marks the gaming lounge infrastructure pack (`_gaminglounge`). This pack contains non-gameplay rooms with special `RoomPurpose` values (Lobby, Team Select, Launchpad, Victory Room, Briefing). Non-GAMEPLAY room purposes require the LOBBY flag in `ValidGameModes`.

The LOBBY flag is also available as the constant `VALID_GAME_MODES_LOBBY = 0x200` in `src/formats/jswr_format.py` for binary format readers.

### MM_START

Marks per-spawn Manic Miner entry points — teleport destinations where the player appears when entering a new room through an MM exit door. When a player exits through an MM door in one room, the game looks for a `PLAYER_START` spawn with `MM_START` in the destination room's `game_modes` bitmask to determine the entry position.

This flag appears in per-spawn `GameModes` bitmasks (not just at the pack level). It is checked at runtime via:

```python
spawn.game_modes & MapFlags.MM_START
```

---

## SinglePlayerMode (SP Victory Conditions)

```python
class SinglePlayerMode(IntFlag):
    SP_CLASSIC      = 0x01   # Collect all items (+ optional destination room)
    SP_MANIC_MINER  = 0x02   # Clear rooms sequentially, exit final door
```

### Bitmask Table

| Bit | Value | Name | Description |
|-----|-------|------|-------------|
| 0 | 0x01 | `SP_CLASSIC` | Collect all items; optionally reach a destination room |
| 1 | 0x02 | `SP_MANIC_MINER` | Room-by-room clearance, exit through final door |
| 2-7 | — | Reserved | Reserved for future SP modes (zero) |

### Storage

Stored in JSWP header byte 15 (uint8). This byte was previously reserved (always zero), so existing packs are backward compatible — `SinglePlayerModes = 0` means no SP support, which is the correct default.

### SP_CLASSIC

The standard JSW single-player experience: collect every item in the map.

- If `sp_victory_room` is set (V5 custom data, uint16 LE room ID): player must collect all items **and** reach that room. Example: collect all 82 items in JSW Gorgeous, then reach The Master Bedroom.
- If `sp_victory_room = 0` (default): victory triggers immediately when the last item is collected.

Victory detection runs locally in the game loop via `SPClassicStrategy` — no server involved.

### SP_MANIC_MINER

Linear room-by-room progression. All items in the current room must be collected before the MM exit door opens. Victory when the player exits through the door in the final room (identified by the existing `ManicFinalRoom` / `mm_final_exit_room` property).

Uses existing Manic Miner infrastructure. Victory detection is handled by the existing MM exit handler in `GameInstance`.

### SP Victory Room

The `sp_victory_room` value is stored as V5 custom data (key: `"sp_victory_room"`, value: uint16 LE room ID) in the JSWP pack. It is read into `MapInfo.sp_victory_room` at startup and passed to `SPClassicStrategy` when starting an SP game.

See [JSWP_PACK_FORMAT.md](../../docs/formats/JSWP_PACK_FORMAT.md) for the custom data format.

---

## TMX Configuration

### GameModes Enum (TMX propertyType id=13)

The TMX `GameModes` enum is a flags-type integer enum used for both `ValidGameModes` (project property) and per-spawn `GameModes` (SpawnPoint class member). It defines the bit positions for the combined `GameMode | MapFlags` uint16 bitmask:

| Position | Name | Bit Value |
|----------|------|-----------|
| 0 | COLLECT_X_ITEMS | 0x0001 |
| 1 | TIMED_GAMES | 0x0002 |
| 2 | RACE_TO_GAMES | 0x0004 |
| 3 | DISCOVERY_GAMES | 0x0008 |
| 4 | GOLDEN_WILLY | 0x0010 |
| 5 | WILLY_TAG | 0x0020 |
| 6 | BRITISH_BULLDOG | 0x0040 |
| 7 | WILLY_TEAMS | 0x0080 |
| 8 | CAPTURE_THE_FLAG | 0x0100 |
| 9 | LOBBY | 0x0200 |
| 10 | FIRST_TO_COLLECT | 0x0400 |
| 11 | COLLECT_ALL | 0x0800 |
| 12 | CHAIN_GAMES | 0x1000 |
| 13 | IT_TAG | 0x2000 |
| 14 | MM_START | 0x4000 |
| 15 | WILLY_BALL | 0x8000 |

This enum is shared between `GameMode` and `MapFlags` in TMX — Tiled sees them as one flags enum. The Python code separates them into distinct `IntFlag` classes for type clarity, but the stored integer values are identical.

### SPModes Enum (TMX propertyType id=16)

The TMX `SPModes` enum is a flags-type integer enum for the `SinglePlayerModes` project property:

| Position | Name | Bit Value |
|----------|------|-----------|
| 0 | SP_CLASSIC | 0x01 |
| 1 | SP_MANIC_MINER | 0x02 |

### Project Properties

| Property | Type | Description |
|----------|------|-------------|
| `ValidGameModes` | GameModes (int) | MP mode + infrastructure bitmask |
| `SinglePlayerModes` | SPModes (int) | SP victory condition bitmask |
| `SPVictoryRoom` | int | Room ID for SP_CLASSIC destination (0 = none) |
| `ManicFinalRoom` | int | Room ID for MM final exit (used by SP_MANIC_MINER) |
| `DefaultTileset` | string | Tileset name to activate on load (empty = first loaded) |

After modifying the archetype (`tmx/project-template/archetype.tiled-project`), run `python tmx/scripts/tmx_project.py refresh` to propagate new enum types and properties to all content projects.

---

## Runtime Data Flow

### Pack Build (TMX → JSWP)

```
archetype.tiled-project           tmx_to_jsw.py              JSWP pack header
┌───────────────────────┐    ┌──────────────────────┐    ┌──────────────────┐
│ ValidGameModes: 0x11FF│───▶│ _read_project_valid_ │───▶│ Bytes 8-9: 0x11FF│
│ SinglePlayerModes: 1  │───▶│ _read_project_single_│───▶│ Byte 15: 0x01    │
│ SPVictoryRoom: 48     │───▶│ _read_project_sp_vic_│───▶│ V5 custom data   │
│ DefaultTileset: "X"   │───▶│ _read_project_defaul_│───▶│ V5 custom data   │
└───────────────────────┘    └──────────────────────┘    └──────────────────┘
```

### Game Startup (JSWP → Runtime)

```
JSWP pack header          JSWPackReader             MapRegistry (MapInfo)
┌──────────────────┐    ┌───────────────────┐    ┌──────────────────────────┐
│ Bytes 8-9: 0x11FF│───▶│ .valid_game_modes │───▶│ valid_game_modes = 0x11FF│
│ Byte 15: 0x01    │───▶│ .single_player_   │───▶│ single_player_modes = 1  │
│ V5: sp_victory_  │───▶│  modes            │───▶│ sp_victory_room = 48     │
│     room = 48    │    │ .get_custom_data()│    │ default_tileset = "X"    │
│ V5: default_     │───▶│                   │───▶│                          │
│     tileset = "X"│    │                   │    │                          │
└──────────────────┘    └───────────────────┘    └──────────────────────────┘
```

### Menu Queries

| Query | Method | Returns |
|-------|--------|---------|
| Maps for MP mode X | `registry.get_maps_for_mode(GameMode.X)` | Maps where `valid_game_modes & X` |
| Maps for SP mode X | `registry.get_maps_for_sp_mode(SinglePlayerMode.X)` | Maps where `single_player_modes & X` |
| Is map a lobby pack? | `info.valid_game_modes & MapFlags.LOBBY` | Truthy if lobby infrastructure |

---

## Map Configuration Examples

### Mansion Redux (`main`)

Full-featured main map with nearly all MP modes and SP Classic:

```
ValidGameModes:    0x11FF  (Collect, Timed, Race, Chain, Discovery, Golden, Tag, Bulldog, Teams, CTF)
SinglePlayerModes: 0x01    (SP_CLASSIC)
SPVictoryRoom:     48      (The Bathroom — must reach after collecting all items)
```

### Manic Willy (`manic`)

Manic Miner-style map with linear room progression:

```
ValidGameModes:    0x0010  (GOLDEN_WILLY — for multiplayer Golden Willy mode)
SinglePlayerModes: 0x02    (SP_MANIC_MINER)
ManicFinalRoom:    20      (final room's exit triggers victory)
SPVictoryRoom:     0       (not used — MM uses ManicFinalRoom)
```

### Assault Course (`assault`)

Small SP-capable map with multiplayer Golden Willy and quick race modes:

```
ValidGameModes:    0x0410  (GOLDEN_WILLY + FIRST_TO_COLLECT)
SinglePlayerModes: 0x01    (SP_CLASSIC)
SPVictoryRoom:     0       (no destination — victory on last item collected)
```

### Construction Site (`construction`)

Multiplayer-only arena map — no SP support:

```
ValidGameModes:    0x2060  (WILLY_TAG + BRITISH_BULLDOG + IT_TAG)
SinglePlayerModes: 0x00    (no SP — does not appear in Single Player menu)
```

### Gaming Lounge (`_gaminglounge`)

Infrastructure pack — not a playable map:

```
ValidGameModes:    0x0200  (LOBBY only)
SinglePlayerModes: 0x00    (no SP)
```