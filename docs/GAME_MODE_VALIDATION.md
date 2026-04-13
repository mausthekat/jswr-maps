# Game Mode Validation

ValidGameModes is **computed from spawn data** at build time. There is no project-level
declaration — the converter derives supported modes entirely from spawn point `GameModes`
properties and room `RoomPurpose` values.

## How ValidGameModes Is Computed

The build process (`tmx_to_jsw.py --pack`) computes the bitmask as follows:

1. **Union of spawn game_modes**: OR together the `GameModes` bitmask from every spawn
   point (PLAYER_START, FLAG, EXIT, BALL_SPAWN) across all rooms. Only gameplay mode bits
   are kept (COLLECT_X_ITEMS through WILLY_BALL).

2. **LOBBY flag (0x0200)**: Added if any room has a non-GAMEPLAY `RoomPurpose`
   (Lobby, Team Select, Launchpad, Victory Room, Briefing, Team Select 4).

3. **MM_START flag (0x4000)**: Added if any spawn's `GameModes` includes MM_START
   (bit 14). This indicates Manic Miner entry/exit points are present.

The result is written to the JSWP pack header. Runtime code reads it from there — no
project file is consulted.

## Validation Rules

All structural checks run during `--pack` builds and in the Tiled extension's
"Game Mode Report" action. Most produce **warnings** (build continues); a few are
**errors** (build fails).

### Errors

| Rule | Description |
|------|-------------|
| **game_modes=0** | Non-EXIT spawns must have explicit GameModes. A value of 0 means "unset", not "all modes". EXIT spawns are exempt. |
| **Neutral + WILLY_TEAMS** | A neutral (team=NONE) PLAYER_START must not have WILLY_TEAMS in its game_modes. Neutral spawns are never used in team modes. |
| **Duplicate RoomPurpose** | Only one room may have each non-GAMEPLAY purpose (e.g. one Lobby, one Briefing). |

### Warnings

| Rule | Description |
|------|-------------|
| **Team symmetry (Red/Blue)** | If Red team spawns exist, Blue must too (and vice versa). |
| **Team symmetry (Green/Orange)** | Green/Orange spawns require Red+Blue to also be present. |
| **Neutral spawn required** | Modes without team variants (RACE_TO_GAMES, DISCOVERY_GAMES, etc.) require at least one neutral PLAYER_START. |
| **Neutral or team spawn required** | Modes with team variants (COLLECT_X_ITEMS, TIMED_GAMES, CTF, etc.) require either neutral or team spawns. |
| **Flag symmetry** | Team flags require both Red and Blue flags present. |
| **Flag without team spawn** | Team flags require matching team PLAYER_START spawns. |
| **Neutral flag without neutral spawn** | A neutral flag requires a neutral PLAYER_START. |
| **CTF: team pairing** | Team CTF (CTF+WILLY_TEAMS) needs >=2 teams with both a CTF-tagged flag AND CTF-tagged PLAYER_START. |
| **CTF: solo** | Solo CTF (CTF without WILLY_TEAMS) needs a CTF-tagged neutral flag AND neutral PLAYER_START. |
| **CTF: flag not tagged** | Every FLAG spawn should have CAPTURE_THE_FLAG in its game_modes. |
| **CTF: flag/spawn mismatch** | A CTF-tagged team flag without a matching CTF-tagged team spawn (or vice versa). |
| **WILLY_BALL: requires WILLY_TEAMS** | WILLY_BALL is always team-based. |
| **WILLY_BALL: requires BALL_SPAWN** | At least one BALL_SPAWN spawn point must exist. |
| **WILLY_BALL: team pairing** | Needs >=2 teams with both a WILLY_BALL-tagged team flag AND WILLY_BALL-tagged team PLAYER_START. |

## Tiled Extension: Game Mode Report

The "Game Mode Report" action in Tiled's Map menu scans all rooms and produces a
report showing:

- Computed ValidGameModes value and constituent modes
- Per-mode breakdown of contributing spawn points
- All structural validation warnings

The report can be saved to `game_mode_report.txt` in the map folder.

## Spawn Point GameModes Property

Each spawn point carries a `GameModes` bitmask indicating which modes it participates in.
This is the **source of truth** for what a map supports.

| Bit | Value | Mode |
|-----|-------|------|
| 0 | 0x0001 | COLLECT_X_ITEMS |
| 1 | 0x0002 | TIMED_GAMES |
| 2 | 0x0004 | RACE_TO_GAMES |
| 3 | 0x0008 | DISCOVERY_GAMES |
| 4 | 0x0010 | GOLDEN_WILLY |
| 5 | 0x0020 | WILLY_TAG |
| 6 | 0x0040 | BRITISH_BULLDOG |
| 7 | 0x0080 | WILLY_TEAMS |
| 8 | 0x0100 | CAPTURE_THE_FLAG |
| 9 | 0x0200 | LOBBY (infrastructure, not set on spawns) |
| 10 | 0x0400 | FIRST_TO_COLLECT |
| 11 | 0x0800 | COLLECT_ALL |
| 12 | 0x1000 | CHAIN_GAMES |
| 13 | 0x2000 | IT_TAG |
| 14 | 0x4000 | MM_START (infrastructure flag) |
| 15 | 0x8000 | WILLY_BALL |
