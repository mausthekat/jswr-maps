#!/usr/bin/env python3
"""
Convert Tiled .tmx files back to JSW .dat room files.

Usage (from project root):
    python tmx/scripts/tmx_to_dat.py tmx/content/main --map
    python tmx/scripts/tmx_to_dat.py tmx/content/main output_folder --map

This will read TMX files and create:
  - Room .dat files (e.g., 1.dat, 2.dat)
  - Collectible _pickups.dat files
  - Enemy _enemy.dat files
"""

import argparse
import os
import sys
import struct
import re
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional, Tuple

# Project root is 2 levels up from this script (tmx/scripts -> tmx -> project)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))

# =============================================================================
# Constants - Must match dat_to_tmx.py exactly
# =============================================================================
ROOM_WIDTH = 32   # tiles wide
ROOM_HEIGHT = 16  # tiles tall
TILE_SIZE = 8     # pixels per tile
EDITOR_SCALE = 2  # coordinate scale in .dat files

# Room dimensions in pixels
ROOM_PIXEL_WIDTH = ROOM_WIDTH * TILE_SIZE    # 256
ROOM_PIXEL_HEIGHT = ROOM_HEIGHT * TILE_SIZE  # 128

# TMX GID flip flags
FLIPPED_HORIZONTALLY_FLAG = 0x80000000
FLIPPED_VERTICALLY_FLAG = 0x40000000
FLIPPED_DIAGONALLY_FLAG = 0x20000000
GID_MASK = 0x0FFFFFFF  # Mask to extract tile ID without flip flags

# =============================================================================
# Tileset GID ranges (2048-spaced firstgids)
# =============================================================================
# TMX FirstGid Scheme:
#   tiles_solid      = 1      (range 1-2048)
#   tiles_stairs     = 2049   (range 2049-4096)
#   tiles_platform   = 4097   (range 4097-6144)
#   tiles_hazard     = 6145   (range 6145-8192)
#   tiles_decoration = 8193   (range 8193-10240)
#   tiles_conveyor   = 10241  (range 10241-12288)
#   collectibles     = 12289  (range 12289-14336)
#   guardians        = 14337  (range 14337-16384)
TILES_FIRSTGID = 1
COLLECTIBLES_FIRSTGID = 12289
GUARDIANS_FIRSTGID = 14337

# =============================================================================
# Entity type mapping (reverse of dat_to_tmx.py)
# =============================================================================
# For reverse conversion (tmx_to_dat):
#   - GID 14407 (14337 + 70) → entity_type 72 (lift)
#   - GID 14408 (14337 + 71) → entity_type 73 (arrow left)
#   - GID 14409 (14337 + 72) → entity_type 74 (arrow right)
#   - GID 14410 (14337 + 73) → entity_type 70 (periscope tank)
#   - GID 14411 (14337 + 74) → entity_type 71 (evil giant head)

ENTITY_TYPE_PERISCOPE_TANK = 70
ENTITY_TYPE_EVIL_GIANT_HEAD = 71
ENTITY_TYPE_LIFT = 72
ENTITY_TYPE_ARROW_LEFT = 73
ENTITY_TYPE_ARROW_RIGHT = 74

# Guardian sprite dimensions
GUARDIAN_WIDTH_NORMAL = 16
GUARDIAN_HEIGHT_NORMAL = 16
GUARDIAN_WIDTH_EVIL_HEAD = 32
GUARDIAN_HEIGHT_OVERSIZED = 32


def gid_to_entity_type(gid: int, gids: 'TilesetGids') -> int:
    """
    Convert TMX GID to dat file entity_type.

    Reverse of entity_type_to_gid() in dat_to_tmx.py.
    """
    # Strip flip flags
    raw_gid = gid & GID_MASK

    # Oversized guardians (separate tilesets)
    if gids.periscope_tank and raw_gid == gids.periscope_tank:
        return ENTITY_TYPE_PERISCOPE_TANK
    elif gids.evil_giant_head and raw_gid == gids.evil_giant_head:
        return ENTITY_TYPE_EVIL_GIANT_HEAD

    # Special entities in guardians tileset
    # tile_index 70 = lift, but entity_type is 72
    # tile_index 71 = arrow left, but entity_type is 73
    # tile_index 72 = arrow right, but entity_type is 74
    tile_index = raw_gid - gids.guardians

    if tile_index == 70:
        return ENTITY_TYPE_LIFT
    elif tile_index == 71:
        return ENTITY_TYPE_ARROW_LEFT
    elif tile_index == 72:
        return ENTITY_TYPE_ARROW_RIGHT
    else:
        # Normal guardians: entity_type = tile_index
        return tile_index


