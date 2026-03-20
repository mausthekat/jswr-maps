# JSW:O Tiled Map Editor Tools

This folder contains Tiled map editor integration for JSW:O (Jet Set Willy Online), including a Tiled extension and conversion scripts.

## Folder Structure

```
tmx/
├── content/              # Map content folders
│   └── <mapname>/        # Map-specific folders (e.g., main/)
│       ├── <mapname>.world  # World file for room positions
│       ├── <mapname>.tiled-project # Tiled project file
│       └── *.tmx         # Room files (001.tmx - 255.tmx)
├── tilesets/             # Shared tilesets (referenced by all maps)
│   ├── tiles_solid.tsx     # Solid blocks (GID 1-160)
│   ├── tiles_stairs.tsx    # Stairs/ramps (GID 161-224)
│   ├── tiles_platform.tsx  # One-way platforms (GID 225-304)
│   ├── tiles_hazard.tsx    # Hazard tiles (GID 305-336)
│   ├── tiles_decoration.tsx # Decoration tiles (GID 337-400)
│   ├── tiles_conveyor.tsx  # Conveyor belts (GID 401-576)
│   ├── collectibles.tsx    # Collectible items (GID 577-676)
│   ├── guardians.tsx       # Guardian sprites collection (GID 677-751)
│   ├── guardians.txt       # Guardian names (75 lines, one per tile)
│   └── guardians/          # Individual guardian sprite images
├── extensions/           # Tiled extension
│   └── jswo.js           # JSW:O Tiled plugin
└── scripts/              # Conversion scripts
    ├── dat_to_tmx.py             # Convert .dat files to .tmx
    ├── tmx_to_dat.py             # Convert .tmx to .dat files
    ├── tmx_to_jsw.py             # Convert .tmx to .jsw format
    └── update_tmx_bg_colors.py   # Set background colors from tiles
```

## Tiled Extension (jswo.js)

The Tiled extension adds JSW:O-specific menu items under **Map** menu.

## Menu Reference

### New JSW:O Room... (Ctrl+Shift+N)

Creates a new room in the current map project.

**Features:**
- Auto-selects next available room ID (001-255)
- Set room name (max 32 characters)
- Configure exit connections (Up/Down/Left/Right)
- Enable rope for the room
- Auto-places room in .world file based on exit connections

**Dialog Fields:**

| Field | Description |
|-------|-------------|
| Room ID | Three-digit room identifier (001-255) |
| Room Name | Display name shown in-game |
| ↑ Up | Room connected above (player falls/climbs to) |
| ↓ Down | Room connected below |
| ← Left | Room connected to the left |
| → Right | Room connected to the right |
| Has Rope | Whether the room contains a rope |

---

### Check/Fix Orphaned Guardian Routes...

Scans all rooms in the current map project and repairs route-guardian assignments.

**What it does:**
1. Finds routes with empty Guardian property (orphaned routes)
2. Finds guardians not referenced by any route (unassigned guardians)
3. Auto-fixes unambiguous cases (one overlapping guardian for one route)
4. Reports remaining issues that need manual attention

**Report includes:**
- Routes auto-fixed
- Remaining orphaned routes
- Unassigned guardians
- Per-room breakdown of issues

**Save Report** button exports the full report to `route_report.txt` in the map folder.

---

### Check/Fix Guardian/Guardian Route Properties...

Scans all guardians and guardian routes in the **current room** and fixes missing/incorrect properties.

