# Tiled Map Creation Guide for JSW:R

A start-to-finish guide for creating custom maps for Jet Set Willy: Redux using the
[Tiled Map Editor](https://www.mapeditor.org/).

For the extension reference and conversion script details, see [tmx/README.md](../README.md).

> **Getting started:** Open the `training` map project in Tiled (`tmx/content/training/`)
> as a reference while reading this guide. It's a small 13-room map that demonstrates the
> core features: tiles, guardians, routes, collectibles, spawns, and ropes.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Creating a New Map Project](#2-creating-a-new-map-project)
3. [Project Configuration](#3-project-configuration)
4. [Creating Rooms](#4-creating-rooms)
5. [Room Properties](#5-room-properties)
6. [Tile Layer](#6-tile-layer)
7. [Collectibles](#7-collectibles)
8. [Guardians](#8-guardians)
9. [Arrows](#9-arrows)
10. [Routes](#10-routes)
11. [Spawn Points](#11-spawn-points)
12. [Special Objects](#12-special-objects)
13. [Ropes](#13-ropes)
14. [World File & Navigation](#14-world-file--navigation)
15. [Game Mode Configuration](#15-game-mode-configuration)
16. [Infrastructure Rooms](#16-infrastructure-rooms)
17. [Building & Testing](#17-building--testing)
18. [Extension Tools](#18-extension-tools)
19. [Validation Rules](#19-validation-rules)
20. [Tips & Common Pitfalls](#20-tips--common-pitfalls)

---

## 1. Prerequisites

- **Tiled Map Editor** 1.10+ (1.11+ recommended) — [mapeditor.org](https://www.mapeditor.org/)
- **uv** ([astral.sh/uv](https://docs.astral.sh/uv/getting-started/installation/)) — for running build/conversion scripts (manages Python automatically)
- The map editing repository from GitHub

### Getting the Map Repository

**Option A: Using git (recommended if you plan to contribute)**

```bash
git clone https://github.com/mausthekat/jswr-maps.git
cd jswr-maps
```

**Option B: Download as ZIP (no git required)**

1. Go to [github.com/mausthekat/jswr-maps](https://github.com/mausthekat/jswr-maps)
2. Click the green **Code** button → **Download ZIP**
3. Extract the ZIP to a folder of your choice
4. Open a terminal and `cd` into the extracted folder

### Installing uv

The conversion scripts require **uv**, a fast Python package manager that automatically
manages Python versions and dependencies.

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Verify with: `uv --version`

That's it — `uv` downloads the correct Python version and handles all dependencies
automatically when you run scripts with `uv run`. No manual Python or pip install required.

---

## 2. Creating a New Map Project

> **Important:** All scripts should be run from the root of the tmx repository. Open a
> terminal and `cd` into the folder before running any commands.

Use the `tmx_project.py create` command to scaffold a new map project:

```bash
# macOS / Linux
uv run scripts/tmx_project.py create <map-name>

# Windows
uv run scripts\tmx_project.py create <map-name>
```

This creates a directory under `_in_progress/<map-name>/` containing:

```
<map-name>/
├── <map-name>.tiled-project     # Project file with all property type definitions
├── <map-name>.world             # World file for room layout
├── templates/                   # Spawn and route object templates
│   ├── spawn_player.tx
│   ├── spawn_player_red.tx
│   ├── spawn_player_blue.tx
│   ├── spawn_player_green.tx
│   ├── spawn_player_orange.tx
│   ├── spawn_flag_neutral.tx
│   ├── spawn_flag_red.tx
│   ├── spawn_flag_blue.tx
│   ├── spawn_flag_green.tx
│   ├── spawn_flag_orange.tx
│   ├── spawn_ball.tx
│   └── route.tx
└── .extensions/
    └── jswr.js                  # JSW:R Tiled extension
```

Options:
- `--location content` — create directly in `content/` (for finished maps)
- `--location in_progress` (default) — create in `_in_progress/`
- `--dry-run` — preview what would be created

When ready to publish, move the directory from `_in_progress/` to `content/`.

> **Note:** The `dat_to_tmx.py --new` flag is deprecated and should not be used. Always use
> `tmx_project.py create` for new maps.

### Importing Legacy .dat Maps

If you have maps from the original JSW:O editor in `.dat` format, use `dat_to_tmx.py` to
convert them to TMX:

```bash
# macOS / Linux
uv run scripts/dat_to_tmx.py <dat-folder> <output-folder> --map

# Windows
uv run scripts\dat_to_tmx.py <dat-folder> <output-folder> --map
```

For example, to convert a map called `my-map` and output to `_in_progress/`:

```bash
# macOS / Linux
uv run scripts/dat_to_tmx.py /path/to/my-map _in_progress/my-map --map

# Windows
uv run scripts\dat_to_tmx.py C:\path\to\my-map _in_progress\my-map --map
```

The input folder should contain the legacy `.dat` files:
- `*.dat` — room tile data (e.g., `1.dat`, `2.dat`)
- `*_enemy.dat` or `*_ENEMY.dat` — guardian/enemy data
- `*_pickups.dat` — collectible positions
- `<mapname>_setup.dat` — spawn positions (optional)

The converter creates a complete Tiled project in the output folder, including:
- Individual `.tmx` room files with all layers (Tiles, Collectables, Enemies, Routes, Spawn)
- A `.world` file with room positions derived from exit connections
- A `.tiled-project` file with all property type definitions
- Templates and the Tiled extension

> **Tip:** After conversion, open the `.tiled-project` file in Tiled and set the `MapName`
> and `ValidGameModes` in Project > Project Properties — these are needed for the map to
> build correctly.

---

## 3. Project Configuration

Open the `.tiled-project` file in Tiled (File > Open Project). The project-level properties
are configured in **Project > Project Properties**:

| Property | Type | Description |
|----------|------|-------------|
| `MapName` | string | Display name of the map (shown in-game). **Required.** |
| `Author` | string | Author credit. Recommended. |
| `ValidGameModes` | GameModes (flags) | Which game modes this map supports. See [Game Mode Configuration](#15-game-mode-configuration). |
| `FallDamageMode` | FallDamageMode | `Lenient` (0, default) or `Strict` (1). |
| `SoftLifts` | bool | Enable soft lift mechanics. Default: false. |
| `OriginalArrows` | bool | Use original ZX Spectrum arrow behavior (per-arrow counter, 256-tick cycle). SP only — ignored in multiplayer. Default: false. |
| `ManicFinalRoom` | int | Room ID for the final room in Manic-style maps. Default: 0 (unused). |
| `IncludeMapPreview` | bool | Generate a preview image in the pack file. Default: true. |
| `InfiniteLivesSP` | bool | Dying does not cost a life in single-player. Default: false. |
| `InfiniteLivesMP` | bool | Dying does not cost a life in multiplayer. Default: false. |
| `SinglePlayerModes` | SPModes (flags) | Single-player modes this map supports: `SP_CLASSIC`, `SP_MANIC_MINER`. Default: none. |
| `SPVictoryRoom` | int | Room ID for the single-player victory room. Default: 0 (unused). |
| `DefaultTileset` | string | Tileset variant to activate on load for standalone map packs. Default: empty (use first loaded). |

---

## 4. Creating Rooms

### Using the Extension Dialog

The Tiled extension adds a **New JSW:R Room** command:
- **Menu:** Map > New JSW:R Room...
- **Shortcut:** Ctrl+Shift+N (also available from New menu when no map is open)

The dialog prompts for:
1. **Room ID** — dropdown of available IDs (001–255, auto-detects occupied slots)
2. **Room Name** — display name (max 32 characters)
3. **Exits** — Up/Down/Left/Right dropdowns showing existing rooms by ID and name
4. **Has Rope** — checkbox

The extension creates the `.tmx` file with:
- Correct map dimensions (32×16 tiles, 8×8 pixel tiles)
- All 8 standard tilesets pre-configured
- All required layers (Tiles, Collectables, Enemies, Routes, Spawn)
- Room properties initialized from dialog values
- Automatic placement in the `.world` file based on exit connections

### Room Numbering

Rooms are numbered `001.tmx` through `255.tmx`. Room 000 is reserved.

### Room File Structure

Each `.tmx` room is an orthogonal Tiled map: **32 tiles wide × 16 tiles tall** at **8×8 pixels
per tile** (256×128 pixel room).

Required layers (in order):
1. **Tiles** — tile layer for room geometry
2. **Collectables** — object group for collectible items
3. **Enemies** — object group for guardian sprites
4. **Routes** — object group for guardian patrol paths (magenta/cyan color recommended)
5. **Spawn** — object group for player spawn points

Optional layers:
6. **Special** — object group for team doors, barriers, and additional spawns

---

## 5. Room Properties

Set via Map > Map Properties in Tiled. Per-room properties come in two groups:

### Standard properties

Always present on every room. The `[ROOM] Check/Fix Room Properties` extension
command (Section 18) initializes any that are missing.

| Property | Type | Description |
|----------|------|-------------|
| `Name` | string | Room display name. |
| `Up` | file | Exit room filename (e.g., `041.tmx`). Empty = no exit. |
| `Down` | file | Exit room filename. |
| `Left` | file | Exit room filename. |
| `Right` | file | Exit room filename. |
| `Rope` | bool | Whether the room contains a rope. Default: false. |
| `Rope Offset` | int | Signed tile offset to adjust rope horizontal position (0 = center of room). Default: 0. |
| `Flags` | RoomFlags | Room flags: `MIRROR_TRIGGER`, `DARK_ROOM`, `UNDERWATER`, `LOW_GRAVITY`. |
| `WillySuit` | WillySuit | `Normal` (0), `SpaceSuit` (1), `DivingSuit` (2), or `FlyingPig` (3). Default: Normal. |
| `RoomPurpose` | RoomPurpose | Infrastructure-room role. Default: `Gameplay` (0). Non-Gameplay values (`Lobby`, `Team Select`, `Launchpad`, `Victory Room`, `Briefing`, `Team Select 4`) force the containing map pack into lobby-only mode. See [Infrastructure Rooms](#16-infrastructure-rooms). |

### Opt-in properties

Added to a room **only when that room actually uses the feature**. They are
deliberately not in the archetype or the Fix Room Properties initializer to
keep the common case lean — adding them to every room would mean ~600 lines
of noise for features used in a handful of rooms. Add them manually via
Map > Map Properties > Add Property.

| Property | Type | Where used | Description                                                                                                                                                                                                                                         |
|----------|------|------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `Border` | int | `jsw-gorgeous` | ZX `$FE` border palette index (0–7): 0=black, 1=blue, 2=red, 3=magenta, 4=green, 5=cyan, 6=yellow, 7=white. Applied on room entry when the player has Options > Border Color enabled. Stored in JSWR header byte 16. Absent or 0 = black (default). |
| `RaceLabel` | string | `main` | Target label for `RACE_TO_GAMES`. Displayed in the menu as flavour text. E.g. "The Lager Run" for a race to the Off License.                                                                                                                        |

> `CHAIN_GAMES` chain groups are **no longer authored via a per-room property**. They are auto-generated at pack build time from BFS distance data using farthest-first clustering (`tmx_to_jsw.py:_generate_chain_groups_from_bfs`) and stored in the pack's `chain_groups` custom data block. See [MAP_FLAGS.md](MAP_FLAGS.md) and [JSWP_PACK_FORMAT.md](../../docs/formats/JSWP_PACK_FORMAT.md).

**Background color** is set via Map > Map Properties > Background Color. This is converted to
the game's 9-bit color format (3 bits per channel).

---

## 6. Tile Layer

The **Tiles** layer is a 32×16 tile grid. Select the layer, then use the **Stamp Brush** (B)
or **Bucket Fill** (F) tools to paint tiles. Tile ID 0 = empty/air.

The tilesets appear in the **Tilesets** panel (View > Views and Toolbars > Tilesets). Click a
tileset tab to browse its tiles, then select one or more tiles to paint with.

### Standard Tilesets

All rooms include these tilesets by default. The tileset you pick a tile from determines its
behavior:

| Tileset | Behavior |
|---------|----------|
| **Solid** | Blocks movement in all directions. Walls, floors, ceilings. |
| **Stairs** | Allows walking at an angle. Direction determined by tile properties or column position. |
| **Platform** | One-way platforms. Solid from above, passable from below and sides. |
| **Hazard** | Kills the player on contact. |
| **Decoration** | Visual only — no collision. |
| **Conveyor** | Moves the player horizontally. Animated (8-frame, 100ms). |

### Specialty Tilesets

| Tileset | Description |
|---------|-------------|
| **Collapsible** | Crumble/collapse tiles that break when stepped on, then reset. Animated (8-frame, 125ms). Included in new rooms by default. See `manic/` for examples. |
| **Penrose** | Special visual tiles. Must be added manually via Map > Add External Tileset (browse to `tmx/tilesets/tiles_penrose.tsx`). |
| **MM Exit** | Manic Miner exit door tiles. Must be added manually via Map > Add External Tileset (browse to `tmx/tilesets/tiles_mm_exit.tsx`). See [MM Exit Spawns](#mm-exit-spawns). |

### Stair Direction

Stair tiles encode direction (left-going `\` or right-going `/`):

- **Property-based** (preferred): Select stair tiles in the tileset editor and set their
  `Direction` property — `Left` for `\` stairs, `Right` for `/` stairs. Tiles without a
  Direction property are treated as decoration.
- **Position-based** (fallback): If no stair tiles have Direction properties, direction is
  determined by column index — odd columns = left-going, even columns = right-going.

---

## 7. Collectibles

Collectible items are placed on the **Collectables** object layer.

### Placing Collectibles

1. Select the **Collectables** layer in the Layers panel
2. Select the **Insert Tile** tool (T)
3. In the Tilesets panel, switch to the **Collectibles** tileset and click a tile to select it
4. Click in the map to place the collectible

The collectibles tileset contains 148 tiles, many with 4-frame animations. No additional
properties are needed — the collectible type is determined by which tile you pick.

> **Example:** Open `training/012.tmx` to see a room with a placed collectible.

> **Note:** Tiled anchors tile objects at their **bottom-left** corner. The converter
> automatically adjusts for this.

---

## 8. Guardians

Guardian enemies are placed on the **Enemies** object layer.

### Placing a Guardian

1. Select the **Enemies** layer in the Layers panel
2. Select the **Insert Tile** tool (T)
3. In the Tilesets panel, switch to the **Guardians** tileset and click a sprite
4. Click in the map to place the guardian at its starting position
5. With the guardian selected, set its properties in the Properties panel (see below)

### Setting Guardian Properties

After placing a guardian, select it with the **Select Objects** tool (S) and configure in the
Properties panel:

1. Set **Type** to `Guardian` (the extension's fix tools can do this automatically)
2. Give it a descriptive **Name** (e.g., "Beetle 1") — the fix tools auto-generate these
3. Set **Color** — click the color swatch to pick the guardian's display color
4. Optionally set **Flags** — `HARMLESS` (cannot kill), `ALWAYS_DEADLY` (kills through invincibility)

### Guardian Sprite Types

The Guardians tileset contains several categories of sprites:

| Sprites | Type | Notes |
|---------|------|-------|
| 0–69 | Regular guardians | 16×16. Each needs a Route. |
| 70 | Lift | 16×16. Needs a Route (vertical). Automatically flagged as HARMLESS. |
| 71–72 | Arrow I / Arrow II | 16×16. See [Arrows](#9-arrows). |
| 73 | Periscope Tank | 16×32 (oversized). Needs a Route. |
| 74 | Evil Giant Head | 32×32 (oversized). Needs a Route. |

Each guardian needs a **Route** object to define its patrol path — see [Routes](#10-routes).
Arrows are the exception (see [Arrows](#9-arrows)).

> **Example:** Open `training/001.tmx` to see a simple room with two guardians and their
> routes. For a more complex example, browse rooms in `main/`.

---

## 9. Arrows

Arrows are horizontal projectiles that fire from screen edges on a global timer.

### Arrow Types

There are two arrow sprites in the Guardians tileset, each on an independent timer:

- **Arrow I** (sprite 71) — fires on timer 1, starts immediately
- **Arrow II** (sprite 72) — fires on timer 2, starts with a longer initial delay

Using both types in the same room gives staggered firing patterns. The timer reset interval
depends on the total number of arrows in the room: ~2.5 seconds with 1 arrow, ~5 seconds
with 2 or more.

### Placing an Arrow

1. Select the **Enemies** layer
2. Select the **Insert Tile** tool (T)
3. In the **Guardians** tileset, select **Arrow I** (sprite 71) or **Arrow II** (sprite 72)
4. Click in the map to place. The Y position determines the arrow's flight altitude.
   By convention, place the arrow on the side of the room it originates from, but this
   is not required

### Setting Arrow Properties

Select the placed arrow and configure in the Properties panel:

1. Set **Type** to `Arrow`
2. Set **Color** — click the color swatch to pick the arrow's display color
3. Set **FlightDirection** — `Right→Left` or `Left→Right`
4. Set **Speed** — flight speed (0–8)

Arrows do **not** need a Route object — they fly in a straight horizontal line.

> **Example:** Open `pitfall2/016.tmx` to see an Arrow II with FlightDirection and Speed
> configured.

---

## 10. Routes

Routes define guardian patrol paths. They are placed on the **Routes** layer.

### Creating a Route

**Using the template** (recommended):
1. Select the **Routes** layer in the Layers panel
2. Use **Insert Template** (drag from the Templates panel, or use the Insert Template tool)
   and select `templates/route.tx`
3. Click to place at the start of the patrol path
4. Double-click the placed route to edit its polyline — drag the endpoint to define the path

**Manually:**
1. Select the **Routes** layer
2. Select the **Insert Point** tool and draw a polyline with two points
3. Select the object, then set **Type** to `Route` in the Properties panel
4. Add the required properties (see below)

### Route Properties

Select a route with the **Select Objects** tool (S) and configure in the Properties panel:

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `Guardian` | object | Yes | Object reference to the guardian this route controls. |
| `Speed` | Speed | Yes | Movement speed (0–8). `1` = Normal. `8` = Very Slow. |
| `Traversal` | Traversal | Yes | Movement pattern (see below). |
| `Direction` | Direction | No | Initial direction of travel. |

### Traversal Modes

| Value | Name | Behavior |
|-------|------|----------|
| 0 | **Ping-Pong** | Moves back and forth between endpoints. |
| 1 | **One-Way Reset** | Moves to end, then teleports back to start. |
| 2 | **One-Way Stop** | Moves to end, then stops. |
| 3 | **Loop** | Moves to end, then wraps around to start seamlessly. |

### Polyline Path

Routes use a 2-point polyline to define the patrol path as a **center-line**. When you
double-click a route to edit it, you'll see the two points:

- **Vertical** route: both points share the same X (the line goes straight up/down)
- **Horizontal** route: both points share the same Y (the line goes straight left/right)

The distance between the two points determines the patrol length. The converter automatically
adjusts from center-path to top-left coordinates based on the guardian's sprite dimensions.

### Linking Routes to Guardians

Every route must be linked to the guardian it controls:

1. Select the route object with the **Select Objects** tool (S)
2. In the Properties panel, find the **Guardian** property
3. Click its value field, then click the guardian object in the map to link them

Alternatively, you can type the guardian's object ID directly into the field.

> **Tip:** The extension's **Check/Fix Orphaned Routes** tool (Map menu) can auto-link routes
> to guardians based on spatial overlap — useful after placing several guardians and routes.

> **Example:** Open `training/003.tmx` to see a horizontal route, or `training/001.tmx`
> for vertical routes.

---

## 11. Spawn Points

Spawn points define where players appear. They are placed on the **Spawn** layer (or the
**Special** layer for infrastructure rooms).

### Placing Spawn Points

1. Select the **Spawn** layer in the Layers panel
2. Open the **Templates** panel (View > Views and Toolbars > Templates)
3. Navigate to the project's `templates/` folder and select the appropriate template
4. Click in the map to place the spawn point
5. With the spawn selected, override **GameModes** in the Properties panel to specify which
   game modes use this spawn

### Available Templates

| Template | Kind | Team | Default GameModes | Use Case |
|----------|------|------|-------------------|----------|
| `spawn_player.tx` | Player Start | Neutral | — | Generic player spawn |
| `spawn_player_red.tx` | Player Start | Red | WILLY_TEAMS | Red team spawn |
| `spawn_player_blue.tx` | Player Start | Blue | WILLY_TEAMS | Blue team spawn |
| `spawn_player_green.tx` | Player Start | Green | WILLY_TEAMS | Green team spawn |
| `spawn_player_orange.tx` | Player Start | Orange | WILLY_TEAMS | Orange team spawn |
| `spawn_flag_neutral.tx` | Flag | Neutral | CTF | Neutral CTF flag |
| `spawn_flag_red.tx` | Flag | Red | WILLY_TEAMS+CTF | Red team flag |
| `spawn_flag_blue.tx` | Flag | Blue | WILLY_TEAMS+CTF | Blue team flag |
| `spawn_flag_green.tx` | Flag | Green | WILLY_TEAMS+CTF | Green team flag |
| `spawn_flag_orange.tx` | Flag | Orange | WILLY_TEAMS+CTF | Orange team flag |
| `spawn_ball.tx` | Ball Spawn | Neutral | WILLY_BALL | Ball starting position for Willy Ball mode |

### Spawn Properties

Select a placed spawn with the **Select Objects** tool (S) to view and override its properties.
Template defaults can be overridden per-instance:

| Property | Type | Description |
|----------|------|-------------|
| `Kind` | SpawnKind | `Player Start`, `Flag`, `Exit`, or `Ball Spawn`. |
| `Team` | Team | `No Team`, `Red`, `Blue`, `Green`, `Orange`. |
| `GameModes` | GameModes (flags) | Which game modes this spawn is active for. Tiled shows these as checkboxes — tick the modes you want. **Must be non-zero** (except for Exit spawns). |
| `Position` | int | Ordered spawn position (0 = default/unordered, 1+ = ordered e.g. podium). Default: 0. |
| `VarianceX` | int | Horizontal spread per player in tiles. Default: 0. |
| `VarianceY` | int | Vertical spread per player in tiles. Default: 0. |

### GameModes

The `GameModes` property appears in the Properties panel as a set of checkboxes (since it is
a flags enum). Tick the modes this spawn should be active for:

COLLECT_X_ITEMS, TIMED_GAMES, RACE_TO_GAMES, DISCOVERY_GAMES, GOLDEN_WILLY, WILLY_TAG,
BRITISH_BULLDOG, WILLY_TEAMS, CAPTURE_THE_FLAG, LOBBY, FIRST_TO_COLLECT, COLLECT_ALL,
CHAIN_GAMES, IT_TAG, MM_START, WILLY_BALL

> **Important:** Every non-EXIT spawn **must** have at least one GameMode ticked.
> The converter will error if GameModes is left empty for player starts and flags.

> **Example:** Open `training/001.tmx` for a simple neutral spawn, or `rj-flag-cross/`
> for team spawns and CTF flags.

### MM Exit Spawns

Manic Miner exit gates are placed as tile objects using the MM Exit tileset — not as spawn
templates. The last tile in the MM Exit tileset has the `Final` flag set, which triggers the
victory condition when reached. See [Specialty Tilesets](#specialty-tilesets) for how to add
the MM Exit tileset to a room.

---

## 12. Special Objects

The **Special** object layer is used for team doors, team barriers, and additional spawn points
in infrastructure rooms.

### Team Doors

Team doors are tile overlays that act as solid blockages. The overlay is **removed** (door
opens) when the assigned team is active, and **placed** (door closes) when the team is not
active. Use these to gate areas by team — e.g., a Red team door opens only when Red is an
active team.

1. Select the **Special** layer in the Layers panel
2. Select the **Insert Tile** tool (T)
3. Pick a solid tile from the tilesets — this tile is placed as the blocking overlay
4. Click to place the tile object where you want the door
5. Select the placed object and add a **Team** property (Team enum) in the Properties panel

You can place multiple door tiles to form a doorway (e.g., a column of 3 tiles).

**Properties:**

| Property | Type | Description |
|----------|------|-------------|
| `Team` | Team | Team that this door opens for (Red, Blue, It, Green, Orange). |
| `MinPlayerCount` | int | Optional. Minimum connected players to activate. Default: 0. |

### Team Barriers

Team barriers are tile overlays that are **removed** when both conditions are met: the
assigned team is available in the current map, AND the connected player count meets the
minimum threshold. Otherwise the barrier remains in place.

1. Place tile objects on the **Special** layer (same workflow as team doors)
2. Add a **RequiredTeam** property instead of Team

| Property | Type | Description |
|----------|------|-------------|
| `RequiredTeam` | Team | Team that must be available for the barrier to open. |
| `MinPlayerCount` | int | Minimum connected players required. Default: 0. |

### Spawn Points on Special Layer

Spawn templates can also be placed on the Special layer (using the same workflow as the Spawn
layer). This is used in infrastructure rooms like the gaming lounge, where spawns serve the
LOBBY mode.

> **Example:** Open `_gaminglounge/179.tmx` to see team doors (Red/Blue) on the Special
> layer, and `_gaminglounge/182.tmx` for team barriers (Green/Orange) with RequiredTeam.

---

## 13. Ropes

Ropes are enabled per-room via room properties — there is no rope object to place.

1. Set the room's `Rope` property to `true`
2. Optionally adjust `Rope Offset` (signed integer) to shift the rope horizontally in tiles
   (0 = center of room)

> **Example:** Open rooms in `rj-the-ropery/` for a rope-heavy map, or `pitfall2/016.tmx`
> for a room combining ropes with arrows.

The rope is always vertical and appears at a default position in the room.

---

## 14. World File & Navigation

### World File

The `.world` file positions rooms in Tiled's world view, letting you see and navigate the
overall map layout. It is a JSON file listing each room's filename and pixel position:

```json
{
  "maps": [
    { "fileName": "001.tmx", "x": 0, "y": 0, "width": 256, "height": 128 },
    { "fileName": "002.tmx", "x": 256, "y": 0, "width": 256, "height": 128 }
  ],
  "type": "world"
}
```

Room positions are in multiples of 256 (width) and 128 (height) to tile correctly.

When creating rooms via the extension dialog, rooms are auto-placed in the world based on
their exit connections.

### Snap Commands (Shift+Arrow)

Repositions the current room in the world to align with its exit target:
- **Snap Up** (Shift+↑) — places current room above its Up exit target
- **Snap Down** (Shift+↓) — places current room below its Down exit target
- **Snap Left** (Shift+←) — places current room left of its Left exit target
- **Snap Right** (Shift+→) — places current room right of its Right exit target

These are only enabled when the exit is defined and the target position is unoccupied.

### Go To Commands (Ctrl+Arrow)

Opens the room connected via the specified exit:
- **Go Up** (Ctrl+↑) — opens the Up exit room
- **Go Down** (Ctrl+↓) — opens the Down exit room
- **Go Left** (Ctrl+←) — opens the Left exit room
- **Go Right** (Ctrl+→) — opens the Right exit room

The action label shows the target room ID (e.g., "Go ↑ to 178").

---

## 15. Game Mode Configuration

The `ValidGameModes` property on the `.tiled-project` declares which game modes the map
supports. This is a flags enum — multiple modes can be selected.

### Available Game Modes

| Flag | Mode | Spawn Requirements |
|------|------|--------------------|
| COLLECT_X_ITEMS | Collect target items | Neutral spawn OR team spawns |
| TIMED_GAMES | Timed gameplay | Neutral spawn OR team spawns |
| RACE_TO_GAMES | Race to target room | Neutral spawn (always) |
| DISCOVERY_GAMES | Explore and discover | Neutral spawn (always) |
| GOLDEN_WILLY | Golden Willy mode | Neutral spawn OR team spawns |
| WILLY_TAG | Tag gameplay | Neutral spawn (always) |
| BRITISH_BULLDOG | British Bulldog | Neutral spawn (always) |
| WILLY_TEAMS | Team-based gameplay | Red + Blue team spawns |
| CAPTURE_THE_FLAG | CTF mode | See CTF rules below |
| LOBBY | Lobby/infrastructure | Neutral spawn |
| FIRST_TO_COLLECT | First to collect target | Neutral spawn OR team spawns |
| COLLECT_ALL | Collect everything | Neutral spawn OR team spawns |
| CHAIN_GAMES | Chain game rooms | Neutral spawn OR team spawns |
| IT_TAG | It-Tag variant | Neutral spawn (always) |
| MM_START | Manic Miner start | Neutral spawn |
| WILLY_BALL | Team ball-carrying game | BALL_SPAWN + CTF team flags + WILLY_TEAMS spawns (see below) |

> **Note:** `LOBBY` and `MM_START` are infrastructure/map flags, not gameplay modes that
> players select. `LOBBY` marks rooms belonging to the gaming lounge infrastructure (see
> [Infrastructure Rooms](#16-infrastructure-rooms)). `MM_START` marks the starting room for
> Manic Miner-style single-player progression.

### Spawn Coverage Rules

- **Modes requiring neutral spawns:** RACE_TO_GAMES, DISCOVERY_GAMES, WILLY_TAG,
  BRITISH_BULLDOG, IT_TAG, CHAIN_GAMES — these *always* need a neutral (teamless) player spawn.
- **Team-capable modes:** COLLECT_X_ITEMS, TIMED_GAMES, CAPTURE_THE_FLAG, GOLDEN_WILLY,
  COLLECT_ALL, FIRST_TO_COLLECT — these need *either* a neutral spawn *or* team spawns
  (Red + Blue minimum).
- **WILLY_TEAMS:** Requires Red and Blue team spawns. Green/Orange are optional but can only
  exist if Red and Blue are present.

### CTF Rules

**Team CTF** (WILLY_TEAMS + CAPTURE_THE_FLAG):
- Needs ≥2 teams with both a CTF-tagged team spawn AND a CTF-tagged team flag
- Flags and spawns must both have CAPTURE_THE_FLAG in their GameModes

**Solo CTF** (CAPTURE_THE_FLAG without WILLY_TEAMS):
- Needs a CTF-tagged neutral spawn AND a CTF-tagged neutral flag

### Willy Ball Rules

**WILLY_BALL** requires all three of:

1. **A `BALL_SPAWN` point** — place using the `spawn_ball.tx` template. This is the ball's reset position (where it appears at match start and after a goal). Only one BALL_SPAWN per map is expected. Its `GameModes` must include `WILLY_BALL`.
2. **CTF-style team flags** — Red and Blue (minimum) flag spawns tagged with both `CAPTURE_THE_FLAG` and `WILLY_TEAMS` in their `GameModes`. These define the goal zones — the ball carrier scores by reaching the opposing team's flag position.
3. **WILLY_TEAMS player spawns** — Red and Blue (minimum) player spawns tagged with `WILLY_TEAMS`. Green and Orange are optional but require Red and Blue to be present.

`ValidGameModes` for a Willy Ball map must include at minimum: `WILLY_BALL | WILLY_TEAMS | CAPTURE_THE_FLAG`.

---

## 16. Infrastructure Rooms

Infrastructure rooms serve special functions in the gaming lounge (lobby area). They are
identified by the `RoomPurpose` property.

### Room Purposes

| Value | Purpose | Description |
|-------|---------|-------------|
| 0 | **Gameplay** | Normal game room (default). |
| 1 | **Lobby** | Main lobby room where players gather before a game. |
| 2 | **Team Select** | 2-team selection room (Red/Blue). |
| 3 | **Launchpad** | Transition room before game start. |
| 4 | **Victory Room** | Post-game victory screen room. |
| 5 | **Briefing** | Mission briefing countdown room. |
| 6 | **Team Select 4** | 4-team selection room (Red/Blue/Green/Orange). |

### Rules

- Each non-Gameplay purpose can only appear **once** across all rooms in a map.
- Non-Gameplay rooms require `ValidGameModes` to include only `LOBBY`.
- Infrastructure rooms may place spawns on the **Special** layer (not just Spawn).
- Always use `RoomPurpose` to identify infrastructure rooms — never hardcode room IDs.

### Gaming Lounge Pattern

Open the `_gaminglounge` project in Tiled to see the standard infrastructure layout:
- Lobby room (RoomPurpose=1) — main gathering point
- Briefing room (RoomPurpose=5) — countdown before game
- Team Select room (RoomPurpose=2) — team picking
- Launchpad (RoomPurpose=3) — game launch transition
- Victory Room (RoomPurpose=4) — game over celebration

---

## 17. Building & Testing

### Converting TMX to Game Format

Convert individual room files **and** the pack file. These scripts live in the **game
repository** under `build_scripts/tmx/`, not in the maps repository. Run them from the
game project root:

```bash
# macOS / Linux
uv run build_scripts/tmx/tmx_to_jsw.py tmx/content/<map-name>
uv run build_scripts/tmx/tmx_to_jsw.py tmx/content/<map-name> --pack

# Windows
uv run build_scripts\tmx\tmx_to_jsw.py tmx\content\<map-name>
uv run build_scripts\tmx\tmx_to_jsw.py tmx\content\<map-name> --pack
```

> **Important:** Always run **both** commands. The game loads individual files from the folder
> when it exists, preferring them over the pack file. Running only `--pack` can leave stale
> individual files.

### Authorship metadata (`--pack` only)

Standalone packs (maps with their own tilesets) carry an authorship
`meta` entry: originator GUID + display name + a per-export
modification log. The exporter reads the local `client.cfg`
identity by default; CI / scripted builds override it via flags:

```bash
# Tag a build with explicit identity (CI use)
uv run build_scripts/tmx/tmx_to_jsw.py tmx/content/<map-name> --pack \
    --originator-guid 0123456789abcdef --originator-name BuildBot

# Suppress meta entirely (legacy / hermetic builds)
uv run build_scripts/tmx/tmx_to_jsw.py tmx/content/<map-name> --pack --no-meta
```

**First export** anchors `originator_guid` + `originator_name`.
**Re-exports** preserve the original anchor and append a fresh
modification entry — the originator never gets overwritten, so a
map's lineage stays intact even when contributors take turns
editing. **Non-standalone (rooms-only) packs** silently skip
stamping; the compact `ContentType.ROOMS` entry table strips entry
names on save, so a `meta` entry wouldn't survive a round-trip
there. The exporter prints a one-line note if `--originator-*` was
given on a non-standalone target.

The metadata feeds the upcoming custom-map sharing flow — see
[`docs/formats/CUSTOM_MAPS_TRANSFER.md`](../../docs/formats/CUSTOM_MAPS_TRANSFER.md)
for how forks / divergence / network distribution are layered on top.

### Regenerating All Maps

```bash
# macOS / Linux
uv run build_scripts/tmx/regenerate_all_packs.py

# Windows
uv run build_scripts\tmx\regenerate_all_packs.py
```

This refreshes all project templates from the archetype, converts all maps in `content/`,
and cleans stale pack files. Directories prefixed with `__` are skipped.

### Refreshing Project Templates

When enum values change in the archetype:

```bash
# macOS / Linux
uv run scripts/tmx_project.py refresh

# Windows
uv run scripts\tmx_project.py refresh
```

This propagates updated property type definitions to all projects in `content/` and
`_in_progress/`.

### Testing In-Game

Run the game executable for your platform with the `--map` flag to load your map:

```
# Windows
jswr.exe --map <map-name>
jswr.exe --map <map-name> --room 001
jswr.exe --map <map-name> --debug

# Linux / SteamDeck
./jswr --map <map-name>

# macOS
open jswr.app --args --map <map-name>
```

---

## 18. Extension Tools

The JSW:R Tiled extension (`.extensions/jswr.js`) provides validation and fix tools accessible from
Tiled's **Map** menu.

### [WORLD] Validate Spawn Points

Scans all rooms in the map and reports:
- Spawn coverage per team and kind (Player Start vs Flag)
- GameModes coverage analysis
- Team pairing warnings (Red without Blue, etc.)
- Flag location listing
- Can save report to `spawn_report.txt`

### [WORLD] Check/Fix Orphaned Guardian Routes

Scans all rooms for:
- Routes with missing or null `Guardian` property
- Unassigned guardians (no route references them)
- Auto-links routes to guardians based on spatial overlap (when unambiguous)
- Can save report to `route_report.txt`

### [ROOM] Check/Fix Room Properties

Checks the current room for missing standard properties and adds defaults:
- `Name` (empty string), `Rope` (false), `Rope Offset` (0), `Flags` (empty)
- Exit properties `Up`/`Down`/`Left`/`Right` (typed `file`, empty string default).
  Legacy rooms with untyped string exits are auto-promoted to `file` type.
- `WillySuit` (Normal)
- `RoomPurpose` (Gameplay) — exposes the enum in the sidebar so it's
  discoverable; the pack-time converter also regex-scans the raw TMX when
  the property is absent.

### [ROOM] Check/Fix Guardian/Guardian Route Properties

Fixes all guardians and routes in the current room:
- Sets `type` to `"Guardian"` or `"Arrow"` based on GID
- Generates descriptive names with instance numbering (e.g., "Bird 1", "Bird 2")
- Adds missing `Color` (white), `Flags`, `FlightDirection` (arrows), `Speed` (arrows)
- Adds missing route properties: `Direction`, `Speed`, `Traversal`
- Includes orphaned route auto-linking

### [SELECTED] Check/Fix Guardian/Guardian Route Properties

Same as above but only processes selected objects. Useful for fixing newly added guardians.

---

## 19. Validation Rules

The converter (`build_scripts/tmx/tmx_to_jsw.py --pack`) enforces these rules at pack time. Errors cause the
build to fail; warnings are reported but don't block.

### Errors (Build Fails)

- `MapName` not set in `.tiled-project`
- Any non-EXIT spawn has `GameModes=0`
- Neutral spawn has `WILLY_TEAMS` in its `GameModes`
- Red team spawns exist without Blue (or vice versa) — incomplete team pair
- Green/Orange spawns exist without both Red and Blue
- Mode requiring neutral spawn (RACE, DISCOVERY, TAG, BULLDOG) has no neutral spawn
- Team-capable mode has neither neutral spawn nor team spawns
- Team flags incomplete (Red flag without Blue flag)
- Team flags exist but no team spawns
- Neutral flag exists but no neutral spawn
- Solo CTF without CTF-tagged neutral spawn or flag
- Team CTF without matching CTF-tagged team spawn+flag pairs
- WILLY_BALL without a BALL_SPAWN point (SpawnKind=3) in the map
- WILLY_BALL without WILLY_TEAMS in `ValidGameModes`
- WILLY_BALL without matching CTF-tagged team flag pairs (Red + Blue minimum)
- Non-Gameplay room without LOBBY-only `ValidGameModes`
- Duplicate non-Gameplay `RoomPurpose` values

### Warnings (Build Continues)

- `Author` not set
- Mode in `ValidGameModes` not covered by any spawn
- Spawn covers a mode not in `ValidGameModes`
- Flag spawn not tagged with CAPTURE_THE_FLAG
- Guardian missing `Color` property (defaults to white)
- `FallDamageMode` not set (defaults to Lenient)

---

## 20. Tips & Common Pitfalls

### Coordinate System

- **Y=0 is at the top** of the room in game coordinates (and in Tiled's default view)
- Room dimensions: 32×16 tiles = 256×128 pixels
- All TMX coordinates are in game pixel space (tilewidth=8)

### Tile Object Anchoring

Tiled anchors tile objects (collectibles, guardians, spawns) at the **bottom-left** corner.
The converter adjusts Y by subtracting the tile height. When placing objects, the position you
see in Tiled is the bottom-left, not the top-left.

For spawn objects, the converter subtracts 16 from Y (two tiles height) for the anchor
adjustment.

### Naming Conventions

- Room files: `NNN.tmx` (zero-padded 3 digits, e.g., `001.tmx`)
- Map directories: lowercase with hyphens (e.g., `rj-flag-cross`)
- Guardian names: Type + instance number (e.g., `"Beetle 1"`, `"Bird 2"`)

### Common Mistakes

1. **Forgetting GameModes on spawns** — every player start and flag must have a non-zero
   `GameModes` value.
2. **Incomplete team pairs** — if you add a Red spawn, you must also add Blue.
3. **Running only `--pack`** — always run both individual conversion and pack conversion.
4. **Wrong firstgid for specialty tilesets** — if Tiled auto-assigns a different firstgid when
   adding Penrose or Collapsible tilesets, the converter's GID fixer can correct it, but it's
   better to accept the default values from the `.tsx` files.
5. **Orphaned routes** — every route must have its `Guardian` property linked to a guardian
   object. Use the extension's Check/Fix tools to detect and fix these.
6. **Neutral spawns in team-only modes** — a neutral spawn must not have `WILLY_TEAMS` in its
   `GameModes`.

---

## Appendix A: Custom Tilesets

JSW:R supports multiple visual styles for tiles. The game ships with two built-in styles
("enhanced" and "original") and can discover additional styles at runtime. Custom tilesets
let you give your map a completely different look while keeping the same tile physics.

### How the Game Discovers Tileset Styles

At startup, the game scans `assets/sprites/` for subdirectories containing a `tiles/`
folder. Each such directory is registered as an available tileset style. The directory name
becomes the style name (e.g., `assets/sprites/gorgeous/tiles/` registers as "gorgeous").

The built-in styles are:

| Directory | Style Name | Color Clash |
|-----------|-----------|-------------|
| `assets/sprites/enhanced/tiles/` | enhanced | No |
| `assets/sprites/original/tiles/` | original | Yes |

For custom styles, the game reads optional properties from `tiles_solid.tsx` in the tiles
directory:

- **TilesetName** — overrides the display name (e.g., directory "gorgeous" shows as
  "Gorgeous" in the menu)
- **SupportsColorClash** — whether the ZX Spectrum color clash shader can be applied to
  this tileset (default: false)

Players cycle through available styles with F9 during gameplay.

### Tile File Structure

Each tileset style directory must contain these PNG files (one per standard tileset type):

```
assets/sprites/<style>/tiles/
    tiles_solid.png
    tiles_stairs.png
    tiles_platform.png
    tiles_hazard.png
    tiles_decoration.png
    tiles_conveyor.png
    tiles_collapsible.png   (optional)
    tiles_penrose.png       (optional)
```

Each PNG is a tilesheet in the same 16-column layout as the shared tilesets in
`tmx/tilesets/`. Tile dimensions are 8x8 pixels. The tile count per image must match or
exceed the standard tilesets — the game uses tile index to look up graphics, so index 0 in
the custom solid tileset replaces index 0 in the standard solid tileset, and so on.

### Distributing Custom Tilesets with Map Packs

For standalone map packs (`.jsw` files), custom tilesets are embedded using the JSWC
(JSW Collection) binary format. This bundles all tileset PNGs into a single blob inside the
pack, along with metadata (tileset name, color clash support).

The pack structure looks like:

```
my-map.jsw (JSWP)
├── rooms (room data)
└── tiles (JSWC)
    ├── Collection Header (name="Gorgeous", supports_color_clash=false)
    ├── solid (JSWX — tiles_solid.png)
    ├── stairs (JSWX — tiles_stairs.png)
    ├── platform (JSWX — tiles_platform.png)
    ├── hazard (JSWX — tiles_hazard.png)
    ├── decoration (JSWX — tiles_decoration.png)
    └── conveyor (JSWX — tiles_conveyor.png)
```

When a player loads a pack that contains a JSWC tiles entry, the game registers that
tileset style and switches to it automatically. See `docs/formats/JSWC_TILESET_COLLECTION_FORMAT.md`
for the full binary format specification.

### Tileset Variants (Multi-Resolution Support)

Custom tilesets can ship multiple variants (e.g., a base 8x8 set and a 16x16 hi-res set)
that players cycle through with F9. The current workflow uses a `tilesets.json` manifest
in the map's project root to declare each variant's display name, color clash support,
and per-room overrides. See [STANDALONE_MAPS.md](STANDALONE_MAPS.md) for the manifest
format and the full standalone-map packaging pipeline.

### Creating a New Custom Tileset

To create a new tileset style from scratch:

1. Create a directory under `assets/sprites/` with your style name (e.g.,
   `assets/sprites/retro/tiles/`)

2. Create PNG tilesheets for each tile type, matching the standard layout — 16 columns,
   8x8 pixel tiles, same tile count as the corresponding shared tileset in `tmx/tilesets/`

3. Optionally create a `tiles_solid.tsx` in your tiles directory with `TilesetName` and
   `SupportsColorClash` properties to control the display name and color clash support

4. The game will discover the style on next startup and make it available via F9

5. To bundle it with a map pack for distribution, use the JSWC packing tools to embed the
   tilesets in your `.jsw` pack file
