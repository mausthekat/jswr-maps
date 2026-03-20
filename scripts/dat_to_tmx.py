#!/usr/bin/env python3
"""
Convert JSW .dat room files to individual Tiled .tmx files and a .world file.

Usage (from project root):
    python tmx/scripts/dat_to_tmx.py assets/rooms/main --map
    python tmx/scripts/dat_to_tmx.py assets/rooms/main --templates
    python tmx/scripts/dat_to_tmx.py assets/rooms/main --extensions
    python tmx/scripts/dat_to_tmx.py assets/rooms/main --map --templates --extensions

    # Create an empty map (no source .dat files required):
    python tmx/scripts/dat_to_tmx.py --new mymap
    python tmx/scripts/dat_to_tmx.py --new path/to/mymap

If no flags are specified, nothing happens.

This will create tmx/content/main/001.tmx, 002.tmx, etc. and main.world
"""

import argparse
import os
import sys
import struct
import glob
import re
import json
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Project root is 2 levels up from this script (tmx/scripts -> tmx -> project)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))

# For parsing TSX files
import xml.etree.ElementTree as ET

# Constants from the game
ROOM_WIDTH = 32   # tiles wide
ROOM_HEIGHT = 16  # tiles tall
TILE_SIZE = 8     # pixels per tile
EDITOR_SCALE = 2  # coordinate scale in .dat files

# Room dimensions in pixels
ROOM_PIXEL_WIDTH = ROOM_WIDTH * TILE_SIZE    # 256
ROOM_PIXEL_HEIGHT = ROOM_HEIGHT * TILE_SIZE  # 128

# TMX GID flip flags
FLIPPED_HORIZONTALLY_FLAG = 0x80000000

# =============================================================================
# Guardian/Enemy Tile Mapping
# =============================================================================
# The guardians tileset has 75 tiles (indices 0-74, GIDs 14337-14411).
# With 2048-spaced firstgids, guardians start at 14337.
#
# Most entity types map directly: GID = guardians_firstgid + entity_type
#
# Special entity types remapped within guardians tileset:
#   - Lift (dat type 72) → tile index 70 (GID 14407)
#   - Arrow left (dat type 73) → tile index 71 (GID 14408)
#   - Arrow right (dat type 74) → tile index 72 (GID 14409)
#   - Periscope Tank (dat type 70) → tile index 73 (GID 14410, 16x32)
#   - Evil Giant Head (dat type 71) → tile index 74 (GID 14411, 32x32)
#
# For reverse conversion (tmx_to_dat):
#   - GID 14407 → entity_type 72 (lift)
#   - GID 14408 → entity_type 73 (arrow left)
#   - GID 14409 → entity_type 74 (arrow right)
#   - GID 14410 → entity_type 70 (periscope tank)
#   - GID 14411 → entity_type 71 (evil giant head)
# =============================================================================
GUARDIANS_FIRSTGID = 14337
GUARDIANS_TILECOUNT = 75

# Special entity types that need remapping
ENTITY_TYPE_PERISCOPE_TANK = 70   # Oversized guardian (16x32)
ENTITY_TYPE_EVIL_GIANT_HEAD = 71  # Oversized guardian (32x32)
ENTITY_TYPE_LIFT = 72
ENTITY_TYPE_ARROW_LEFT = 73
ENTITY_TYPE_ARROW_RIGHT = 74

# Tile indices for special entities (within the guardians tileset)
TILE_INDEX_LIFT = 70
TILE_INDEX_ARROW_LEFT = 71   # Penultimate tile
TILE_INDEX_ARROW_RIGHT = 72  # Last tile
TILE_INDEX_PERISCOPE_TANK = 73  # Periscope tank (16x32) - now in guardians collection
TILE_INDEX_EVIL_GIANT_HEAD = 74  # Evil giant head (32x32) - now in guardians collection

# Legacy GIDs for oversized guardians (now in guardians collection, tiles 73-74)
GID_PERISCOPE_TANK = 702      # Original legacy dat format GID
GID_EVIL_GIANT_HEAD = 703     # Original legacy dat format GID

# Guardian sprite dimensions (used for TMX object sizing and vertical path adjustment)
GUARDIAN_WIDTH_NORMAL = 16
GUARDIAN_HEIGHT_NORMAL = 16
GUARDIAN_WIDTH_EVIL_HEAD = 32   # Evil giant head is 32x32
GUARDIAN_HEIGHT_OVERSIZED = 32  # Periscope tank (16x32) and evil head (32x32)

# Guardian names loaded from text files
GUARDIAN_NAMES: List[str] = []  # Indexed by (GID - GUARDIANS_FIRSTGID) for normal guardians
PERISCOPE_TANK_NAME: str = "Periscope Tank"
EVIL_HEAD_NAME: str = "Evil Head"


# =============================================================================
# Setup.dat Parsing (Spawn Points)
# =============================================================================
# Legacy setup.dat format:
#   Bytes 0-1: Unknown
#   Bytes 2-21: Map name (20 bytes)
#   Bytes 22-41: Unknown
#   Byte 42: Start room ID
#   Byte 43: Start X (tile coordinate)
#   Byte 44: Start Y (tile coordinate)
#   Bytes 45-47: Unknown
#   Byte 48: Blue spawn room ID
#   Byte 49: Blue spawn X (tile coordinate)
#   Byte 50: Blue spawn Y (tile coordinate)
#   Bytes 51-53: Unknown
#   Byte 54: Red spawn room ID
#   Byte 55: Red spawn X (tile coordinate)
#   Byte 56: Red spawn Y (tile coordinate)
# =============================================================================

@dataclass
class SpawnInfo:
    """Spawn point information from setup.dat."""
    room_id: int
    tile_x: int
    tile_y: int
    team: int  # 0=None (neutral), 1=Red, 2=Blue


def parse_setup_dat(filepath: str) -> Dict[str, SpawnInfo]:
    """Parse a setup.dat file and extract spawn positions.

    Args:
        filepath: Path to the setup.dat file

    Returns:
        Dict with keys 'player', 'red', 'blue' mapping to SpawnInfo (or None if not present)
    """
    result = {
        'player': None,
        'red': None,
        'blue': None,
    }

    try:
        with open(filepath, 'rb') as f:
            data = f.read()
    except Exception as e:
        print(f"Warning: Could not read {filepath}: {e}")
        return result

    if len(data) < 45:
        print(f"Warning: {filepath} too small ({len(data)} bytes)")
        return result

    # Parse player start (bytes 42-44)
    start_room = data[42]
    start_x = data[43]
    start_y = data[44]

    if start_room > 0:
        result['player'] = SpawnInfo(
            room_id=start_room,
            tile_x=start_x,
            tile_y=start_y,
            team=0  # Neutral
        )
        map_name = data[2:22].decode('latin-1', errors='replace').rstrip('\x00 ')
        print(f"  Setup.dat: map='{map_name}', player start room={start_room} at ({start_x}, {start_y})")

    # Parse blue team spawn (bytes 48-50)
    if len(data) >= 51 and data[48] > 0:
        result['blue'] = SpawnInfo(
            room_id=data[48],
            tile_x=data[49],
            tile_y=data[50],
            team=2  # Blue
        )
        print(f"  Setup.dat: blue team room={data[48]} at ({data[49]}, {data[50]})")

    # Parse red team spawn (bytes 54-56)
    if len(data) >= 57 and data[54] > 0:
        result['red'] = SpawnInfo(
            room_id=data[54],
            tile_x=data[55],
            tile_y=data[56],
            team=1  # Red
        )
        print(f"  Setup.dat: red team room={data[54]} at ({data[55]}, {data[56]})")

    return result


def get_spawn_template_name(team: int) -> str:
    """Get the spawn template filename for a team.

    Args:
        team: 0=None (neutral), 1=Red, 2=Blue

    Returns:
        Template filename (e.g., 'spawn_player.tx')
    """
    if team == 1:
        return 'spawn_player_red.tx'
    elif team == 2:
        return 'spawn_player_blue.tx'
    else:
        return 'spawn_player.tx'


class TilesetGids:
    """Holds firstgid values using 2048-spaced scheme for TMX files.

    TMX FirstGid Scheme (2048-spaced):
        tiles_solid      = 1      (range 1-2048)
        tiles_stairs     = 2049   (range 2049-4096)
        tiles_platform   = 4097   (range 4097-6144)
        tiles_hazard     = 6145   (range 6145-8192)
        tiles_decoration = 8193   (range 8193-10240)
        tiles_conveyor   = 10241  (range 10241-12288)
        collectibles     = 12289  (range 12289-14336)
        guardians        = 14337  (range 14337-16384)
    """
    def __init__(self):
        # Split tile tilesets with 2048-spaced firstgids
        self.tiles_solid: int = 1
        self.tiles_stairs: int = 2049
        self.tiles_platform: int = 4097
        self.tiles_hazard: int = 6145
        self.tiles_decoration: int = 8193
        self.tiles_conveyor: int = 10241
        # Other tilesets
        self.collectibles: int = 12289
        self.guardians: int = 14337
        # Note: periscope_tank and evil_giant_head are now in guardians collection
        # as tiles 73 and 74 (GID 14410 and 14411)
        # Tile counts (for reference)
        self.tiles_solid_count: int = 160
        self.tiles_stairs_count: int = 64
        self.tiles_platform_count: int = 80
        self.tiles_hazard_count: int = 32
        self.tiles_decoration_count: int = 64
        self.tiles_conveyor_count: int = 176
        self.collectibles_count: int = 100
        self.guardians_count: int = 75  # Now includes pipe (73) and head (74)


def get_tilecount_from_tsx(tsx_path: str) -> int:
    """Parse a .tsx file and return its tilecount."""
    try:
        tree = ET.parse(tsx_path)
        root = tree.getroot()
        return int(root.get('tilecount', '0'))
    except Exception as e:
        print(f"Warning: Could not parse {tsx_path}: {e}")
        return 0


def calculate_tileset_gids(content_folder: str) -> TilesetGids:
    """Return 2048-spaced firstgid values for TMX generation.

    The firstgid values are fixed (2048 spacing) regardless of actual tile counts.
    This ensures consistency across all TMX files and aligns with the tile encoding
    system where tileset_index = (gid - 1) // 2048.
    """
    gids = TilesetGids()

    # Tilesets are in tmx/tilesets/ (sibling to content folder)
    tilesets_folder = os.path.join(os.path.dirname(content_folder), "tilesets")

    # Read tile counts from split tileset files (for reference only)
    tileset_files = [
        ("tiles_solid.tsx", "tiles_solid_count"),
        ("tiles_stairs.tsx", "tiles_stairs_count"),
        ("tiles_platform.tsx", "tiles_platform_count"),
        ("tiles_hazard.tsx", "tiles_hazard_count"),
        ("tiles_decoration.tsx", "tiles_decoration_count"),
        ("tiles_conveyor.tsx", "tiles_conveyor_count"),
    ]
    for filename, count_attr in tileset_files:
        tsx_path = os.path.join(tilesets_folder, filename)
        if os.path.exists(tsx_path):
            setattr(gids, count_attr, get_tilecount_from_tsx(tsx_path))

    # Read other tileset counts from tilesets folder (for reference only)
    collectibles_tsx = os.path.join(tilesets_folder, "collectibles.tsx")
    guardians_tsx = os.path.join(tilesets_folder, "guardians.tsx")

    if os.path.exists(collectibles_tsx):
        gids.collectibles_count = get_tilecount_from_tsx(collectibles_tsx)
    if os.path.exists(guardians_tsx):
        gids.guardians_count = get_tilecount_from_tsx(guardians_tsx)

    # FirstGid values are fixed at 2048 spacing - do NOT calculate from tile counts
    # This is the standard scheme used by all TMX files after migration
    gids.tiles_solid = 1
    gids.tiles_stairs = 2049
    gids.tiles_platform = 4097
    gids.tiles_hazard = 6145
    gids.tiles_decoration = 8193
    gids.tiles_conveyor = 10241
    gids.collectibles = 12289
    gids.guardians = 14337

    return gids