**For Guardians:**
- Sets the object name from `guardians.txt` based on GID
- Adds numbering when multiple of same type exist (e.g., "Egg 1", "Egg 2")
- Adds missing `Color` property (defaults to #ffffff)

**For Arrows:**
- Adds missing `FlightDirection` property (defaults to 0 = Right→Left)
- Adds missing `Speed` property (defaults to 1)

**For Routes:**
- Adds missing `Direction` property (defaults to 0 = Up)
- Adds missing `Speed` property (defaults to 1)

**Report shows:**
- Total objects checked
- Properties that were fixed/updated
- Detailed per-object change list

---

### Check/Fix Selected Guardian/Guardian Route

Same as above, but only applies to currently selected objects.

**Availability:** Only enabled when one or more Guardian, Arrow, or Route objects are selected.

---

### Snap ↑/↓/←/→ to [Room]

Moves the current room in the .world file to align with its exit connection.

**Example:** If room 042 has its Up exit set to room 041, "Snap ↑ to 041" positions room 042 directly below room 041 in the world view.

**Availability:**
- Shown only when at least one exit is defined
- Disabled if already aligned with "(aligned)"
- Disabled if target position occupied by another room with "(occupied)"
- Disabled if target room not in world with "(not in world)"

**Requirements:** The .world file must be open in Tiled.

---

### Go ↑/↓/←/→ to [Room]

Opens the room connected via the specified exit direction.

**Example:** If current room has Right exit set to room 039, "Go → to 039" opens 039.tmx.

**Availability:**
- Shown only when the exit is defined
- Disabled if target .tmx file doesn't exist with "(missing)"

---

## Guardian Name Files

Guardian names are loaded from `tilesets/guardians.txt`:

### guardians.txt

One name per line (75 lines total). Line number corresponds to tile index in guardians.tsx:
- Lines 1-70: Normal guardian sprites (tiles 0-69, GID 677-746)
- Line 71: Lift (tile 70, GID 747)
- Lines 72-73: Arrow I, Arrow II (tiles 71-72, GID 748-749)
- Line 74: Periscope Tank (tile 73, GID 750)
- Line 75: Evil Head (tile 74, GID 751)

---

## Conversion Scripts

### dat_to_tmx.py

Converts binary .dat room files to Tiled .tmx format, or creates new empty maps.

**Convert existing .dat files:**

```bash
python tmx/scripts/dat_to_tmx.py assets/rooms/<mapname> --map --templates --extensions
```

**Input:** `assets/rooms/<mapname>/` folder containing:
- `*.dat` - Room tile data
- `*_enemy.dat` - Enemy/guardian data
- `*_pickups.dat` - Collectible positions

**Output:** `tmx/content/<mapname>/` folder containing:
- `*.tmx` - Individual room files
- `<mapname>.world` - World file with room positions

**Create a new empty map:**

```bash
python tmx/scripts/dat_to_tmx.py --new <mapname>
```

Creates a new map project with:
- Output folder at `tmx/content/<mapname>/`
- Default room `001.tmx` filled with tile 1 (first tile in tileset)
- World file with the default room at position (0, 0)
- Tiled project file with property type definitions
- Templates folder with room template
- Extensions folder with jswo.js plugin

You can also specify a full path:

```bash
python tmx/scripts/dat_to_tmx.py --new path/to/mymap
```

### tmx_to_dat.py

Converts Tiled .tmx files back to binary .dat format.

```bash
python tmx/scripts/tmx_to_dat.py <map_folder>
```

**Input:** `tmx/content/<mapname>/` folder with .tmx files

**Output:** `assets/rooms/<mapname>/` folder with .dat files

### tmx_to_jsw.py

Converts Tiled .tmx files to the new .jsw binary format.

```bash
python tmx/scripts/tmx_to_jsw.py tmx/content/<mapname> [output_folder]
```

**Options:**
- `--pack` - Create a single packed .jsw file instead of individual room files
- `--export-palettes` - Export tile palette images for debugging

---

## TMX File Format

Each room is stored as a 32x16 tile map (256x128 pixels) with:

### Map Properties

| Property | Type | Description |
|----------|------|-------------|
| Name | string | Room display name |
| Chunk | int | Chunk ID for loading |
| Up | file | Exit room above (e.g., "041.tmx") |
| Down | file | Exit room below |
| Left | file | Exit room to left |
| Right | file | Exit room to right |
| Rope | bool | Whether room has a rope |
| Rope Offset | int | Signed rope position adjustment |
| Flags | RoomFlags | Room flags (MIRROR_TRIGGER, etc.) |

### Layers

1. **Tiles** - Tile layer with room geometry
2. **Collectables** - Object layer for collectible items
3. **Enemies** - Object layer for guardians, arrows, and routes

### Object Types

**Guardian** (type="Guardian")
- Has GID referencing guardians.tsx
- Properties: Color, Flags (GuardianFlags)

**Arrow** (type="Arrow")
- Has GID referencing arrow tiles (747-748)
- Properties: Color, FlightDirection, Speed

**Route** (type="Route")
- Rectangle defining guardian movement area
- Properties: Direction, Guardian (object reference), Speed

### Property Enums

**Direction** (for routes):
- 0 = Up
- 1 = Down
- 2 = Left
- 3 = Right

**Speed**:
- 0 = Stopped
- 1 = Normal
- 2-7 = Faster
- 8 = Very Slow

**FlightDirection** (for arrows):
- 0 = Right→Left
- 1 = Left→Right

**RoomFlags**:
- MIRROR_TRIGGER - Crossing room center triggers mirror mode

**GuardianFlags**:
- HARMLESS - Guardian does not kill player
- ALWAYS_DEADLY - Guardian kills even when invulnerable

---

## Tileset GID Ranges

| Tileset | First GID | Last GID | Tile Count | Description |
|---------|-----------|----------|------------|-------------|
| tiles_solid.tsx | 1 | 160 | 160 | Solid blocks |
| tiles_stairs.tsx | 161 | 224 | 64 | Stairs/ramps |
| tiles_platform.tsx | 225 | 304 | 80 | One-way platforms |
| tiles_hazard.tsx | 305 | 336 | 32 | Hazard tiles |
| tiles_decoration.tsx | 337 | 400 | 64 | Decoration tiles |
| tiles_conveyor.tsx | 401 | 576 | 176 | Conveyor belts |
| collectibles.tsx | 577 | 676 | 100 | Collectible items |
| guardians.tsx | 677 | 751 | 75 | Guardian sprites (collection) |

### Guardians Collection Details

The guardians tileset is a "collection of images" supporting different sprite sizes:

| Tile Index | GID | Size | Description |
|------------|-----|------|-------------|
| 0-69 | 677-746 | 16x16 | Normal guardian sprites |
| 70 | 747 | 16x16 | Lift platform |
| 71 | 748 | 16x16 | Arrow sprite (left) |
| 72 | 749 | 16x16 | Arrow sprite (right) |
| 73 | 750 | 16x32 | Periscope tank (tall) |
| 74 | 751 | 32x32 | Evil giant head (large) |