def get_guardian_dimensions(entity_type: int) -> Tuple[int, int]:
    """Get width and height of guardian sprite in pixels."""
    if entity_type == ENTITY_TYPE_EVIL_GIANT_HEAD:
        return (GUARDIAN_WIDTH_EVIL_HEAD, GUARDIAN_HEIGHT_OVERSIZED)
    elif entity_type == ENTITY_TYPE_PERISCOPE_TANK:
        return (GUARDIAN_WIDTH_NORMAL, GUARDIAN_HEIGHT_OVERSIZED)
    return (GUARDIAN_WIDTH_NORMAL, GUARDIAN_HEIGHT_NORMAL)


def is_arrow_type(entity_type: int) -> bool:
    """Check if entity type is an arrow."""
    return entity_type in (ENTITY_TYPE_ARROW_LEFT, ENTITY_TYPE_ARROW_RIGHT)


# =============================================================================
# TMX Parsing
# =============================================================================

class TilesetGids:
    """Holds firstgid values parsed from a TMX file's tileset elements."""
    def __init__(self):
        self.tiles: int = 1
        self.collectibles: int = 0
        self.guardians: int = 0
        self.periscope_tank: int = 0
        self.evil_giant_head: int = 0


def parse_tileset_gids(root: ET.Element) -> TilesetGids:
    """Parse firstgid values from TMX tileset elements."""
    gids = TilesetGids()

    for tileset in root.findall('tileset'):
        firstgid = int(tileset.get('firstgid', '0'))
        source = tileset.get('source', '')
        name = tileset.get('name', '')

        # Match by source filename or name attribute
        source_lower = source.lower()
        name_lower = name.lower()

        if 'tiles' in source_lower or 'tiles' in name_lower:
            gids.tiles = firstgid
        elif 'collectible' in source_lower or 'collectible' in name_lower:
            gids.collectibles = firstgid
        elif 'guardian' in source_lower or 'guardian' in name_lower:
            gids.guardians = firstgid
        elif 'periscope' in source_lower or 'periscope' in name_lower:
            gids.periscope_tank = firstgid
        elif 'evil' in source_lower or 'head' in source_lower or 'evil' in name_lower or 'head' in name_lower:
            gids.evil_giant_head = firstgid

    return gids


class ParsedRoom:
    """Parsed room data from TMX file."""
    def __init__(self, room_id: int):
        self.room_id = room_id
        self.name = ""
        self.tiles: List[List[int]] = []
        self.exit_up: int = 0
        self.exit_right: int = 0
        self.exit_down: int = 0
        self.exit_left: int = 0
        self.has_rope: bool = False


class ParsedCollectible:
    """Parsed collectible from TMX file."""
    def __init__(self, x: int, y: int, item_type: int):
        self.x = x
        self.y = y
        self.item_type = item_type


class ParsedEnemy:
    """Parsed enemy/guardian from TMX file."""
    def __init__(self):
        self.spawn_x: int = 0
        self.spawn_y: int = 0
        self.entity_type: int = 0
        self.patrol_x1: int = 0
        self.patrol_y1: int = 0
        self.patrol_x2: int = 0
        self.patrol_y2: int = 0
        self.facing: int = 1  # 1=right, 3=left (default left)
        self.speed: int = 1
        self.r: int = 0
        self.g: int = 0
        self.b: int = 0
        self.movement_type: int = 1  # 1=horizontal, 2=vertical


def parse_exit_filename(value: str) -> int:
    """Parse exit filename like '003.tmx' to room ID 3. Returns 0 if empty."""
    if not value or value == "":
        return 0
    match = re.match(r'^(\d+)\.tmx$', value)
    if match:
        return int(match.group(1))
    return 0