# Global instance - will be initialized when content folder is known
TILESET_GIDS: Optional[TilesetGids] = None


# Tile remap tables loaded from analysis/tile_remap_*.json
# These map old monolithic tile indices to new reorganized tileset indices
TILE_REMAPS: Dict[str, Dict[int, int]] = {}


def load_tile_remaps() -> None:
    """Load tile remap tables from JSON files in tilesets/meta/."""
    global TILE_REMAPS
    tmx_dir = os.path.dirname(SCRIPT_DIR)  # tmx/scripts -> tmx
    meta_dir = os.path.join(tmx_dir, "tilesets", "meta")
    for category in ("solid", "platform", "hazard", "decoration"):
        remap_path = os.path.join(meta_dir, f"tile_remap_{category}.json")
        if os.path.exists(remap_path):
            with open(remap_path, encoding="utf-8") as f:
                data = json.load(f)
            TILE_REMAPS[category] = {int(k): v for k, v in data["old_to_new"].items()}


def old_tile_to_new_gid(old_index: int) -> int:
    """Convert old monolithic tile index (0-527) to new TMX GID for split tilesets.

    Old tile ranges (from tiles.png rows 0-32):
    - 0-159: Solid tiles (rows 0-9)     — remapped via tile_remap_solid.json
    - 160-223: Stairs tiles (rows 10-13) — identity mapping
    - 224-303: Platform tiles (rows 14-18) — remapped via tile_remap_platform.json
    - 304-335: Hazard tiles (rows 19-20)   — remapped via tile_remap_hazard.json
    - 336-399: Decoration tiles (rows 21-24) — remapped via tile_remap_decoration.json
    - 400-527: Conveyor tiles (rows 25-32, special layout conversion)

    Returns TMX GID for the appropriate split tileset.
    """
    if TILESET_GIDS is None:
        raise RuntimeError("TILESET_GIDS not initialized")

    if old_index == 0:
        # Tile 0 = empty/air
        return 0
    elif old_index < 160:
        # Solid tiles: 0-159 → tiles_solid (remapped)
        local = TILE_REMAPS.get("solid", {}).get(old_index, old_index)
        return TILESET_GIDS.tiles_solid + local
    elif old_index < 224:
        # Stairs tiles: 160-223 → tiles_stairs (identity)
        return TILESET_GIDS.tiles_stairs + (old_index - 160)
    elif old_index < 304:
        # Platform tiles: 224-303 → tiles_platform (remapped)
        old_local = old_index - 224
        local = TILE_REMAPS.get("platform", {}).get(old_local, old_local)
        return TILESET_GIDS.tiles_platform + local
    elif old_index < 336:
        # Hazard tiles: 304-335 → tiles_hazard (remapped)
        old_local = old_index - 304
        local = TILE_REMAPS.get("hazard", {}).get(old_local, old_local)
        return TILESET_GIDS.tiles_hazard + local
    elif old_index < 400:
        # Decoration tiles: 336-399 → tiles_decoration (remapped)
        old_local = old_index - 336
        local = TILE_REMAPS.get("decoration", {}).get(old_local, old_local)
        return TILESET_GIDS.tiles_decoration + local
    else:
        # Conveyor tiles: 400-527 → tiles_conveyor (layout conversion)
        row = old_index // 16  # 25-32
        col = old_index % 16   # 0-10 = conveyor type

        if col > 10:
            col = 0

        conveyor_type = col
        is_left_moving = (row % 2 == 1)  # Odd rows = left

        # New layout: row = conveyor_type, cols 0-7 = left, cols 8-15 = right
        new_local = conveyor_type * 16 + (0 if is_left_moving else 8)
        return TILESET_GIDS.tiles_conveyor + new_local


def load_guardian_names(content_folder: str) -> None:
    """
    Load guardian names from guardians.txt in the tilesets folder.

    The file contains 75 lines (one per tile in the guardians collection):
    - Lines 1-70: Normal guardian names (tiles 0-69)
    - Line 71: Lift (tile 70)
    - Lines 72-73: Arrow I, Arrow II (tiles 71-72)
    - Line 74: Periscope Tank (tile 73)
    - Line 75: Evil Head (tile 74)
    """
    global GUARDIAN_NAMES, PERISCOPE_TANK_NAME, EVIL_HEAD_NAME

    # Guardian names are in tmx/tilesets/guardians.txt
    tilesets_folder = os.path.join(os.path.dirname(content_folder), "tilesets")
    guardians_file = os.path.join(tilesets_folder, "guardians.txt")

    if os.path.exists(guardians_file):
        with open(guardians_file, 'r', encoding='utf-8') as f:
            GUARDIAN_NAMES = [line.strip() for line in f.readlines()]

        # Extract periscope tank and evil head names from lines 74-75 (tiles 73-74)
        if len(GUARDIAN_NAMES) > TILE_INDEX_PERISCOPE_TANK:
            PERISCOPE_TANK_NAME = GUARDIAN_NAMES[TILE_INDEX_PERISCOPE_TANK]
        if len(GUARDIAN_NAMES) > TILE_INDEX_EVIL_GIANT_HEAD:
            EVIL_HEAD_NAME = GUARDIAN_NAMES[TILE_INDEX_EVIL_GIANT_HEAD]


def get_guardian_name(gid: int) -> Optional[str]:
    """
    Get the name of a guardian from its GID.

    Returns None if no name is available.
    """
    if not TILESET_GIDS:
        return None

    # Calculate tile index within guardians collection
    index = gid - TILESET_GIDS.guardians

    # Check for oversized guardians (now in collection as tiles 73-74)
    if index == TILE_INDEX_PERISCOPE_TANK:
        return PERISCOPE_TANK_NAME
    elif index == TILE_INDEX_EVIL_GIANT_HEAD:
        return EVIL_HEAD_NAME
    elif 0 <= index < len(GUARDIAN_NAMES):
        return GUARDIAN_NAMES[index]
    return None


def get_guardian_dimensions(entity_type: int) -> tuple:
    """
    Get the width and height of a guardian sprite in pixels.

    Normal guardians are 16x16 pixels.
    Periscope tank (type 70) is 16x32.
    Evil giant head (type 71) is 32x32.

    For reverse conversion (tmx_to_dat):
      Use the object width/height from TMX to determine if it's an oversized guardian.
    """
    if entity_type == ENTITY_TYPE_EVIL_GIANT_HEAD:
        return (GUARDIAN_WIDTH_EVIL_HEAD, GUARDIAN_HEIGHT_OVERSIZED)
    elif entity_type == ENTITY_TYPE_PERISCOPE_TANK:
        return (GUARDIAN_WIDTH_NORMAL, GUARDIAN_HEIGHT_OVERSIZED)
    return (GUARDIAN_WIDTH_NORMAL, GUARDIAN_HEIGHT_NORMAL)


def get_guardian_height(entity_type: int) -> int:
    """
    Get the height of a guardian sprite in pixels.

    Normal guardians are 16 pixels tall.
    Oversized guardians (periscope tank, evil giant head) are 32 pixels tall.

    For reverse conversion (tmx_to_dat):
      When converting a vertical path back to dat format, subtract the guardian
      height from the path height to get the original patrol bounds.
    """
    if entity_type in (ENTITY_TYPE_PERISCOPE_TANK, ENTITY_TYPE_EVIL_GIANT_HEAD):
        return GUARDIAN_HEIGHT_OVERSIZED
    return GUARDIAN_HEIGHT_NORMAL


def entity_type_to_gid(entity_type: int) -> int:
    """
    Convert dat file entity_type to TMX GID.

    Most types map directly (GID = guardians_firstgid + type), but special entities
    are remapped:
    - Oversized guardians (70, 71) use tiles 73-74 in guardians collection
    - Lifts and arrows (72, 73, 74) use tiles 70-72 in guardians collection
    """
    if entity_type == ENTITY_TYPE_EVIL_GIANT_HEAD:
        return TILESET_GIDS.guardians + TILE_INDEX_EVIL_GIANT_HEAD
    elif entity_type == ENTITY_TYPE_PERISCOPE_TANK:
        return TILESET_GIDS.guardians + TILE_INDEX_PERISCOPE_TANK
    elif entity_type == ENTITY_TYPE_LIFT:
        return TILESET_GIDS.guardians + TILE_INDEX_LIFT
    elif entity_type == ENTITY_TYPE_ARROW_LEFT:
        return TILESET_GIDS.guardians + TILE_INDEX_ARROW_LEFT
    elif entity_type == ENTITY_TYPE_ARROW_RIGHT:
        return TILESET_GIDS.guardians + TILE_INDEX_ARROW_RIGHT
    else:
        return TILESET_GIDS.guardians + entity_type


class Room:
    """Represents a loaded room."""
    def __init__(self, room_id: int):
        self.room_id = room_id
        self.name = ""
        self.tiles: List[List[int]] = []
        self.exit_up: Optional[int] = None
        self.exit_right: Optional[int] = None
        self.exit_down: Optional[int] = None
        self.exit_left: Optional[int] = None
        self.has_rope: str = 'N'
        # Grid position (set during layout)
        self.grid_x: int = 0
        self.grid_y: int = 0


class Collectible:
    """Represents a collectible item."""
    def __init__(self, x: int, y: int, item_type: int):
        self.x = x
        self.y = y
        self.item_type = item_type


class Enemy:
    """Represents an enemy/guardian."""
    def __init__(self, spawn_x: int, spawn_y: int, entity_type: int,
                 patrol_x1: int, patrol_y1: int, patrol_x2: int, patrol_y2: int,
                 facing: int, speed: int, r: int, g: int, b: int, movement_type: int):
        self.spawn_x = spawn_x
        self.spawn_y = spawn_y
        self.entity_type = entity_type
        self.patrol_x1 = patrol_x1
        self.patrol_y1 = patrol_y1
        self.patrol_x2 = patrol_x2
        self.patrol_y2 = patrol_y2
        self.facing = facing
        self.speed = speed
        self.r = r
        self.g = g
        self.b = b
        self.movement_type = movement_type

    @property
    def is_arrow(self) -> bool:
        return self.entity_type in (73, 74)


def load_room(filepath: str, room_id: int) -> Optional[Room]:
    """Load a single room from a .dat file."""
    try:
        with open(filepath, 'rb') as f:
            data = f.read()
    except FileNotFoundError:
        return None

    if len(data) < 1064:
        print(f"Room file too short: {filepath} ({len(data)} bytes)")
        return None

    room = Room(room_id)

    # Parse tiles (offset 2-1025, 1024 bytes = 512 tiles × 2 bytes)
    for row in range(ROOM_HEIGHT):
        tile_row = []
        for col in range(ROOM_WIDTH):
            offset = 2 + (row * ROOM_WIDTH + col) * 2
            tile = struct.unpack('<H', data[offset:offset+2])[0]
            tile_row.append(tile)
        room.tiles.append(tile_row)

    # Parse connections (offset 1026-1029)
    room.exit_up = data[1026] if data[1026] > 0 else None
    room.exit_right = data[1027] if data[1027] > 0 else None
    room.exit_down = data[1028] if data[1028] > 0 else None
    room.exit_left = data[1029] if data[1029] > 0 else None

    # Parse room name (offset 1030-1061, 32 bytes)
    name_bytes = data[1030:1062]
    room.name = name_bytes.decode('latin-1').rstrip()

    # Parse rope flag (offset 1063)
    room.has_rope = chr(data[1063]) if data[1063] in (ord('N'), ord('Y')) else 'N'

    return room


