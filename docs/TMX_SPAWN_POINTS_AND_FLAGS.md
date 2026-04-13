# TMX Spawn Points and Flags

This document describes the spawn point and flag system used in TMX map files, how they are validated at build time, and how the game resolves them at runtime.

## Spawn System Overview

Spawn points are placed in Tiled as objects on the "Spawn" object layer, using templates from `tmx/project-template/templates/`. Each spawn has three properties:

| Property | Type | Description |
|----------|------|-------------|
| **Kind** | `SpawnKind` enum | `Player Start` (0) or `Flag` (1) |
| **Team** | `Team` enum | `No Team` (0), `Red` (1), `Blue` (2), `Green` (4), `Orange` (5) |
| **GameModes** | `GameModes` flags | Bitmask restricting which modes use this spawn (0 = all modes) |

### Spawn Templates

Located in `tmx/project-template/templates/`:

| Template | Kind | Team | Purpose |
|----------|------|------|---------|
| `spawn_player.tx` | Player Start | No Team | Neutral player spawn |
| `spawn_player_red.tx` | Player Start | Red | Red team spawn |
| `spawn_player_blue.tx` | Player Start | Blue | Blue team spawn |
| `spawn_player_green.tx` | Player Start | Green | Green team spawn (4-team modes) |
| `spawn_player_orange.tx` | Player Start | Orange | Orange team spawn (4-team modes) |
| `spawn_flag_neutral.tx` | Flag | No Team | Neutral/white flag (non-team CTF) |
| `spawn_flag_red.tx` | Flag | Red | Red team flag |
| `spawn_flag_blue.tx` | Flag | Blue | Blue team flag |
| `spawn_flag_green.tx` | Flag | Green | Green team flag (4-team modes) |
| `spawn_flag_orange.tx` | Flag | Orange | Orange team flag (4-team modes) |

## GameModes Bitmask Reference

The `GameModes` enum is stored as a flags bitmask in Tiled. Each bit corresponds to a game mode:

| Bit | Value | Name | Description |
|-----|-------|------|-------------|
| 0 | 0x001 (1) | COLLECT_X_ITEMS | Collect a target number of items |
| 1 | 0x002 (2) | TIMED_GAMES | Timed collection game |
| 2 | 0x004 (4) | RACE_TO_GAMES | Race to finish line |
| 3 | 0x008 (8) | DISCOVERY_GAMES | Discover percentage of rooms |
| 4 | 0x010 (16) | GOLDEN_WILLY | Golden Willy mode |
| 5 | 0x020 (32) | WILLY_TAG | Tag mode |
| 6 | 0x040 (64) | BRITISH_BULLDOG | Bulldog mode |
| 7 | 0x080 (128) | RESERVED | Reserved (WILLY_TEAMS in runtime, not exposed in Tiled) |
| 8 | 0x100 (256) | CAPTURE_THE_FLAG | Capture the Flag |
| 9 | 0x200 (512) | LOBBY | Gaming lounge infrastructure (not a gameplay mode) |
| 10 | 0x400 (1024) | FIRST_TO_COLLECT | First to collect 1 item races |
| 11 | 0x800 (2048) | COLLECT_ALL | Collect all items mode |
| 12 | 0x1000 (4096) | CHAIN_GAMES | Visit rooms in order |
| 13 | 0x2000 (8192) | IT_TAG | IT (Last Man Tag) mode |