def parse_color_property(value: str) -> Tuple[int, int, int]:
    """Parse color property like '#ff0080' to (r, g, b) tuple."""
    if not value or not value.startswith('#'):
        return (0, 0, 0)

    hex_str = value[1:]  # Remove '#'

    # Handle different formats
    if len(hex_str) == 6:
        # #RRGGBB
        r = int(hex_str[0:2], 16)
        g = int(hex_str[2:4], 16)
        b = int(hex_str[4:6], 16)
    elif len(hex_str) == 8:
        # #AARRGGBB (alpha + RGB)
        r = int(hex_str[2:4], 16)
        g = int(hex_str[4:6], 16)
        b = int(hex_str[6:8], 16)
    else:
        return (0, 0, 0)

    return (r, g, b)


def parse_tmx_room(tmx_path: str, room_id: int) -> Optional[Tuple[ParsedRoom, List[ParsedCollectible], List[ParsedEnemy]]]:
    """
    Parse a TMX file and extract room data, collectibles, and enemies.

    Returns (room, collectibles, enemies) or None on error.
    """
    try:
        tree = ET.parse(tmx_path)
        root = tree.getroot()
    except Exception as e:
        print(f"Error parsing {tmx_path}: {e}")
        return None

    room = ParsedRoom(room_id)
    collectibles: List[ParsedCollectible] = []
    enemies: List[ParsedEnemy] = []

    # Parse tileset firstgid values from this TMX file
    gids = parse_tileset_gids(root)

    # Parse room properties
    properties = root.find('properties')
    if properties is not None:
        for prop in properties.findall('property'):
            name = prop.get('name')
            value = prop.get('value', '')

            if name == 'Name':
                room.name = value
            elif name == 'Up':
                room.exit_up = parse_exit_filename(value)
            elif name == 'Right':
                room.exit_right = parse_exit_filename(value)
            elif name == 'Down':
                room.exit_down = parse_exit_filename(value)
            elif name == 'Left':
                room.exit_left = parse_exit_filename(value)
            elif name == 'Rope':
                room.has_rope = value.lower() == 'true'

    # Parse tile layer
    layer = root.find(".//layer[@name='Tiles']")
    if layer is not None:
        data = layer.find('data')
        if data is not None and data.get('encoding') == 'csv':
            csv_text = data.text.strip()
            rows = csv_text.split('\n')
            for row in rows:
                # Handle trailing comma
                row = row.rstrip(',').strip()
                if row:
                    tile_row = []
                    for cell in row.split(','):
                        cell = cell.strip()
                        if cell:
                            gid = int(cell)
                            # TMX uses 1-based tile IDs, dat uses 0-based
                            # GID 0 = empty, GID 1 = tile 0, GID 2 = tile 1, etc.
                            tile_value = max(0, gid - 1)
                            tile_row.append(tile_value)
                    if tile_row:
                        room.tiles.append(tile_row)

    # Ensure tiles grid is correct size
    while len(room.tiles) < ROOM_HEIGHT:
        room.tiles.append([0] * ROOM_WIDTH)
    for row in room.tiles:
        while len(row) < ROOM_WIDTH:
            row.append(0)

    # Parse object groups
    # First pass: collect all guardian objects by ID
    guardian_objects: Dict[str, dict] = {}
    route_objects: List[dict] = []
    collectible_objects: List[dict] = []

    for objgroup in root.findall('objectgroup'):
        # group_name = objgroup.get('name', '')

        for obj in objgroup.findall('object'):
            obj_id = obj.get('id', '')
            obj_type = obj.get('type', '')
            gid_str = obj.get('gid', '')
            x = float(obj.get('x', 0))
            y = float(obj.get('y', 0))
            width = float(obj.get('width', 0))
            height = float(obj.get('height', 0))

            # Get properties
            obj_props = {}
            props_elem = obj.find('properties')
            if props_elem is not None:
                for prop in props_elem.findall('property'):
                    obj_props[prop.get('name')] = prop.get('value', '')

            if gid_str:
                gid = int(gid_str)
                raw_gid = gid & GID_MASK
                is_flipped = bool(gid & FLIPPED_HORIZONTALLY_FLAG)

                # Determine object category by GID range (using parsed firstgid values)
                if gids.collectibles and gids.guardians and gids.collectibles <= raw_gid < gids.guardians:
                    # Collectible
                    collectible_objects.append({
                        'gid': raw_gid,
                        'x': x,
                        'y': y,
                        'width': width,
                        'height': height
                    })
                elif (gids.guardians and raw_gid >= gids.guardians) or \
                     (gids.periscope_tank and raw_gid == gids.periscope_tank) or \
                     (gids.evil_giant_head and raw_gid == gids.evil_giant_head):
                    # Guardian/Enemy
                    guardian_objects[obj_id] = {
                        'gid': raw_gid,
                        'x': x,
                        'y': y,
                        'width': width,
                        'height': height,
                        'is_flipped': is_flipped,
                        'props': obj_props,
                        'type': obj_type
                    }
            else:
                # No GID - this is a route/path object
                if 'Guardian' in obj_props:
                    route_objects.append({
                        'x': x,
                        'y': y,
                        'width': width,
                        'height': height,
                        'props': obj_props
                    })

    # Parse collectibles
    for coll in collectible_objects:
        gid = coll['gid']
        x = int(coll['x'])
        # TMX Y is bottom of object, convert to top-left
        y = int(coll['y']) - int(coll['height'])

        # Collectible type: (gid - collectibles_firstgid) / columns
        # Tileset has 4 columns (frames) per row (type)
        item_type = (gid - gids.collectibles) // 4

        collectibles.append(ParsedCollectible(x, y, item_type))

    # Build guardian ID to route mapping
    route_by_guardian: Dict[str, dict] = {}
    for route in route_objects:
        guardian_id = route['props'].get('Guardian', '')
        if guardian_id:
            route_by_guardian[guardian_id] = route

    # Parse enemies (guardians + their routes)
    for guardian_id, guardian in guardian_objects.items():
        enemy = ParsedEnemy()

        gid = guardian['gid']
        entity_type = gid_to_entity_type(gid, gids)
        enemy.entity_type = entity_type

        # Get sprite dimensions
        sprite_w, sprite_h = get_guardian_dimensions(entity_type)

        # TMX Y is bottom of object, convert to top-left
        spawn_x = int(guardian['x'])
        spawn_y = int(guardian['y']) - sprite_h
        enemy.spawn_x = spawn_x
        enemy.spawn_y = spawn_y

        # Facing direction: This will be set from the route's Direction property
        # The Direction property in TMX is set directly from enemy.facing in dat_to_tmx.py
        # Direction enum: 0=Up, 1=Down, 2=Left, 3=Right
        # For sprites, facing=3 causes horizontal flip (facing right)
        # Default to Left (2) for now, will be overwritten from route
        enemy.facing = 2  # Default: Left

        # Parse Color property - default to white if not specified
        color_str = guardian['props'].get('Color', '')
        if color_str:
            enemy.r, enemy.g, enemy.b = parse_color_property(color_str)
        else:
            # No color specified - default to white and warn
            enemy.r, enemy.g, enemy.b = 255, 255, 255
            obj_type = guardian.get('type', 'Guardian')
            print(f"  Warning: {obj_type} at ({spawn_x}, {spawn_y}) has no Color property, defaulting to white")

        # Get route/patrol path
        route = route_by_guardian.get(guardian_id)
        if route and not is_arrow_type(entity_type):
            # Route exists
            path_x = int(route['x'])
            path_y = int(route['y'])
            path_w = int(route['width'])
            path_h = int(route['height'])

            # Get direction (sprite facing) and speed from route properties
            direction = int(route['props'].get('Direction', '0'))
            enemy.speed = int(route['props'].get('Speed', '1'))

            # Direction property = sprite facing (0=Up, 1=Down, 2=Left, 3=Right)
            # This is different from patrol direction!
            enemy.facing = direction

            # Determine patrol direction from path dimensions, not from Direction
            # dat_to_tmx adds sprite dimensions to show full movement range:
            #   - Horizontal paths: path_w includes sprite_w
            #   - Vertical paths: path_h includes sprite_h
            # The `or 16` in dat_to_tmx means minimum dimension is 16 (sprite size)
            #
            # If path is wider than tall (after accounting for sprite), it's horizontal
            # If path is taller than wide (after accounting for sprite), it's vertical

            # Calculate effective movement range
            effective_w = path_w - sprite_w  # Horizontal range
            effective_h = path_h - sprite_h  # Vertical range

            # Determine if horizontal or vertical based on which dimension has movement
            is_horizontal = effective_w > 0 and effective_h <= 0
            is_vertical = effective_h > 0 and effective_w <= 0

            if is_horizontal:
                # Horizontal movement: Y stays same
                enemy.movement_type = 1
                enemy.patrol_x1 = path_x
                enemy.patrol_y1 = path_y
                enemy.patrol_x2 = path_x + max(0, effective_w)
                enemy.patrol_y2 = path_y  # Same Y for horizontal
            elif is_vertical:
                # Vertical movement: X stays same
                enemy.movement_type = 2
                enemy.patrol_x1 = path_x
                enemy.patrol_y1 = path_y
                enemy.patrol_x2 = path_x  # Same X for vertical
                enemy.patrol_y2 = path_y + max(0, effective_h)
            else:
                # Both dimensions or stationary
                # Use whichever dimension is larger
                if effective_w >= effective_h:
                    enemy.movement_type = 1  # Horizontal
                else:
                    enemy.movement_type = 2  # Vertical
                enemy.patrol_x1 = path_x
                enemy.patrol_y1 = path_y
                enemy.patrol_x2 = path_x + max(0, effective_w)
                enemy.patrol_y2 = path_y + max(0, effective_h)
        else:
            # No route - stationary or arrow
            # For arrows, patrol bounds are same as spawn
            enemy.patrol_x1 = spawn_x
            enemy.patrol_y1 = spawn_y
            enemy.patrol_x2 = spawn_x
            enemy.patrol_y2 = spawn_y

            # Arrows have FlightDirection and Speed properties
            # FlightDirection 0 (Right→Left) → facing = 3 in .dat file
            # FlightDirection 1 (Left→Right) → facing = 2 in .dat file
            # movement_type = 2 for all arrows (100% consistent in original data)
            if is_arrow_type(entity_type):
                flight_direction = int(guardian['props'].get('FlightDirection', '0'))
                # FlightDirection 0 = Right→Left → facing byte 3
                # FlightDirection 1 = Left→Right → facing byte 2
                enemy.facing = 2 if flight_direction == 0 else 3
                enemy.speed = int(guardian['props'].get('Speed', '1'))
                enemy.movement_type = 2
            else:
                # Stationary guardian - use horizontal flip flag to determine facing
                # Flipped sprite = facing right (3), unflipped = facing left (2)
                if guardian['is_flipped']:
                    enemy.facing = 3  # Right
                else:
                    enemy.facing = 2  # Left (default)

        enemies.append(enemy)

    return (room, collectibles, enemies)