def load_collectibles(filepath: str) -> List[Collectible]:
    """Load collectibles from a _pickups.dat file."""
    try:
        with open(filepath, 'rb') as f:
            data = f.read()
    except FileNotFoundError:
        return []

    if len(data) < 4:
        return []

    count = data[2] + 1
    items = []

    for i in range(count):
        offset = 4 + i * 5
        if offset + 5 > len(data):
            break

        x = struct.unpack('<H', data[offset:offset+2])[0] // EDITOR_SCALE
        y = struct.unpack('<H', data[offset+2:offset+4])[0] // EDITOR_SCALE
        item_type = data[offset+4]
        items.append(Collectible(x, y, item_type))

    return items


def load_enemies(filepath: str) -> List[Enemy]:
    """Load enemies from a _enemy.dat file."""
    try:
        with open(filepath, 'rb') as f:
            data = f.read()
    except FileNotFoundError:
        return []

    if len(data) < 4:
        return []

    count = data[2] + 1
    enemies = []

    for i in range(count):
        offset = 4 + i * 19
        if offset + 19 > len(data):
            break

        spawn_x = struct.unpack('<H', data[offset:offset+2])[0] // EDITOR_SCALE
        spawn_y = struct.unpack('<H', data[offset+2:offset+4])[0] // EDITOR_SCALE
        entity_type = data[offset+4]
        patrol_x1 = struct.unpack('<H', data[offset+5:offset+7])[0] // EDITOR_SCALE
        patrol_y1 = struct.unpack('<H', data[offset+7:offset+9])[0] // EDITOR_SCALE
        patrol_x2 = struct.unpack('<H', data[offset+9:offset+11])[0] // EDITOR_SCALE
        patrol_y2 = struct.unpack('<H', data[offset+11:offset+13])[0] // EDITOR_SCALE
        facing = data[offset+13]
        speed = data[offset+14]
        r = data[offset+15]
        g = data[offset+16]
        b = data[offset+17]
        movement_type = data[offset+18]

        enemies.append(Enemy(spawn_x, spawn_y, entity_type,
                            patrol_x1, patrol_y1, patrol_x2, patrol_y2,
                            facing, speed, r, g, b, movement_type))

    return enemies


def _find_regions(rooms: Dict[int, Room], visited: set, room_chunks: Dict[int, int]) -> List[set]:
    """
    Find connected regions where rooms are both physically adjacent AND game-connected.
    Only considers rooms in chunk 0.
    Returns list of regions (each region is a set of room IDs).
    """
    chunk0_rooms = {rid for rid in visited if room_chunks.get(rid, 0) == 0}

    # Build adjacency for region finding
    # Two rooms are in same region if: physically adjacent AND game-connected
    def are_physically_adjacent(r1: Room, r2: Room) -> bool:
        dx = abs(r1.grid_x - r2.grid_x)
        dy = abs(r1.grid_y - r2.grid_y)
        return (dx == 1 and dy == 0) or (dx == 0 and dy == 1)

    def are_game_connected(r1: Room, r2: Room) -> bool:
        r1_connects_to_r2 = (
            r1.exit_up == r2.room_id or
            r1.exit_down == r2.room_id or
            r1.exit_left == r2.room_id or
            r1.exit_right == r2.room_id
        )
        r2_connects_to_r1 = (
            r2.exit_up == r1.room_id or
            r2.exit_down == r1.room_id or
            r2.exit_left == r1.room_id or
            r2.exit_right == r1.room_id
        )
        return r1_connects_to_r2 or r2_connects_to_r1

    # Union-Find for regions
    parent = {rid: rid for rid in chunk0_rooms}

    def find(x):
        if parent[x] != x:
            parent[x] = find(parent[x])
        return parent[x]

    def union(x, y):
        px, py = find(x), find(y)
        if px != py:
            parent[px] = py

    # Union rooms that are both physically adjacent and game-connected
    chunk0_list = list(chunk0_rooms)
    for i, rid1 in enumerate(chunk0_list):
        for rid2 in chunk0_list[i+1:]:
            r1, r2 = rooms[rid1], rooms[rid2]
            if are_physically_adjacent(r1, r2) and are_game_connected(r1, r2):
                union(rid1, rid2)

    # Group by root
    region_map: Dict[int, set] = {}
    for rid in chunk0_rooms:
        root = find(rid)
        if root not in region_map:
            region_map[root] = set()
        region_map[root].add(rid)

    return list(region_map.values())


def _count_reciprocal_connections(r1: Room, r2: Room) -> int:
    """
    Count how many reciprocal connection pairs exist between two rooms.
    A reciprocal connection is when A -> B in one direction AND B -> A in the opposite.
    """
    count = 0
    # Up-Down pair: r1 goes up to r2, r2 goes down to r1
    if r1.exit_up == r2.room_id and r2.exit_down == r1.room_id:
        count += 1
    # Down-Up pair: r1 goes down to r2, r2 goes up to r1
    if r1.exit_down == r2.room_id and r2.exit_up == r1.room_id:
        count += 1
    # Left-Right pair: r1 goes left to r2, r2 goes right to r1
    if r1.exit_left == r2.room_id and r2.exit_right == r1.room_id:
        count += 1
    # Right-Left pair: r1 goes right to r2, r2 goes left to r1
    if r1.exit_right == r2.room_id and r2.exit_left == r1.room_id:
        count += 1
    return count


def _assign_chunks_by_connectivity(rooms: Dict[int, Room], visited: set,
                                    position_to_rooms: Dict[Tuple[int, int], List[int]]) -> Dict[int, int]:
    """
    Assign chunk numbers to rooms, keeping game-connected rooms in the same chunk.

    The constraint is: rooms at the same grid position MUST be in different chunks.
    The goal is: game-connected rooms should be in the SAME chunk when possible.
    """
    room_chunks: Dict[int, int] = {}

    # Find positions with overlaps (need chunk assignment)
    overlap_positions = {pos for pos, rlist in position_to_rooms.items() if len(rlist) > 1}

    if not overlap_positions:
        # No overlaps - everything in chunk 0
        for rid in visited:
            room_chunks[rid] = 0
        return room_chunks

    # Find all rooms involved in overlaps
    overlap_rooms = set()
    for pos in overlap_positions:
        overlap_rooms.update(position_to_rooms[pos])

    # Build game connection graph for overlap rooms
    # connection[rid] = set of room IDs that rid connects to (in either direction)
    connections: Dict[int, set] = {rid: set() for rid in overlap_rooms}
    for rid in overlap_rooms:
        room = rooms[rid]
        for exit_id in [room.exit_up, room.exit_down, room.exit_left, room.exit_right]:
            if exit_id and exit_id in overlap_rooms:
                connections[rid].add(exit_id)
                connections[exit_id].add(rid)

    # Use Union-Find to group connected rooms
    parent = {rid: rid for rid in overlap_rooms}

    def find(x):
        if parent[x] != x:
            parent[x] = find(parent[x])
        return parent[x]

    def union(x, y):
        px, py = find(x), find(y)
        if px != py:
            # Prefer lower room ID as root
            if px < py:
                parent[py] = px
            else:
                parent[px] = py

    # Union game-connected rooms, but NOT if they're at the same position
    # (rooms at the same position MUST be in different chunks)
    for rid, connected in connections.items():
        rid_pos = (rooms[rid].grid_x, rooms[rid].grid_y)
        for cid in connected:
            cid_pos = (rooms[cid].grid_x, rooms[cid].grid_y)
            if rid_pos != cid_pos:
                union(rid, cid)

    # Group rooms by their connected component
    component_rooms: Dict[int, List[int]] = {}
    for rid in overlap_rooms:
        root = find(rid)
        if root not in component_rooms:
            component_rooms[root] = []
        component_rooms[root].append(rid)

    # Calculate total reciprocal connections for each component
    def component_reciprocal_count(component: List[int]) -> int:
        total = 0
        for i, rid1 in enumerate(component):
            for rid2 in component[i+1:]:
                total += _count_reciprocal_connections(rooms[rid1], rooms[rid2])
        return total

    # Sort components by: reciprocal count (higher first), then min room ID (lower first)
    sorted_components = sorted(component_rooms.values(),
                               key=lambda c: (-component_reciprocal_count(c), min(c)))

    # Track which chunks are used at each position
    position_chunks_used: Dict[Tuple[int, int], set] = {pos: set() for pos in overlap_positions}

    # Assign chunks: process components in order, but handle internal overlaps
    # A component may have multiple rooms at the same position (transitively connected)
    for component in sorted_components:
        # Sort rooms within component by room ID (lower gets priority for chunk 0)
        sorted_rooms = sorted(component)

        for rid in sorted_rooms:
            pos = (rooms[rid].grid_x, rooms[rid].grid_y)

            # Find the lowest chunk available at this position
            chunk = 0
            while chunk in position_chunks_used.get(pos, set()):
                chunk += 1

            room_chunks[rid] = chunk
            if pos in position_chunks_used:
                position_chunks_used[pos].add(chunk)

    # Assign chunk 0 to all non-overlap rooms
    for rid in visited:
        if rid not in room_chunks:
            room_chunks[rid] = 0

    return room_chunks


def _are_rooms_connected(r1: Room, r2: Room) -> bool:
    """Check if two rooms have a direct game connection (either direction)."""
    return (
        r1.exit_up == r2.room_id or r1.exit_down == r2.room_id or
        r1.exit_left == r2.room_id or r1.exit_right == r2.room_id or
        r2.exit_up == r1.room_id or r2.exit_down == r1.room_id or
        r2.exit_left == r1.room_id or r2.exit_right == r1.room_id
    )


def _are_rooms_correctly_adjacent(r1: Room, r2: Room) -> bool:
    """
    Check if two physically adjacent rooms can be placed next to each other
    without creating a bad placement.

    A bad placement occurs when a room has an exit in a direction but
    a DIFFERENT room is physically adjacent in that direction.

    Returns True only if NEITHER room has a conflicting exit:
    - r2 is above r1: r1.exit_up must be r2 or None, AND r2.exit_down must be r1 or None
    - etc for other directions
    """
    dx = r2.grid_x - r1.grid_x
    dy = r2.grid_y - r1.grid_y

    if dx == 0 and dy == -1:  # r2 is above r1
        # r1's up exit must not conflict (either points to r2 or is None)
        # r2's down exit must not conflict (either points to r1 or is None)
        r1_ok = r1.exit_up is None or r1.exit_up == r2.room_id
        r2_ok = r2.exit_down is None or r2.exit_down == r1.room_id
        return r1_ok and r2_ok
    elif dx == 0 and dy == 1:  # r2 is below r1
        r1_ok = r1.exit_down is None or r1.exit_down == r2.room_id
        r2_ok = r2.exit_up is None or r2.exit_up == r1.room_id
        return r1_ok and r2_ok
    elif dx == -1 and dy == 0:  # r2 is left of r1
        r1_ok = r1.exit_left is None or r1.exit_left == r2.room_id
        r2_ok = r2.exit_right is None or r2.exit_right == r1.room_id
        return r1_ok and r2_ok
    elif dx == 1 and dy == 0:  # r2 is right of r1
        r1_ok = r1.exit_right is None or r1.exit_right == r2.room_id
        r2_ok = r2.exit_left is None or r2.exit_left == r1.room_id
        return r1_ok and r2_ok

    return False  # Not adjacent