**Note:** `WILLY_TEAMS` (0x80, bit 7) is NOT in the Tiled enum — bit 7 is reserved. Team mode support is inferred from the presence of team spawns (see [Team Mode Inference](#team-mode-inference)).

### GameModes on Spawn Points

When `GameModes` is set to **0** (default), the spawn is valid for all game modes. When non-zero, the spawn is only used when the current game mode matches at least one set bit.

This allows a single map to have different spawn positions for different modes. For example, the main map has:
- A neutral spawn with `GameModes = COLLECT_X_ITEMS | TIMED_GAMES | DISCOVERY_GAMES | ...` for standard modes
- A different neutral spawn with `GameModes = WILLY_TAG | BRITISH_BULLDOG` for tag/bulldog (different starting room)

## How Spawn Resolution Works

At runtime, spawn positions are resolved in `game.py` (`_extract_spawn_positions_from_rooms`) and `headless/server.py`:

1. Iterate all rooms and their spawn data
2. For each spawn, check `game_modes` filter:
   - If `game_mode == 0` (no filtering) OR `spawn.game_modes == 0` (spawn valid for all): include
   - If `spawn.game_modes & game_mode`: include (mode matches)
   - Otherwise: skip
3. First matching spawn of each type wins:
   - `player`: first neutral `PLAYER_START` (team=NONE)
   - `red`/`blue`/`green`/`orange`: first team `PLAYER_START` (only checked in team modes)
4. Flag spawns are collected separately by `flag.py`

### Resolution Priority

Spawns are resolved in room-ID order. The first matching spawn for each slot wins. This means lower-numbered rooms have priority.

## Design Rules

### When to Use GameModes on Spawns

- **Set GameModes = 0** (default) when the spawn position is suitable for all game modes the map supports
- **Set specific GameModes bits** when different modes need different starting positions (e.g., tag starts in a different room than collect)
- Most maps only need one neutral spawn with GameModes=0

### Team Spawn Requirements

- Team spawns always come in Red+Blue pairs (minimum). Green/Orange are optional for 4-team modes
- Green/Orange spawns require Red+Blue to also be present
- Team spawns do not need GameModes filtering — they are only used when the host selects a team mode

### CTF Requirements

Capture the Flag requires flag spawns:
- **Non-team CTF**: Neutral spawn + neutral (white) flag
- **Team CTF**: Red+Blue team spawns + Red+Blue team flags
- A map can support both by providing all spawn types

## Team Mode Inference

`WILLY_TEAMS` (0x80, bit 7) is a modifier flag, not a standalone game mode. It is NOT in the Tiled `GameModes` enum and is NOT stored in `ValidGameModes`.

Team mode support is **inferred at runtime** from the presence of team spawns:
- If Red+Blue team spawns exist → team variants of COLLECT, TIMED, CTF, and GOLDEN_WILLY are available
- The host UI shows team mode options only when team spawns are present
- Modes without team variants (TAG, BULLDOG, RACE_TO, DISCOVERY) always use neutral spawns

This means `ValidGameModes` stores only base mode bits (0-11). A map with `ValidGameModes = 0x103` (COLLECT + TIMED + CTF) that also has team spawns implicitly supports Team Collect, Team Timed, and Team CTF.

## ValidGameModes (Project-Level)

Each `.tiled-project` file has a `ValidGameModes` property (type: `GameModes` flags). This tells the build system which game modes the map is designed to support.

| Value | Meaning |
|-------|---------|
| 0 | Skip validation (legacy/unset) |
| 511 (0x1FF) | All 9 gameplay modes |
| 512 (0x200) | LOBBY only (gaming lounge infrastructure) |
| Other | Specific mode combination |

### Reference Values

| Map | ValidGameModes | Hex | Modes |
|-----|---------------|-----|-------|
| main | 511 | 0x1FF | All base modes + CTF |
| _gaminglounge | 512 | 0x200 | LOBBY |
| rj-bulldogging | 96 | 0x060 | Tag + Bulldog |
| rj-flag-cross | 384 | 0x180 | CTF |
| rj-fun-run | 352 | 0x160 | Tag + Bulldog + CTF |
| rj-jumper | 256 | 0x100 | CTF |
| rj-map1 | 256 | 0x100 | CTF |
| rj-the-ropery | 256 | 0x100 | CTF |
| rj-rapid-tag | 96 | 0x060 | Tag + Bulldog |
| rj-test | 99 | 0x063 | Collect + Timed + Tag + Bulldog |
| rj-what-goes-up | 384 | 0x180 | CTF |
| darktower | 1152 | 0x480 | First to Collect |

Built-in maps (assault, circle, construction, frantic, etc.) use their existing values (typically 0 or correct values set during initial migration).

## Validation Rules

The build tool (`build_scripts/tmx/tmx_to_jsw.py`, function `_compute_and_validate_game_modes()`) validates spawn/flag consistency when `ValidGameModes != 0`.

| # | Rule | Description |
|---|------|-------------|
| 1 | Team spawns must be paired | If any Red or Blue team spawn exists, both must be present |
| 1b | Extended team spawns need base | Green/Orange spawns require Red+Blue to also exist |
| 2a | Non-team-capable modes need neutral spawn | WILLY_TAG, BRITISH_BULLDOG, RACE_TO_GAMES, DISCOVERY_GAMES always require a neutral player spawn |
| 2b | Team-capable modes need neutral or team spawn | COLLECT_X_ITEMS, TIMED_GAMES, CAPTURE_THE_FLAG, GOLDEN_WILLY, COLLECT_ALL can use either neutral spawn or team spawns |
| 3 | Team flags must be paired | If any Red or Blue flag exists, both must be present |
| 4 | Team flags require team spawns | Red/Blue flags require Red+Blue team spawns |
| 5 | Neutral flag requires neutral spawn | A neutral flag requires a neutral player spawn |
| 5b | CTF requires flags | If CAPTURE_THE_FLAG is enabled, at least one flag type must exist |
| 5c | Team CTF requires team flags | If team spawns exist and CTF is enabled, Red+Blue flags must exist |
| 5d | CTF requires spawns | CTF needs either neutral spawn or team spawns |
| 6 | Non-GAMEPLAY rooms require LOBBY | Rooms with RoomPurpose != GAMEPLAY require the LOBBY bit |
| 7 | No duplicate room purposes | Each non-GAMEPLAY purpose (LOBBY, TEAM_SELECT, etc.) can only appear once |

### Current Status

All maps with `ValidGameModes` set pass validation cleanly.