# =============================================================================
# DAT File Writing
# =============================================================================

def write_room_dat(room: ParsedRoom, output_path: str) -> bool:
    """
    Write room data to a .dat file.

    File format (1065 bytes):
    - Bytes 0-1: Header "04" (ASCII)
    - Bytes 2-1025: Tiles (512 tiles × 2 bytes, little-endian uint16)
    - Byte 1026: Exit Up (room ID or 0)
    - Byte 1027: Exit Right (room ID or 0)
    - Byte 1028: Exit Down (room ID or 0)
    - Byte 1029: Exit Left (room ID or 0)
    - Bytes 1030-1061: Room name (32 bytes, space-padded)
    - Byte 1062: Padding (space)
    - Byte 1063: Rope flag ('Y' or 'N')
    - Byte 1064: Padding (null)
    """
    data = bytearray(1065)

    # Header "04"
    data[0] = ord('0')
    data[1] = ord('4')

    # Tiles (32 × 16 = 512 tiles, 2 bytes each)
    offset = 2
    for row in range(ROOM_HEIGHT):
        for col in range(ROOM_WIDTH):
            tile = 0
            if row < len(room.tiles) and col < len(room.tiles[row]):
                tile = room.tiles[row][col]
            struct.pack_into('<H', data, offset, tile)
            offset += 2

    # Exits (single bytes at offsets 1026-1029)
    data[1026] = room.exit_up & 0xFF
    data[1027] = room.exit_right & 0xFF
    data[1028] = room.exit_down & 0xFF
    data[1029] = room.exit_left & 0xFF

    # Room name (32 bytes, space-padded)
    name_bytes = room.name.encode('latin-1', errors='replace')[:32]
    # Pad with spaces to 32 bytes
    name_bytes = name_bytes.ljust(32, b' ')
    data[1030:1062] = name_bytes

    # Rope flag (offset 1063)
    data[1063] = ord('Y') if room.has_rope else ord('N')

    # Padding
    data[1062] = 0x20  # Space before rope flag
    data[1064] = 0x00  # Null after rope flag

    try:
        with open(output_path, 'wb') as f:
            f.write(data)
        return True
    except Exception as e:
        print(f"Error writing {output_path}: {e}")
        return False