def _find_bad_adjacencies(rooms: Dict[int, Room], visited: set, room_chunks: Dict[int, int]) -> List[Tuple[int, int]]:
    """
    Find pairs of rooms that are physically adjacent but not game-connected.
    Only considers rooms in the same chunk.
    """
    bad_pairs = []
    visited_list = list(visited)

    for i, rid1 in enumerate(visited_list):
        r1 = rooms[rid1]
        chunk1 = room_chunks.get(rid1, 0)

        for rid2 in visited_list[i+1:]:
            r2 = rooms[rid2]
            chunk2 = room_chunks.get(rid2, 0)

            # Only check rooms in the same chunk
            if chunk1 != chunk2:
                continue

            # Check if physically adjacent
            dx = abs(r1.grid_x - r2.grid_x)
            dy = abs(r1.grid_y - r2.grid_y)
            is_adjacent = (dx == 1 and dy == 0) or (dx == 0 and dy == 1)

            if is_adjacent and not _are_rooms_connected(r1, r2):
                bad_pairs.append((rid1, rid2))

    return bad_pairs


def _get_adjacency_score(r1: Room, r2: Room) -> int:
    """
    Calculate adjacency score between two physically adjacent rooms.
    - 2 points: bidirectional connection (both rooms exit to each other in correct direction)
    - 1 point: unidirectional connection (one room exits to the other)
    - 0 points: no connection (neither room exits to the other)
    """
    dx = r2.grid_x - r1.grid_x
    dy = r2.grid_y - r1.grid_y

    # Determine which exits to check based on relative position
    if dx == 0 and dy == -1:  # r2 is above r1
        r1_connects = r1.exit_up == r2.room_id
        r2_connects = r2.exit_down == r1.room_id
    elif dx == 0 and dy == 1:  # r2 is below r1
        r1_connects = r1.exit_down == r2.room_id
        r2_connects = r2.exit_up == r1.room_id
    elif dx == -1 and dy == 0:  # r2 is left of r1
        r1_connects = r1.exit_left == r2.room_id
        r2_connects = r2.exit_right == r1.room_id
    elif dx == 1 and dy == 0:  # r2 is right of r1
        r1_connects = r1.exit_right == r2.room_id
        r2_connects = r2.exit_left == r1.room_id
    else:
        return 0  # Not adjacent

    if r1_connects and r2_connects:
        return 2  # Bidirectional
    elif r1_connects or r2_connects:
        return 1  # Unidirectional
    else:
        return 0  # No connection


def _separate_unconnected_clusters(rooms: Dict[int, Room], visited: set, room_chunks: Dict[int, int]):
    """
    Identify clusters of rooms that are physically adjacent AND game-connected.
    If different clusters are physically adjacent (bad adjacency), move one cluster
    to a different chunk. Uses adjacency scoring to decide which rooms to move:
    - 2 points: bidirectional connection
    - 1 point: unidirectional connection
    - 0 points: no connection (definitely move)
    Higher total score wins contention.
    """
    # Process each chunk separately, starting with chunk 0
    max_chunk = max(room_chunks.values()) if room_chunks else 0
    next_chunk = max_chunk + 1

    chunks_to_process = list(range(max_chunk + 1))
    processed_states = set()  # Track (chunk, frozenset of rooms) to avoid infinite loops

    while chunks_to_process:
        current_chunk = chunks_to_process.pop(0)
        chunk_rooms = [rid for rid in visited if room_chunks.get(rid, 0) == current_chunk]

        if len(chunk_rooms) < 2:
            continue

        # Create a state key to detect if we've already processed this exact configuration
        state_key = (current_chunk, frozenset(chunk_rooms))
        if state_key in processed_states:
            continue
        processed_states.add(state_key)

        # Build clusters using Union-Find based on physical adjacency + connection score
        parent = {rid: rid for rid in chunk_rooms}

        def find(x):
            if parent[x] != x:
                parent[x] = find(parent[x])
            return parent[x]

        def union(x, y):
            px, py = find(x), find(y)
            if px != py:
                if px < py:
                    parent[py] = px
                else:
                    parent[px] = py

        # Build position map for this chunk
        pos_to_room = {}
        for rid in chunk_rooms:
            pos = (rooms[rid].grid_x, rooms[rid].grid_y)
            pos_to_room[pos] = rid

        # Union rooms that are physically adjacent AND have any connection (score > 0)
        for i, rid1 in enumerate(chunk_rooms):
            r1 = rooms[rid1]
            for rid2 in chunk_rooms[i+1:]:
                r2 = rooms[rid2]
                dx = abs(r1.grid_x - r2.grid_x)
                dy = abs(r1.grid_y - r2.grid_y)
                is_adjacent = (dx == 1 and dy == 0) or (dx == 0 and dy == 1)

                if is_adjacent and _get_adjacency_score(r1, r2) > 0:
                    union(rid1, rid2)

        # Group rooms by cluster
        clusters: Dict[int, set] = {}
        for rid in chunk_rooms:
            root = find(rid)
            if root not in clusters:
                clusters[root] = set()
            clusters[root].add(rid)

        if len(clusters) < 2:
            continue  # Only one cluster in this chunk, no bad adjacencies possible

        # Find bad adjacencies (score = 0) between clusters
        cluster_bad_adjacencies: Dict[Tuple[int, int], List[Tuple[int, int]]] = {}
        for rid1 in chunk_rooms:
            r1 = rooms[rid1]
            c1 = find(rid1)
            for rid2 in chunk_rooms:
                if rid1 >= rid2:
                    continue
                r2 = rooms[rid2]
                c2 = find(rid2)
                if c1 == c2:
                    continue  # Same cluster

                dx = abs(r1.grid_x - r2.grid_x)
                dy = abs(r1.grid_y - r2.grid_y)
                is_adjacent = (dx == 1 and dy == 0) or (dx == 0 and dy == 1)

                if is_adjacent and _get_adjacency_score(r1, r2) == 0:
                    # Bad adjacency between clusters (no connection)
                    key = (min(c1, c2), max(c1, c2))
                    if key not in cluster_bad_adjacencies:
                        cluster_bad_adjacencies[key] = []
                    cluster_bad_adjacencies[key].append((rid1, rid2))

        if not cluster_bad_adjacencies:
            continue  # No bad adjacencies in this chunk

        # Calculate total adjacency score for each cluster
        def cluster_score(cluster_rooms_set: set) -> int:
            total = 0
            for rid in cluster_rooms_set:
                r = rooms[rid]
                # Check all 4 adjacent positions
                for dx, dy in [(0, -1), (0, 1), (-1, 0), (1, 0)]:
                    neighbor_pos = (r.grid_x + dx, r.grid_y + dy)
                    neighbor_rid = pos_to_room.get(neighbor_pos)
                    if neighbor_rid is not None and neighbor_rid in cluster_rooms_set:
                        # Only count each pair once (when rid < neighbor_rid)
                        if rid < neighbor_rid:
                            total += _get_adjacency_score(r, rooms[neighbor_rid])
            return total

        # Sort clusters by: total adjacency score (highest first), then size (largest first), then min room ID
        sorted_clusters = sorted(
            clusters.items(),
            key=lambda x: (-cluster_score(x[1]), -len(x[1]), min(x[1]))
        )

        # Keep removing clusters with bad adjacencies until none remain
        # Highest score cluster stays, lower score clusters move
        moved_any = True
        while moved_any:
            moved_any = False

            # Find a cluster to move: lowest score cluster that has bad adjacency with higher score cluster
            for i in range(len(sorted_clusters) - 1, 0, -1):  # From lowest score to second-highest
                cluster_id, cluster_rooms_set = sorted_clusters[i]

                # Check if this cluster has bad adjacencies with any higher-score cluster
                has_bad = any(
                    (min(cluster_id, other_id), max(cluster_id, other_id)) in cluster_bad_adjacencies
                    for other_id, _ in sorted_clusters[:i]
                )

                if has_bad:
                    # Move this cluster to a new chunk
                    for rid in cluster_rooms_set:
                        room_chunks[rid] = next_chunk

                    # Queue the new chunk for processing
                    if next_chunk not in chunks_to_process:
                        chunks_to_process.append(next_chunk)
                    next_chunk += 1

                    # Remove from sorted_clusters and restart
                    sorted_clusters = sorted_clusters[:i] + sorted_clusters[i+1:]
                    moved_any = True
                    break


def _isolate_impossible_rooms(rooms: Dict[int, Room], visited: set, room_chunks: Dict[int, int]):
    """
    Find and isolate rooms with impossible exit configurations.

    These are rooms where exits in opposite directions point to the same room,
    making it physically impossible to place correctly (e.g., Left->1, Right->1).
    """
    impossible_rooms = set()

    for rid in visited:
        room = rooms[rid]

        # Check for opposite directions pointing to same room
        if room.exit_left is not None and room.exit_left == room.exit_right:
            impossible_rooms.add(rid)
        if room.exit_up is not None and room.exit_up == room.exit_down:
            impossible_rooms.add(rid)

    if impossible_rooms:
        # Move each impossible room to its own chunk
        max_chunk = max(room_chunks.values()) if room_chunks else -1
        for rid in impossible_rooms:
            max_chunk += 1
            rooms[rid].grid_x = 0
            rooms[rid].grid_y = 0
            room_chunks[rid] = max_chunk


def _optimize_chunk_placement(rooms: Dict[int, Room], visited: set, room_chunks: Dict[int, int]):
    """
    Post-processing: optimize room placement across all chunks.

    For each chunk:
    1. Find rooms with exits to rooms in other chunks (dangling connections)
    2. Find rooms involved in bad placements (exit points to X but Y is adjacent)
    3. Try to pull connected rooms from other chunks if they fit
    4. Try to move rooms with bad placements to other chunks where they fit

    Repeat until no changes across all chunks.
    """
    # First, isolate rooms with impossible exit configurations
    _isolate_impossible_rooms(rooms, visited, room_chunks)

    max_global_iterations = 100
    global_iteration = 0

    while global_iteration < max_global_iterations:
        global_iteration += 1
        changed_any = False

        # Get all chunks
        all_chunks = sorted(set(room_chunks.values()))

        for current_chunk in all_chunks:
            # Build position map for this chunk
            chunk_positions: Dict[Tuple[int, int], int] = {}
            for rid in visited:
                if room_chunks.get(rid, 0) == current_chunk:
                    pos = (rooms[rid].grid_x, rooms[rid].grid_y)
                    chunk_positions[pos] = rid

            # Find rooms with bad placements in this chunk
            # A room is a bad placement ONLY if ALL its adjacent rooms have score 0
            # (i.e., it has no connections whatsoever to any of its neighbors)
            bad_placement_rooms = set()
            for rid in visited:
                if room_chunks.get(rid, 0) != current_chunk:
                    continue

                room = rooms[rid]
                x, y = room.grid_x, room.grid_y

                # Check all adjacent positions
                has_any_connection = False
                has_any_neighbor = False
                for dx, dy in [(0, -1), (0, 1), (-1, 0), (1, 0)]:
                    adjacent_pos = (x + dx, y + dy)
                    adjacent_rid = chunk_positions.get(adjacent_pos)
                    if adjacent_rid is not None:
                        has_any_neighbor = True
                        if _get_adjacency_score(room, rooms[adjacent_rid]) > 0:
                            has_any_connection = True
                            break

                # Only mark as bad if has neighbors but NO connections to any of them
                if has_any_neighbor and not has_any_connection:
                    bad_placement_rooms.add(rid)

            # Find dangling connections: rooms with exits to other chunks
            dangling_connections = []
            for rid in visited:
                if room_chunks.get(rid, 0) != current_chunk:
                    continue

                room = rooms[rid]
                for exit_dir, dx, dy in [('up', 0, -1), ('down', 0, 1), ('left', -1, 0), ('right', 1, 0)]:
                    target_id = getattr(room, f'exit_{exit_dir}')
                    if target_id is None or target_id not in rooms:
                        continue

                    target_chunk = room_chunks.get(target_id, 0)
                    if target_chunk == current_chunk:
                        continue

                    expected_x = room.grid_x + dx
                    expected_y = room.grid_y + dy
                    dangling_connections.append((rid, target_id, expected_x, expected_y, exit_dir, target_chunk))

            # Try to pull rooms from other chunks into this chunk
            # Only pull from HIGHER chunk numbers to LOWER (prefer keeping rooms in chunk 0)
            for source_rid, target_rid, expected_x, expected_y, exit_dir, target_chunk in dangling_connections:
                if room_chunks.get(target_rid, 0) == current_chunk:
                    continue

                # Only pull rooms from higher-numbered chunks into lower-numbered chunks
                if target_chunk < current_chunk:
                    continue

                expected_pos = (expected_x, expected_y)

                if expected_pos in chunk_positions:
                    continue

                target_room = rooms[target_rid]
                old_x, old_y = target_room.grid_x, target_room.grid_y
                target_room.grid_x = expected_x
                target_room.grid_y = expected_y

                has_bad_adjacency = False
                for check_dx, check_dy in [(0, -1), (0, 1), (-1, 0), (1, 0)]:
                    neighbor_pos = (expected_x + check_dx, expected_y + check_dy)
                    neighbor_rid = chunk_positions.get(neighbor_pos)

                    if neighbor_rid is None:
                        continue

                    if not _are_rooms_correctly_adjacent(target_room, rooms[neighbor_rid]):
                        has_bad_adjacency = True
                        break

                if has_bad_adjacency:
                    target_room.grid_x = old_x
                    target_room.grid_y = old_y
                    continue

                room_chunks[target_rid] = current_chunk
                chunk_positions[expected_pos] = target_rid
                changed_any = True
                break

            if changed_any:
                break

            # Try to move rooms with bad placements to other chunks
            for bad_rid in sorted(bad_placement_rooms):
                bad_room = rooms[bad_rid]

                # Try each other chunk where this room has a connection
                for other_chunk in all_chunks:
                    if other_chunk == current_chunk:
                        continue

                    # Build position map for other chunk
                    other_positions: Dict[Tuple[int, int], int] = {}
                    for rid in visited:
                        if room_chunks.get(rid, 0) == other_chunk:
                            pos = (rooms[rid].grid_x, rooms[rid].grid_y)
                            other_positions[pos] = rid

                    # Check if this room has a connection to a room in the other chunk
                    for exit_dir, dx, dy in [('up', 0, -1), ('down', 0, 1), ('left', -1, 0), ('right', 1, 0)]:
                        target_id = getattr(bad_room, f'exit_{exit_dir}')
                        if target_id is None or target_id not in rooms:
                            continue

                        if room_chunks.get(target_id, 0) != other_chunk:
                            continue

                        target_room = rooms[target_id]
                        # Calculate where bad_room should be relative to target
                        opposite_dx = -dx
                        opposite_dy = -dy
                        expected_x = target_room.grid_x + opposite_dx
                        expected_y = target_room.grid_y + opposite_dy
                        expected_pos = (expected_x, expected_y)

                        if expected_pos in other_positions:
                            continue

                        old_x, old_y = bad_room.grid_x, bad_room.grid_y
                        bad_room.grid_x = expected_x
                        bad_room.grid_y = expected_y

                        has_bad = False
                        for check_dx, check_dy in [(0, -1), (0, 1), (-1, 0), (1, 0)]:
                            neighbor_pos = (expected_x + check_dx, expected_y + check_dy)
                            neighbor_rid = other_positions.get(neighbor_pos)

                            if neighbor_rid is None:
                                continue

                            if not _are_rooms_correctly_adjacent(bad_room, rooms[neighbor_rid]):
                                has_bad = True
                                break

                        if has_bad:
                            bad_room.grid_x = old_x
                            bad_room.grid_y = old_y
                            continue

                        room_chunks[bad_rid] = other_chunk
                        changed_any = True
                        break

                    if changed_any:
                        break

                if changed_any:
                    break

                # If couldn't move to existing chunk, try creating a new chunk
                # Move this room and its connected neighbors that also have bad placements
                if not changed_any and bad_rid in bad_placement_rooms:
                    # Create a new chunk
                    new_chunk = max(all_chunks) + 1

                    # Move this room to the new chunk at position (0, 0)
                    bad_room.grid_x = 0
                    bad_room.grid_y = 0
                    room_chunks[bad_rid] = new_chunk
                    changed_any = True
                    break

            if changed_any:
                break

        if not changed_any:
            break


def _split_disconnected_chunks(rooms: Dict[int, Room], visited: set, room_chunks: Dict[int, int]):
    """
    Split chunks that contain disconnected room sets into separate chunks.
    If a chunk has n disconnected physical groups, split into n chunks.
    """
    max_chunk = max(room_chunks.values()) if room_chunks else 0
    next_chunk = max_chunk + 1

    # Process each chunk (except we'll skip chunks we create during iteration)
    chunks_to_check = sorted(set(room_chunks.values()))

    for current_chunk in chunks_to_check:
        chunk_rooms = [rid for rid in visited if room_chunks.get(rid, 0) == current_chunk]

        if len(chunk_rooms) < 2:
            continue

        # Find physically connected components using Union-Find
        parent = {rid: rid for rid in chunk_rooms}

        def find(x):
            if parent[x] != x:
                parent[x] = find(parent[x])
            return parent[x]

        def union(x, y):
            px, py = find(x), find(y)
            if px != py:
                if px < py:
                    parent[py] = px
                else:
                    parent[px] = py

        # Union rooms that are physically adjacent
        for i, rid1 in enumerate(chunk_rooms):
            r1 = rooms[rid1]
            for rid2 in chunk_rooms[i+1:]:
                r2 = rooms[rid2]
                dx = abs(r1.grid_x - r2.grid_x)
                dy = abs(r1.grid_y - r2.grid_y)
                is_adjacent = (dx == 1 and dy == 0) or (dx == 0 and dy == 1)
                if is_adjacent:
                    union(rid1, rid2)

        # Group rooms by their component
        components: Dict[int, List[int]] = {}
        for rid in chunk_rooms:
            root = find(rid)
            if root not in components:
                components[root] = []
            components[root].append(rid)

        if len(components) <= 1:
            continue  # Only one connected component, no split needed

        # Sort components by size (largest stays in current chunk)
        sorted_components = sorted(components.values(), key=lambda c: -len(c))

        # Keep the largest component in the current chunk, move others to new chunks
        for component in sorted_components[1:]:  # Skip the largest
            for rid in component:
                room_chunks[rid] = next_chunk
            next_chunk += 1


def _optimize_region_placement(rooms: Dict[int, Room], visited: set, room_chunks: Dict[int, int]):
    """
    Optimize placement by moving small disconnected regions to be adjacent
    to rooms they connect to, if space is available.
    """
    max_iterations = 100  # Prevent infinite loops
    iteration = 0

    while iteration < max_iterations:
        iteration += 1
        moved = False

        # Find current regions
        regions = _find_regions(rooms, visited, room_chunks)

        # Sort by size (largest first - big regions are anchors, small ones move to fit)
        regions.sort(key=len, reverse=True)

        # Build current occupied positions (chunk 0 only)
        occupied = set()
        for rid in visited:
            if room_chunks.get(rid, 0) == 0:
                occupied.add((rooms[rid].grid_x, rooms[rid].grid_y))

        # Try to move each small region
        for region in regions:
            if len(region) >= len(visited) // 2:
                # Don't try to move large regions
                continue

            # Find broken connections: game connections to rooms outside this region
            # where the rooms are NOT physically adjacent
            broken_connections = []
            for rid in region:
                room = rooms[rid]
                for exit_dir, dx, dy in [('up', 0, -1), ('down', 0, 1), ('left', -1, 0), ('right', 1, 0)]:
                    connected_id = getattr(room, f'exit_{exit_dir}')
                    if connected_id is None or connected_id not in visited:
                        continue
                    if connected_id in region:
                        continue  # Same region
                    if room_chunks.get(connected_id, 0) != 0:
                        continue  # Not in chunk 0

                    # Check if physically adjacent
                    connected_room = rooms[connected_id]
                    expected_x = room.grid_x + dx
                    expected_y = room.grid_y + dy
                    if connected_room.grid_x != expected_x or connected_room.grid_y != expected_y:
                        # Broken connection - record the target position
                        broken_connections.append((rid, connected_id, dx, dy))

            if not broken_connections:
                continue

            # Sort broken connections by:
            # 1. Reciprocal connection count (higher = better, so negate)
            # 2. Room ID difference (lower = better)
            broken_connections.sort(key=lambda c: (
                -_count_reciprocal_connections(rooms[c[0]], rooms[c[1]]),
                abs(c[0] - c[1])
            ))

            # Try each broken connection
            for source_rid, target_rid, dx, dy in broken_connections:
                source_room = rooms[source_rid]
                target_room = rooms[target_rid]

                # Calculate where the region needs to move so source is adjacent to target
                # Target is at (target_room.grid_x, target_room.grid_y)
                # Source should be at (target_room.grid_x - dx, target_room.grid_y - dy)
                # Region offset = new_source_pos - current_source_pos
                new_source_x = target_room.grid_x - dx
                new_source_y = target_room.grid_y - dy
                offset_x = new_source_x - source_room.grid_x
                offset_y = new_source_y - source_room.grid_y

                # Check if all new positions are free
                can_move = True
                new_positions = []
                for rid in region:
                    new_x = rooms[rid].grid_x + offset_x
                    new_y = rooms[rid].grid_y + offset_y
                    new_pos = (new_x, new_y)
                    if new_pos in occupied and new_pos not in {(rooms[r].grid_x, rooms[r].grid_y) for r in region}:
                        can_move = False
                        break
                    new_positions.append((rid, new_x, new_y))

                if can_move:
                    # Move the region
                    for rid, new_x, new_y in new_positions:
                        old_pos = (rooms[rid].grid_x, rooms[rid].grid_y)
                        occupied.discard(old_pos)
                        rooms[rid].grid_x = new_x
                        rooms[rid].grid_y = new_y
                        occupied.add((new_x, new_y))
                    moved = True
                    break  # Restart with updated regions

            if moved:
                break

        if not moved:
            break  # No more moves possible