def write_collectibles_dat(collectibles: List[ParsedCollectible], output_path: str) -> bool:
    """
    Write collectibles to a _pickups.dat file.

    File format:
    - Bytes 0-1: Header "03" (ASCII)
    - Byte 2: Count - 1 (number of collectibles minus 1)
    - Byte 3: Padding (0)
    - Bytes 4+: Collectible records (5 bytes each)

    Each collectible record:
    - Bytes 0-1: X coordinate (little-endian uint16, multiplied by EDITOR_SCALE)
    - Bytes 2-3: Y coordinate (little-endian uint16, multiplied by EDITOR_SCALE)
    - Byte 4: Item type (0-24 for standard, 25 for Golden Willy)
    """
    if not collectibles:
        return True  # No collectibles, no file needed

    count = len(collectibles)
    file_size = 4 + count * 5
    # Minimum file size observed is 25 bytes
    file_size = max(file_size, 25)

    data = bytearray(file_size)

    # Header "03"
    data[0] = ord('0')
    data[1] = ord('3')

    # Count - 1
    data[2] = (count - 1) & 0xFF

    # Padding
    data[3] = 0

    # Collectible records
    offset = 4
    for coll in collectibles:
        # Multiply coordinates by EDITOR_SCALE
        x_scaled = coll.x * EDITOR_SCALE
        y_scaled = coll.y * EDITOR_SCALE

        struct.pack_into('<H', data, offset, x_scaled)
        struct.pack_into('<H', data, offset + 2, y_scaled)
        data[offset + 4] = coll.item_type & 0xFF
        offset += 5

    # Pad rest with spaces (0x20) if needed
    while offset < file_size:
        data[offset] = 0x20
        offset += 1

    try:
        with open(output_path, 'wb') as f:
            f.write(data)
        return True
    except Exception as e:
        print(f"Error writing {output_path}: {e}")
        return False