def build_room_layout(rooms: Dict[int, Room], start_room_id: int = 1) -> Tuple[set, int, int, int, Dict[int, int]]:
    """
    Build a grid layout from room connections using BFS.
    Handles non-Euclidean connections by partitioning into chunks.
    Returns (visited_rooms, grid_width, grid_height, connected_height, room_chunks).
    connected_height is the height of just the connected component (for chunk offset calc).
    """
    if start_room_id not in rooms:
        # Find first available room
        start_room_id = min(rooms.keys()) if rooms else 1
    # Track which positions are occupied
    position_to_room: Dict[Tuple[int, int], int] = {}

    # BFS to assign grid positions
    visited = set()
    queue = deque()

    rooms[start_room_id].grid_x = 0
    rooms[start_room_id].grid_y = 0
    position_to_room[(0, 0)] = start_room_id
    queue.append(start_room_id)
    visited.add(start_room_id)

    while queue:
        room_id = queue.popleft()
        room = rooms[room_id]
        x, y = room.grid_x, room.grid_y

        # Check all connections
        connections = [
            (room.exit_up, x, y - 1),
            (room.exit_down, x, y + 1),
            (room.exit_left, x - 1, y),
            (room.exit_right, x + 1, y),
        ]

        for next_id, nx, ny in connections:
            if next_id is None or next_id not in rooms:
                continue

            target_pos = (nx, ny)

            if next_id not in visited:
                # Room not yet placed - place at target position
                # (even if occupied, we'll handle overlaps with chunking)
                rooms[next_id].grid_x = nx
                rooms[next_id].grid_y = ny
                visited.add(next_id)
                queue.append(next_id)
            # If room is already placed, don't move it - non-Euclidean connection

    # Place any rooms that haven't been positioned yet (conflicts from first pass)
    for room_id in visited:
        room = rooms[room_id]
        pos = (room.grid_x, room.grid_y)
        if pos not in position_to_room:
            # Room needs a position - find a free spot
            # This shouldn't happen often, but handle it
            position_to_room[pos] = room_id

    # Normalize coordinates (shift so min is 0)
    if position_to_room:
        min_x = min(pos[0] for pos in position_to_room.keys())
        min_y = min(pos[1] for pos in position_to_room.keys())
        max_x = max(pos[0] for pos in position_to_room.keys())
        max_y = max(pos[1] for pos in position_to_room.keys())
    else:
        min_x, min_y, max_x, max_y = 0, 0, 0, 0

    for room in rooms.values():
        if room.room_id in visited:
            room.grid_x -= min_x
            room.grid_y -= min_y

    grid_width = max_x - min_x
    grid_height = max_y - min_y
    connected_height = grid_height  # Save for chunk offset calculation

    # Detect overlapping rooms and assign to chunks
    # Group rooms by position (rebuild after normalization)
    position_to_rooms: Dict[Tuple[int, int], List[int]] = {}
    for room in rooms.values():
        if room.room_id in visited:
            pos = (room.grid_x, room.grid_y)
            if pos not in position_to_rooms:
                position_to_rooms[pos] = []
            position_to_rooms[pos].append(room.room_id)

    # Count max overlap (determines number of chunks needed)
    max_overlap = max(len(room_list) for room_list in position_to_rooms.values()) if position_to_rooms else 1

    # Assign chunk numbers keeping game-connected rooms together
    room_chunks = _assign_chunks_by_connectivity(rooms, visited, position_to_rooms)

    if max_overlap > 1:
        num_chunks = max(room_chunks.values()) + 1 if room_chunks else 1
        print(f"  Non-Euclidean map detected: {num_chunks} chunks needed")

    # Post-processing: optimize region placement
    # Move small disconnected regions to be adjacent to rooms they connect to
    _optimize_region_placement(rooms, visited, room_chunks)

    # Rebuild position_to_rooms after optimization
    position_to_rooms = {}
    for room in rooms.values():
        if room.room_id in visited:
            pos = (room.grid_x, room.grid_y)
            if pos not in position_to_rooms:
                position_to_rooms[pos] = []
            position_to_rooms[pos].append(room.room_id)

    # Recalculate grid dimensions after optimization
    if visited:
        min_x = min(rooms[rid].grid_x for rid in visited)
        min_y = min(rooms[rid].grid_y for rid in visited)
        max_x = max(rooms[rid].grid_x for rid in visited)
        max_y = max(rooms[rid].grid_y for rid in visited)
        # Re-normalize
        for room in rooms.values():
            if room.room_id in visited:
                room.grid_x -= min_x
                room.grid_y -= min_y
        grid_width = max_x - min_x
        grid_height = max_y - min_y
        connected_height = grid_height

    # Recalculate chunks after optimization (keeping game-connected rooms together)
    position_to_rooms = {}
    for room in rooms.values():
        if room.room_id in visited:
            pos = (room.grid_x, room.grid_y)
            if pos not in position_to_rooms:
                position_to_rooms[pos] = []
            position_to_rooms[pos].append(room.room_id)

    max_overlap = max(len(room_list) for room_list in position_to_rooms.values()) if position_to_rooms else 1
    room_chunks = _assign_chunks_by_connectivity(rooms, visited, position_to_rooms)

    # Separate clusters that are physically adjacent but not game-connected
    # This must be AFTER all chunk recalculations to ensure it's not undone
    _separate_unconnected_clusters(rooms, visited, room_chunks)

    # Post-processing: optimize room placement across all chunks
    # - Pull rooms from other chunks if they fit
    # - Move rooms with bad placements to other chunks where they fit
    _optimize_chunk_placement(rooms, visited, room_chunks)

    # Split chunks with disconnected room sets into separate chunks
    _split_disconnected_chunks(rooms, visited, room_chunks)

    # Place disconnected rooms in their own chunk (not chunk 0)
    disconnected = [r for r in rooms.values() if r.room_id not in visited]
    if disconnected:
        # Get next available chunk number
        max_chunk = max(room_chunks.values()) if room_chunks else 0
        disconnected_chunk = max_chunk + 1

        # Place disconnected rooms in a row at grid position (0, 0) in their chunk
        for i, room in enumerate(sorted(disconnected, key=lambda r: r.room_id)):
            room.grid_x = i
            room.grid_y = 0
            room_chunks[room.room_id] = disconnected_chunk

    return (visited, grid_width, grid_height, connected_height, room_chunks)


def generate_room_tmx(room: Room,
                      room_collectibles: List[Collectible],
                      room_enemies: List[Enemy],
                      chunk: int = 0,
                      spawn: Optional[SpawnInfo] = None) -> str:
    """Generate TMX XML content for a single room.

    Args:
        room: Room data
        room_collectibles: List of collectibles in the room
        room_enemies: List of enemies in the room
        chunk: Chunk ID for disconnected room groups
        spawn: Optional spawn point info (from setup.dat)
    """
    # Build tile data
    tile_data = [[0] * ROOM_WIDTH for _ in range(ROOM_HEIGHT)]

    for row_idx, tile_row in enumerate(room.tiles):
        for col_idx, tile in enumerate(tile_row):
            # Convert old tile index to new TMX GID for split tilesets
            tile_data[row_idx][col_idx] = old_tile_to_new_gid(tile)

    # Convert to CSV
    csv_rows = []
    for row in tile_data:
        csv_rows.append(','.join(str(t) for t in row))
    csv_data = ',\n'.join(csv_rows)

    # Build collectibles objects
    collectible_objects = []
    obj_id = 1
    for item in room_collectibles:
        # GID for collectibles: item_type is the sprite row, 4 columns per row
        gid = TILESET_GIDS.collectibles + (item.item_type * 4)
        px = item.x
        py = item.y + TILE_SIZE  # TMX Y is bottom of object
        collectible_objects.append(
            f'  <object id="{obj_id}" gid="{gid}" x="{px}" y="{py}" width="8" height="8"/>'
        )
        obj_id += 1

    # Build enemy and route objects (routes go on a separate layer)
    enemy_objects = []
    route_objects = []

    # First pass: count guardian types to determine if numbering is needed
    guardian_type_counts: Dict[int, int] = {}
    for enemy in room_enemies:
        raw_gid = entity_type_to_gid(enemy.entity_type)
        guardian_type_counts[raw_gid] = guardian_type_counts.get(raw_gid, 0) + 1

    # Track current instance number for each type
    guardian_type_instance: Dict[int, int] = {}

    for enemy in room_enemies:
        # Use entity_type_to_gid for proper mapping of special types (lifts, arrows)
        # Arrows use sprite tiles (GIDs 700/701), they do NOT have patrol paths
        gid = entity_type_to_gid(enemy.entity_type)
        raw_gid = gid  # Store before adding flip flag
        # Sprites face left by default; flip horizontally if facing right (3)
        # Exception: lifts (entity_type 72) are symmetrical, don't mirror
        if enemy.facing == 3 and enemy.entity_type != ENTITY_TYPE_LIFT:
            gid |= FLIPPED_HORIZONTALLY_FLAG

        # Get sprite dimensions (oversized guardians have different sizes)
        # Normal guardians: 16x16, Periscope tank: 16x32, Evil head: 32x32
        sprite_w, sprite_h = get_guardian_dimensions(enemy.entity_type)
        px = enemy.spawn_x
        py = enemy.spawn_y + sprite_h  # TMX Y is bottom of object

        # Determine object type
        obj_type = "Arrow" if enemy.is_arrow else "Guardian"

        # Get guardian name for the object's name attribute
        guardian_name = get_guardian_name(raw_gid)
        if guardian_name:
            # Track instance number and add numbering if multiple of same type
            guardian_type_instance[raw_gid] = guardian_type_instance.get(raw_gid, 0) + 1
            if guardian_type_counts[raw_gid] > 1:
                guardian_name = f"{guardian_name} {guardian_type_instance[raw_gid]}"
            name_attr = f' name="{guardian_name}"'
        else:
            name_attr = ""

        # Build guardian properties (tint, flags, movement type)
        guardian_props = []
        # Add tint color if not default (0,0,0 = no tint)
        if enemy.r != 0 or enemy.g != 0 or enemy.b != 0:
            tint_color = f"#{enemy.r:02x}{enemy.g:02x}{enemy.b:02x}"
            guardian_props.append(f'    <property name="Color" type="color" value="{tint_color}"/>')
        # Add Flags property (HARMLESS for lifts)
        if enemy.entity_type == ENTITY_TYPE_LIFT:
            guardian_props.append(f'    <property name="Flags" propertytype="GuardianFlags" value="HARMLESS"/>')
        # Add FlightDirection and Speed properties for arrows
        if enemy.is_arrow:
            flight_direction = 0 if enemy.facing == 2 else 1  # 1=Left→Right, 0=Right→Left
            guardian_props.append(f'    <property name="FlightDirection" type="int" propertytype="FlightDirection" value="{flight_direction}"/>')
            guardian_props.append(f'    <property name="Speed" type="int" propertytype="Speed" value="{enemy.speed}"/>')

        if guardian_props:
            props_xml = "\n".join(guardian_props)
            enemy_objects.append(
                f'  <object id="{obj_id}"{name_attr} type="{obj_type}" gid="{gid}" x="{px}" y="{py}" width="{sprite_w}" height="{sprite_h}">\n'
                f'   <properties>\n{props_xml}\n   </properties>\n'
                f'  </object>'
            )
        else:
            enemy_objects.append(
                f'  <object id="{obj_id}"{name_attr} type="{obj_type}" gid="{gid}" x="{px}" y="{py}" width="{sprite_w}" height="{sprite_h}"/>'
            )

        # Add patrol path if enemy moves (arrows do NOT have patrol paths)
        if not enemy.is_arrow and (enemy.patrol_x1 != enemy.patrol_x2 or enemy.patrol_y1 != enemy.patrol_y2):
            guardian_id = obj_id  # Reference to the guardian object
            obj_id += 1
            path_x = min(enemy.patrol_x1, enemy.patrol_x2)
            path_y = min(enemy.patrol_y1, enemy.patrol_y2)

            # Calculate polyline points relative to path origin
            # Patrol bounds represent the guardian's top-left corner positions
            is_vertical_path = (enemy.patrol_x1 == enemy.patrol_x2 and
                                enemy.patrol_y1 != enemy.patrol_y2)

            if is_vertical_path:
                # Vertical path: points go from 0,0 to 0,height
                effective_h = abs(enemy.patrol_y2 - enemy.patrol_y1)
                polyline_points = f"0,0 0,{effective_h}"
                # Vertical: facing 3 = Up (0), facing 2 = Down (1)
                direction = 0 if enemy.facing == 3 else 1
            else:
                # Horizontal path: points go from 0,0 to width,0
                effective_w = abs(enemy.patrol_x2 - enemy.patrol_x1)
                polyline_points = f"0,0 {effective_w},0"
                # Horizontal: facing 3 = Right (3), facing 2 = Left (2)
                direction = 3 if enemy.facing == 3 else 2

            # Traversal enum: 0=Ping-Pong, 1=One-Way Reset, 2=One-Way Stop, 3=Loop
            traversal = enemy.movement_type if enemy.movement_type in (0, 1, 2, 3) else 0

            route_objects.append(f'''  <object id="{obj_id}" type="Route" x="{path_x}" y="{path_y}">
   <properties>
    <property name="Direction" type="int" propertytype="Direction" value="{direction}"/>
    <property name="Guardian" type="object" value="{guardian_id}"/>
    <property name="Speed" type="int" propertytype="Speed" value="{enemy.speed}"/>
    <property name="Traversal" type="int" propertytype="Traversal" value="{traversal}"/>
   </properties>
   <polyline points="{polyline_points}"/>
  </object>''')

        obj_id += 1

    # Build spawn objects (from setup.dat)
    spawn_objects = []
    if spawn:
        # Convert tile coordinates to pixel coordinates
        # TMX Y is at bottom of object, spawn object is 16x16
        spawn_px = spawn.tile_x * TILE_SIZE
        spawn_py = (spawn.tile_y + 2) * TILE_SIZE  # +2 tiles for object anchor at bottom
        template_name = get_spawn_template_name(spawn.team)
        spawn_objects.append(
            f'  <object id="{obj_id}" template="templates/{template_name}" x="{spawn_px}" y="{spawn_py}"/>'
        )
        obj_id += 1

    # Calculate relative path to tilesets (all tilesets are in tmx/tilesets/)
    tileset_path = "../../tilesets"

    # Build room properties (3-digit padded filenames)
    exit_up = f"{room.exit_up:03d}.tmx" if room.exit_up else ""
    exit_down = f"{room.exit_down:03d}.tmx" if room.exit_down else ""
    exit_left = f"{room.exit_left:03d}.tmx" if room.exit_left else ""
    exit_right = f"{room.exit_right:03d}.tmx" if room.exit_right else ""
    has_rope = "true" if room.has_rope == 'Y' else "false"

    # Generate TMX XML
    tmx = f'''<?xml version="1.0" encoding="UTF-8"?>
<map version="1.10" tiledversion="1.11.2" orientation="orthogonal" renderorder="right-down" backgroundcolor="#000000" width="{ROOM_WIDTH}" height="{ROOM_HEIGHT}" tilewidth="{TILE_SIZE}" tileheight="{TILE_SIZE}" infinite="0" nextlayerid="7" nextobjectid="{obj_id}">
 <properties>
  <property name="ChainRoomGroup" type="int" value="0"/>
  <property name="Chunk" type="int" value="{chunk}"/>
  <property name="Down" type="file" value="{exit_down}"/>
  <property name="Flags" propertytype="RoomFlags" value=""/>
  <property name="Left" type="file" value="{exit_left}"/>
  <property name="Name" value="{room.name}"/>
  <property name="RaceLabel" value=""/>
  <property name="Right" type="file" value="{exit_right}"/>
  <property name="Rope" type="bool" value="{has_rope}"/>
  <property name="Rope Offset" type="int" value="0"/>
  <property name="RoomPurpose" type="int" propertytype="RoomPurpose" value="0"/>
  <property name="Up" type="file" value="{exit_up}"/>
  <property name="WillySuit" type="int" propertytype="WillySuit" value="0"/>
 </properties>
 <tileset firstgid="{TILESET_GIDS.tiles_solid}" source="{tileset_path}/tiles_solid.tsx"/>
 <tileset firstgid="{TILESET_GIDS.tiles_stairs}" source="{tileset_path}/tiles_stairs.tsx"/>
 <tileset firstgid="{TILESET_GIDS.tiles_platform}" source="{tileset_path}/tiles_platform.tsx"/>
 <tileset firstgid="{TILESET_GIDS.tiles_hazard}" source="{tileset_path}/tiles_hazard.tsx"/>
 <tileset firstgid="{TILESET_GIDS.tiles_decoration}" source="{tileset_path}/tiles_decoration.tsx"/>
 <tileset firstgid="{TILESET_GIDS.tiles_conveyor}" source="{tileset_path}/tiles_conveyor.tsx"/>
 <tileset firstgid="{TILESET_GIDS.collectibles}" source="{tileset_path}/collectibles.tsx"/>
 <tileset firstgid="{TILESET_GIDS.guardians}" source="{tileset_path}/guardians.tsx"/>
 <layer id="1" name="Tiles" width="{ROOM_WIDTH}" height="{ROOM_HEIGHT}">
  <data encoding="csv">
{csv_data}
</data>
 </layer>
 <objectgroup id="2" name="Collectables">
{chr(10).join(collectible_objects)}
 </objectgroup>
 <objectgroup id="3" name="Enemies">
{chr(10).join(enemy_objects)}
 </objectgroup>
 <objectgroup id="4" name="Routes">
{chr(10).join(route_objects)}
 </objectgroup>
 <objectgroup id="5" name="Spawn">
{chr(10).join(spawn_objects)}
 </objectgroup>
</map>
'''
    return tmx