def write_enemies_dat(enemies: List[ParsedEnemy], output_path: str) -> bool:
    """
    Write enemies to an _enemy.dat file.

    File format:
    - Bytes 0-1: Header "10" (ASCII)
    - Byte 2: Count - 1 (number of enemies minus 1)
    - Byte 3: Padding (0)
    - Bytes 4+: Enemy records (19 bytes each)

    Each enemy record:
    - Bytes 0-1: Spawn X (little-endian uint16, × EDITOR_SCALE)
    - Bytes 2-3: Spawn Y (little-endian uint16, × EDITOR_SCALE)
    - Byte 4: Entity type
    - Bytes 5-6: Patrol X1 (little-endian uint16, × EDITOR_SCALE)
    - Bytes 7-8: Patrol Y1 (little-endian uint16, × EDITOR_SCALE)
    - Bytes 9-10: Patrol X2 (little-endian uint16, × EDITOR_SCALE)
    - Bytes 11-12: Patrol Y2 (little-endian uint16, × EDITOR_SCALE)
    - Byte 13: Facing (1=left, 3=right)
    - Byte 14: Speed
    - Byte 15: Red
    - Byte 16: Green
    - Byte 17: Blue
    - Byte 18: Movement type (1=horizontal, 2=vertical)
    """
    if not enemies:
        return True  # No enemies, no file needed

    count = len(enemies)
    file_size = 4 + count * 19

    data = bytearray(file_size)

    # Header "10"
    data[0] = ord('1')
    data[1] = ord('0')

    # Count - 1
    data[2] = (count - 1) & 0xFF

    # Padding
    data[3] = 0

    # Enemy records
    offset = 4
    for enemy in enemies:
        # Multiply coordinates by EDITOR_SCALE
        spawn_x = enemy.spawn_x * EDITOR_SCALE
        spawn_y = enemy.spawn_y * EDITOR_SCALE
        patrol_x1 = enemy.patrol_x1 * EDITOR_SCALE
        patrol_y1 = enemy.patrol_y1 * EDITOR_SCALE
        patrol_x2 = enemy.patrol_x2 * EDITOR_SCALE
        patrol_y2 = enemy.patrol_y2 * EDITOR_SCALE

        struct.pack_into('<H', data, offset, spawn_x)
        struct.pack_into('<H', data, offset + 2, spawn_y)
        data[offset + 4] = enemy.entity_type & 0xFF
        struct.pack_into('<H', data, offset + 5, patrol_x1)
        struct.pack_into('<H', data, offset + 7, patrol_y1)
        struct.pack_into('<H', data, offset + 9, patrol_x2)
        struct.pack_into('<H', data, offset + 11, patrol_y2)
        data[offset + 13] = enemy.facing & 0xFF
        data[offset + 14] = enemy.speed & 0xFF
        data[offset + 15] = enemy.r & 0xFF
        data[offset + 16] = enemy.g & 0xFF
        data[offset + 17] = enemy.b & 0xFF
        data[offset + 18] = enemy.movement_type & 0xFF
        offset += 19

    # Pad with spaces to make file size consistent with observed files
    min_size = 180  # Observed minimum
    if len(data) < min_size:
        data.extend(b' ' * (min_size - len(data)))

    try:
        with open(output_path, 'wb') as f:
            f.write(data)
        return True
    except Exception as e:
        print(f"Error writing {output_path}: {e}")
        return False