def generate_world_file(rooms: Dict[int, Room], room_chunks: Dict[int, int],
                        connected_height: int, map_name: str) -> str:
    """Generate a .world JSON file linking all rooms, with chunks packed using rectpack."""
    maps = []

    # Calculate actual bounding box for each chunk (in grid units)
    chunk_bounds: Dict[int, Tuple[int, int, int, int]] = {}  # chunk -> (min_x, min_y, max_x, max_y)
    for room_id, room in rooms.items():
        chunk = room_chunks.get(room_id, 0)
        if chunk not in chunk_bounds:
            chunk_bounds[chunk] = (room.grid_x, room.grid_y, room.grid_x, room.grid_y)
        else:
            min_x, min_y, max_x, max_y = chunk_bounds[chunk]
            chunk_bounds[chunk] = (
                min(min_x, room.grid_x),
                min(min_y, room.grid_y),
                max(max_x, room.grid_x),
                max(max_y, room.grid_y)
            )

    # Calculate chunk dimensions (width, height in grid units)
    chunk_sizes: Dict[int, Tuple[int, int]] = {}
    for chunk, (min_x, min_y, max_x, max_y) in chunk_bounds.items():
        chunk_sizes[chunk] = (max_x - min_x + 1, max_y - min_y + 1)

    # Chunk 0 stays at its natural position
    # Chunks 1+ get packed using rectpack, then positioned 1 room below chunk 0
    chunk_offsets: Dict[int, Tuple[int, int]] = {}  # chunk -> (x_offset, y_offset) in pixels

    if 0 in chunk_bounds:
        min_x, min_y, max_x, max_y = chunk_bounds[0]
        # Chunk 0 offset: normalize so min_y starts at 0
        chunk_offsets[0] = (-min_x * ROOM_PIXEL_WIDTH, -min_y * ROOM_PIXEL_HEIGHT)
        chunk0_bottom = (max_y - min_y + 1) * ROOM_PIXEL_HEIGHT
    else:
        chunk0_bottom = 0

    # Get non-zero chunks to pack
    non_zero_chunks = [c for c in chunk_bounds.keys() if c != 0]

    if non_zero_chunks:
        # Simple row-based packing: place chunks left-to-right in rows
        # Sort by height (tallest first), then by width (widest first)
        sorted_chunks = sorted(non_zero_chunks,
                               key=lambda c: (-chunk_sizes[c][1], -chunk_sizes[c][0]))

        # Determine target row width (use chunk 0's width if available, else calculate)
        if 0 in chunk_bounds:
            min_x0, _, max_x0, _ = chunk_bounds[0]
            target_width = max_x0 - min_x0 + 1
        else:
            # Use total area to estimate a reasonable width
            total_area = sum(chunk_sizes[c][0] * chunk_sizes[c][1] for c in non_zero_chunks)
            target_width = max(int(total_area ** 0.5), max(chunk_sizes[c][0] for c in non_zero_chunks))

        # Pack chunks into rows with 1-room gaps between chunks
        packed_positions: Dict[int, Tuple[int, int]] = {}
        current_x = 0
        current_y = 0
        row_height = 0

        for chunk in sorted_chunks:
            width, height = chunk_sizes[chunk]

            # Start new row if this chunk doesn't fit (include gap in calculation)
            if current_x > 0 and current_x + width > target_width:
                current_x = 0
                current_y += row_height + 1  # Add 1-room vertical gap between rows
                row_height = 0

            packed_positions[chunk] = (current_x, current_y)
            current_x += width + 1  # Add 1-room horizontal gap after each chunk
            row_height = max(row_height, height)

        # Position the packed group 1 room below chunk 0's bottom
        pack_base_y = chunk0_bottom + ROOM_PIXEL_HEIGHT  # 1 room gap below chunk 0

        for chunk in non_zero_chunks:
            pack_x, pack_y = packed_positions[chunk]
            min_x, min_y, _, _ = chunk_bounds[chunk]
            # Offset = packed position - original grid position (converted to pixels)
            chunk_offsets[chunk] = (
                pack_x * ROOM_PIXEL_WIDTH - min_x * ROOM_PIXEL_WIDTH,
                pack_base_y + pack_y * ROOM_PIXEL_HEIGHT - min_y * ROOM_PIXEL_HEIGHT
            )

    # Generate map entries
    for room_id in sorted(rooms.keys()):
        room = rooms[room_id]
        chunk = room_chunks.get(room_id, 0)

        # Calculate pixel position with chunk offset
        x_offset, y_offset = chunk_offsets.get(chunk, (0, 0))
        x = room.grid_x * ROOM_PIXEL_WIDTH + x_offset
        y = room.grid_y * ROOM_PIXEL_HEIGHT + y_offset

        maps.append({
            "fileName": f"{room_id:03d}.tmx",
            "height": ROOM_PIXEL_HEIGHT,
            "width": ROOM_PIXEL_WIDTH,
            "x": x,
            "y": y
        })

    world = {
        "maps": maps,
        "type": "world"
    }

    return json.dumps(world, indent=4)


def generate_tiled_project(map_name: str = "") -> str:
    """Generate a .tiled-project JSON file from the archetype template.

    Loads the full property type definitions from archetype.tiled-project
    and optionally sets the MapName project property.

    Args:
        map_name: Display name for the map (set in MapName property)
    """
    from tmx_project_lib import get_template_dir
    archetype_path = get_template_dir() / "archetype.tiled-project"
    with open(archetype_path, encoding="utf-8") as f:
        project = json.load(f)

    # Set MapName if provided
    if map_name:
        for prop in project.get("properties", []):
            if prop["name"] == "MapName":
                prop["value"] = map_name
                break

    return json.dumps(project, indent=4)


def _copy_templates_to_project(output_folder: str) -> bool:
    """Copy templates from archetype to project folder with path adjustment."""
    from tmx_project_lib import get_template_dir, copy_templates
    template_dir = get_template_dir()
    src = template_dir / "templates"
    dst = Path(output_folder) / "templates"
    changes = copy_templates(src, dst)
    for change in changes:
        print(f"  {change}")
    return True


def _copy_extensions_to_project(output_folder: str) -> bool:
    """Copy extensions from archetype to project folder."""
    from tmx_project_lib import get_template_dir, copy_extensions
    template_dir = get_template_dir()
    src = template_dir / ".extensions"
    dst = Path(output_folder) / ".extensions"
    changes = copy_extensions(src, dst)
    for change in changes:
        print(f"  {change}")
    return True