# =============================================================================
# Main Conversion
# =============================================================================

def convert_tmx_folder(input_folder: str, output_folder: str) -> bool:
    """
    Convert all TMX files in a folder to .dat files.
    """
    if not os.path.isdir(input_folder):
        print(f"Error: {input_folder} is not a directory")
        return False

    # Create output directory
    os.makedirs(output_folder, exist_ok=True)

    # Find all TMX files
    tmx_pattern = re.compile(r'^(\d+)\.tmx$')
    tmx_files = []

    for filename in os.listdir(input_folder):
        match = tmx_pattern.match(filename)
        if match:
            room_id = int(match.group(1))
            tmx_files.append((room_id, os.path.join(input_folder, filename)))

    if not tmx_files:
        print(f"Error: No TMX files found in {input_folder}")
        return False

    tmx_files.sort(key=lambda x: x[0])
    print(f"Found {len(tmx_files)} TMX files")

    # Convert each TMX file
    rooms_converted = 0
    collectibles_written = 0
    enemies_written = 0

    for room_id, tmx_path in tmx_files:
        result = parse_tmx_room(tmx_path, room_id)
        if result is None:
            print(f"  Skipping {tmx_path} (parse error)")
            continue

        room, collectibles, enemies = result

        # Write room .dat file
        room_dat_path = os.path.join(output_folder, f"{room_id}.dat")
        if write_room_dat(room, room_dat_path):
            rooms_converted += 1
            print(f"  Created {room_dat_path}")

        # Write collectibles if any
        if collectibles:
            pickups_path = os.path.join(output_folder, f"{room_id}_pickups.dat")
            if write_collectibles_dat(collectibles, pickups_path):
                collectibles_written += len(collectibles)
                print(f"  Created {pickups_path} ({len(collectibles)} items)")

        # Write enemies if any
        if enemies:
            enemy_path = os.path.join(output_folder, f"{room_id}_enemy.dat")
            if write_enemies_dat(enemies, enemy_path):
                enemies_written += len(enemies)
                print(f"  Created {enemy_path} ({len(enemies)} enemies)")

    print("\nConversion complete:")
    print(f"  Rooms: {rooms_converted}")
    print(f"  Collectibles: {collectibles_written}")
    print(f"  Enemies: {enemies_written}")

    return True


def main():
    parser = argparse.ArgumentParser(
        description='Convert Tiled .tmx files to JSW .dat room files.'
    )
    parser.add_argument('input_folder', help='Input folder containing .tmx files')
    parser.add_argument('output_folder', nargs='?', default=None,
                        help='Output folder (default: assets/rooms/<map_name>)')
    parser.add_argument('--map', action='store_true',
                        help='Convert TMX files to .dat files')

    args = parser.parse_args()

    # If no flags specified, do nothing
    if not args.map:
        print("No action specified. Use --map to convert.")
        parser.print_help()
        sys.exit(0)

    # Determine output folder
    if args.output_folder:
        output_folder = args.output_folder
    else:
        map_name = os.path.basename(args.input_folder.rstrip('/'))
        output_folder = os.path.join('assets', 'rooms', map_name)

    if args.map:
        if convert_tmx_folder(args.input_folder, output_folder):
            print("\nDone!")
        else:
            sys.exit(1)


if __name__ == "__main__":
    main()