def convert_map(input_folder: str, output_folder: str = None):
    """Convert a folder of .dat files to individual TMX files and a world file."""
    if not os.path.isdir(input_folder):
        print(f"Error: {input_folder} is not a directory")
        return False

    map_name = os.path.basename(input_folder.rstrip('/'))

    if output_folder is None:
        output_folder = os.path.join('tmx', 'content', map_name)

    # Create output directory
    os.makedirs(output_folder, exist_ok=True)

    # Load guardian names, tile remaps, and calculate tileset GIDs from content folder
    content_folder = os.path.join(PROJECT_ROOT, "tmx", "content")
    load_guardian_names(content_folder)
    load_tile_remaps()

    global TILESET_GIDS
    TILESET_GIDS = calculate_tileset_gids(content_folder)
    print(f"Tileset GIDs: solid={TILESET_GIDS.tiles_solid}, stairs={TILESET_GIDS.tiles_stairs}, "
          f"platform={TILESET_GIDS.tiles_platform}, hazard={TILESET_GIDS.tiles_hazard}, "
          f"decoration={TILESET_GIDS.tiles_decoration}, conveyor={TILESET_GIDS.tiles_conveyor}, "
          f"collectibles={TILESET_GIDS.collectibles}, guardians={TILESET_GIDS.guardians}")

    # Load all rooms
    rooms: Dict[int, Room] = {}
    room_pattern = re.compile(r'^(\d+)\.dat$')

    for filepath in glob.glob(os.path.join(input_folder, '[0-9]*.dat')):
        basename = os.path.basename(filepath)
        match = room_pattern.match(basename)
        if match:
            room_id = int(match.group(1))
            room = load_room(filepath, room_id)
            if room:
                rooms[room_id] = room

    if not rooms:
        print(f"Error: No room files found in {input_folder}")
        return False

    print(f"Loaded {len(rooms)} rooms")

    # Load collectibles
    collectibles: Dict[int, List[Collectible]] = {}
    pickup_pattern = re.compile(r'^(\d+)_pickups\.dat$')

    for filepath in glob.glob(os.path.join(input_folder, '*_pickups.dat')):
        basename = os.path.basename(filepath)
        match = pickup_pattern.match(basename)
        if match:
            room_id = int(match.group(1))
            items = load_collectibles(filepath)
            if items:
                collectibles[room_id] = items

    total_collectibles = sum(len(items) for items in collectibles.values())
    print(f"Loaded {total_collectibles} collectibles")

    # Load enemies (handle both _enemy.dat and _ENEMY.dat variants)
    enemies: Dict[int, List[Enemy]] = {}
    enemy_pattern = re.compile(r'^(\d+)_enemy\.dat$', re.IGNORECASE)

    for filepath in glob.glob(os.path.join(input_folder, '*_[eE][nN][eE][mM][yY].dat')):
        basename = os.path.basename(filepath)
        match = enemy_pattern.match(basename)
        if match:
            room_id = int(match.group(1))
            room_enemies = load_enemies(filepath)
            if room_enemies:
                enemies[room_id] = room_enemies

    total_enemies = sum(len(e) for e in enemies.values())
    print(f"Loaded {total_enemies} enemies")

    # Look for setup.dat file (contains spawn positions)
    setup_dat_path = os.path.join(input_folder, f"{map_name}_setup.dat")
    spawns = parse_setup_dat(setup_dat_path) if os.path.exists(setup_dat_path) else {
        'player': None, 'red': None, 'blue': None
    }

    # Build spawn info by room_id for quick lookup
    spawn_by_room: Dict[int, SpawnInfo] = {}
    for key in ['player', 'red', 'blue']:
        if spawns[key]:
            room_id = spawns[key].room_id
            if room_id in spawn_by_room:
                # Multiple spawns in same room - keep the first one
                print(f"Warning: Multiple spawns in room {room_id}, using first")
            else:
                spawn_by_room[room_id] = spawns[key]

    # Build layout from connections
    visited_rooms, grid_width, grid_height, connected_height, room_chunks = build_room_layout(rooms)
    disconnected_count = len(rooms) - len(visited_rooms)
    num_chunks = max(room_chunks.values()) + 1 if room_chunks else 1
    print(f"Map grid: {grid_width + 1}x{grid_height + 1} rooms ({len(visited_rooms)} connected, {disconnected_count} disconnected, {num_chunks} chunk(s))")

    # Generate individual TMX files for ALL rooms
    for room_id in sorted(rooms.keys()):
        room = rooms[room_id]
        room_collectibles = collectibles.get(room_id, [])
        room_enemies = enemies.get(room_id, [])
        chunk = room_chunks.get(room_id, 0)
        room_spawn = spawn_by_room.get(room_id)

        tmx_content = generate_room_tmx(room, room_collectibles, room_enemies, chunk, room_spawn)

        # Use 3-digit padded filenames (e.g., 001.tmx, 002.tmx, etc.)
        output_path = os.path.join(output_folder, f"{room_id:03d}.tmx")
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(tmx_content)

        print(f"  Created {output_path}")

    # Generate world file
    world_content = generate_world_file(rooms, room_chunks, connected_height, map_name)
    world_path = os.path.join(output_folder, f"{map_name}.world")
    with open(world_path, 'w', encoding='utf-8') as f:
        f.write(world_content)
    print(f"Created {world_path}")

    # Verify no overlapping world positions by parsing the generated world file
    world_data = json.loads(world_content)
    world_positions: Dict[Tuple[int, int], List[str]] = {}
    for map_entry in world_data["maps"]:
        pos = (map_entry["x"], map_entry["y"])
        if pos not in world_positions:
            world_positions[pos] = []
        world_positions[pos].append(map_entry["fileName"])

    overlaps = {pos: files for pos, files in world_positions.items() if len(files) > 1}
    if overlaps:
        print(f"ERROR: {len(overlaps)} overlapping world positions detected!")
        for pos, files in list(overlaps.items())[:5]:
            print(f"  {pos}: {files}")
        return False

    # Generate tiled-project file from archetype
    project_content = generate_tiled_project(map_name)
    project_path = os.path.join(output_folder, f"{map_name}.tiled-project")
    with open(project_path, 'w', encoding='utf-8') as f:
        f.write(project_content)
    print(f"Created {project_path}")

    # Always copy templates and extensions for a complete project
    _copy_templates_to_project(output_folder)
    _copy_extensions_to_project(output_folder)

    return True


def generate_default_room_tmx(room_id: int = 1) -> str:
    """Generate a default empty room TMX file filled with tile 1.

    Delegates to generate_room_tmx() with an empty room to avoid duplication.
    """
    room = Room(room_id)
    room.name = ""
    # Fill tiles with tile index 0 (will become GID 1 = first solid tile)
    room.tiles = [[0] * ROOM_WIDTH for _ in range(ROOM_HEIGHT)]
    return generate_room_tmx(room, [], [])


def create_empty_map(mapname: str) -> bool:
    """
    Create a new map with a default empty room.

    Creates:
    - Output directory
    - World file (<mapname>.world) with one room
    - Default room (001.tmx) filled with tile 1
    - Tiled project file (<mapname>.tiled-project)
    - Templates folder
    - Extensions folder (.extensions)

    If mapname has no path separators, creates in tmx/content/<mapname>.
    If mapname contains path separators, uses the path directly.
    """
    global TILESET_GIDS

    # Initialize tileset GIDs if not already done
    if TILESET_GIDS is None:
        content_folder = os.path.join(PROJECT_ROOT, "tmx", "content")
        TILESET_GIDS = calculate_tileset_gids(content_folder)

    # Determine output path
    if os.sep in mapname or '/' in mapname:
        # mapname contains path separators - use as-is
        output_folder = mapname
        map_name = os.path.basename(mapname.rstrip('/\\'))
    else:
        # Just a name - use default path
        output_folder = os.path.join('tmx', 'content', mapname)
        map_name = mapname

    # Create output directory
    os.makedirs(output_folder, exist_ok=True)
    print(f"Creating new map '{map_name}' in {output_folder}")

    print("WARNING: --new is deprecated. Use 'tmx_project.py create' instead.")
    print()

    # Generate default room (001.tmx) filled with tile 1
    room_tmx = generate_default_room_tmx(room_id=1)
    room_path = os.path.join(output_folder, "001.tmx")
    with open(room_path, 'w', encoding='utf-8') as f:
        f.write(room_tmx)
    print(f"Created {room_path}")

    # Generate world file with the default room at position (0, 0)
    world = {
        "maps": [
            {
                "fileName": "001.tmx",
                "height": ROOM_PIXEL_HEIGHT,
                "width": ROOM_PIXEL_WIDTH,
                "x": 0,
                "y": 0
            }
        ],
        "type": "world"
    }
    world_path = os.path.join(output_folder, f"{map_name}.world")
    with open(world_path, 'w', encoding='utf-8') as f:
        f.write(json.dumps(world, indent=4))
    print(f"Created {world_path}")

    # Generate tiled-project file from archetype
    project_content = generate_tiled_project(map_name)
    project_path = os.path.join(output_folder, f"{map_name}.tiled-project")
    with open(project_path, 'w', encoding='utf-8') as f:
        f.write(project_content)
    print(f"Created {project_path}")

    # Copy templates
    if _copy_templates_to_project(output_folder):
        print("Templates copied successfully!")
    else:
        print("Warning: Failed to copy templates")

    # Copy extensions
    if _copy_extensions_to_project(output_folder):
        print("Extensions copied successfully!")
    else:
        print("Warning: Failed to copy extensions")

    print(f"Empty map '{map_name}' created successfully!")
    return True


def main():
    parser = argparse.ArgumentParser(
        description='Convert JSW .dat room files to Tiled .tmx files and a .world file.'
    )
    parser.add_argument('input_folder', nargs='?', default=None,
                        help='Input folder containing .dat room files')
    parser.add_argument('output_folder', nargs='?', default=None,
                        help='Output folder (default: tmx/content/<map_name>)')
    parser.add_argument('--map', action='store_true',
                        help='Convert room .dat files to TMX files')
    parser.add_argument('--templates', action='store_true',
                        help='Copy the templates folder')
    parser.add_argument('--extensions', action='store_true',
                        help='Copy the extensions folder')
    parser.add_argument('--new', metavar='MAPNAME',
                        help='Create an empty map. If MAPNAME has no path separators, '
                             'creates in tmx/content/<MAPNAME>, otherwise uses the path directly.')

    args = parser.parse_args()

    # Handle --new flag (creates empty map, ignores other flags)
    if args.new:
        if create_empty_map(args.new):
            sys.exit(0)
        else:
            sys.exit(1)

    # If no flags specified, do nothing
    if not args.map and not args.templates and not args.extensions:
        print("No action specified. Use --map, --templates, --extensions, or --new.")
        parser.print_help()
        sys.exit(0)

    # For --map, --templates, --extensions: require input_folder
    if not args.input_folder:
        print("Error: input_folder is required for --map, --templates, or --extensions.")
        parser.print_help()
        sys.exit(1)

    # Determine output folder
    if args.output_folder:
        output_folder = args.output_folder
    else:
        map_name = os.path.basename(args.input_folder.rstrip('/'))
        output_folder = os.path.join('tmx', 'content', map_name)

    # Create output folder if needed for templates/extensions
    if args.templates or args.extensions:
        os.makedirs(output_folder, exist_ok=True)

    # Copy templates if requested
    if args.templates:
        if _copy_templates_to_project(output_folder):
            print("Templates copied successfully!")
        else:
            sys.exit(1)

    # Copy extensions if requested
    if args.extensions:
        if _copy_extensions_to_project(output_folder):
            print("Extensions copied successfully!")
        else:
            sys.exit(1)

    # Convert map if requested
    if args.map:
        if convert_map(args.input_folder, args.output_folder):
            print("Conversion complete!")
        else:
            sys.exit(1)


if __name__ == "__main__":
    main()