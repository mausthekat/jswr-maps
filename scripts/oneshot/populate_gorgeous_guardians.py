#!/usr/bin/env python3
"""
Populate jsw-gorgeous TMX files with guardians and routes from the original
ZX Spectrum room data (tmx/scripts/oneshot/_data/jsw_original_room_data.txt).

Matches rooms by name. Guardians go in the Enemies layer, routes go in a
separate Routes layer (matching the main map format).

Usage:
    python tmx/scripts/oneshot/populate_gorgeous_guardians.py [--dry-run]
"""

import argparse
import os
import re
import xml.etree.ElementTree as ET

# Script lives at tmx/scripts/oneshot/populate_gorgeous_guardians.py
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TMX_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))  # tmx/
GORGEOUS_DIR = os.path.join(TMX_ROOT, "_in_progress", "jsw-gorgeous")
ROOM_DATA_FILE = os.path.join(SCRIPT_DIR, "_data", "jsw_original_room_data.txt")

# Guardian name -> tile index in guardians.tsx (0-based, from guardians.txt)
GUARDIAN_TILES = {
    "Saw": 0, "Egg": 1, "Maria": 2, "Chip": 3, "Scroll": 4,
    "Pliars": 5, "Warehouse Beast": 6, "Tear": 7, "Guillotine": 8,
    "Esmeralda": 9, "Flower": 10, "Foot": 11, "Barrel": 12,
    "Two Globes": 13, "Bunny": 14, "Chef": 15, "Duck Priest": 16,
    "Swiss Army Knife": 17, "Flying Pig": 18, "Devil": 19, "Spiral": 20,
    "Razor Blade": 21, "Robot": 22, "Sun Face": 23, "Flag": 24,
    "Pac-Man": 25, "Ice Cream": 26, "Beetle": 27, "UFO": 28,
    "Coin": 29, "Pirouetting Bunny": 30, "Bird": 31, "Butler": 32,
    "Bouncing Ball": 33, "Waiter": 34, "Hunchback": 35, "Bell": 36,
    "Pheenix": 37, "Spinny Hook": 38, "Hammer": 39, "Camel": 40,
    "Dragon": 41, "Toilet Roll": 42, "Computer I": 43, "Pulsing Ball": 44,
    "Pulser Panel": 45, "Triangle": 46, "Cup and Saucer": 47, "Guard": 48,
    "Clockwork Robot": 49, "Skull": 50, "Peace Sign": 51, "Computer II": 52,
    "Toilet": 53, "Tribble": 54, "Slinky": 55, "Penguin": 56,
    "Bubble": 57, "Dish Robot": 58, "Hover Robot": 59, "Satellite": 60,
    "Monkey": 61, "Jetman": 62, "Jelly": 63, "Smiley": 64,
    "Man-eating Toilet": 65, "Sponge": 66, "Spear Hunter": 67,
    "Chandelier": 68, "Eye": 69, "Lift": 70,
    "Arrow I": 71, "Arrow II": 72,
    "Periscope Tank": 73, "Evil Head": 74,
    # Names used in original room data that map to the same tiles
    "Two Balls": 13,
    "Vertical Guardian": 58,      # Default to Dish Robot sprite
    "Horizontal Guardian": 58,    # Default to Dish Robot sprite
}

SKIP_ROOMS = {"Master Bedroom"}


# --- Parse original room data ---

def parse_room_data():
    """Parse the jsw_original_room_data.txt snapshot under _data/.

    Returns dict: room_name -> list of guardian dicts
    """
    rooms = {}
    current_room = None
    current_guardians = []

    with open(ROOM_DATA_FILE) as f:
        for line in f:
            line = line.rstrip('\n')

            # Room header
            m = re.match(r'Room \d+: (.+)', line)
            if m:
                if current_room:
                    rooms[current_room] = current_guardians
                current_room = m.group(1)
                current_guardians = []
                continue

            # Guardian lines
            line_stripped = line.strip()

            # Vertical: "Name    vertical    at (x, y)  route (x0,y0)-(x1,y1)"
            m = re.match(
                r'(\S.*?)\s{2,}vertical\s+at\s*\(\s*(\d+),\s*(\d+)\)\s+route\s*\(\s*(\d+),\s*(\d+)\)-\(\s*(\d+),\s*(\d+)\)',
                line_stripped
            )
            if m:
                current_guardians.append({
                    'name': m.group(1).strip(),
                    'type': 'vertical',
                    'x': int(m.group(2)), 'y': int(m.group(3)),
                    'x0': int(m.group(4)), 'y0': int(m.group(5)),
                    'x1': int(m.group(6)), 'y1': int(m.group(7)),
                })
                continue

            # Vertical stationary
            m = re.match(
                r'(\S.*?)\s{2,}vertical\s+at\s*\(\s*(\d+),\s*(\d+)\)\s+stationary',
                line_stripped
            )
            if m:
                x, y = int(m.group(2)), int(m.group(3))
                current_guardians.append({
                    'name': m.group(1).strip(),
                    'type': 'vertical',
                    'x': x, 'y': y,
                    'x0': x, 'y0': y, 'x1': x, 'y1': y,
                })
                continue

            # Horizontal: "Name    horizontal  at (x, y)  route (x0,y0)-(x1,y1)"
            m = re.match(
                r'(\S.*?)\s{2,}horizontal\s+at\s*\(\s*(\d+),\s*(\d+)\)\s+route\s*\(\s*(\d+),\s*(\d+)\)-\(\s*(\d+),\s*(\d+)\)',
                line_stripped
            )
            if m:
                current_guardians.append({
                    'name': m.group(1).strip(),
                    'type': 'horizontal',
                    'x': int(m.group(2)), 'y': int(m.group(3)),
                    'x0': int(m.group(4)), 'y0': int(m.group(5)),
                    'x1': int(m.group(6)), 'y1': int(m.group(7)),
                })
                continue

            # Arrow
            m = re.match(r'(Arrow.*?)\s{2,}arrow', line_stripped)
            if m:
                current_guardians.append({
                    'name': m.group(1).strip(),
                    'type': 'arrow',
                    'x': 0, 'y': 0,
                    'x0': 0, 'y0': 0, 'x1': 0, 'y1': 0,
                })
                continue

            # Rope
            m = re.match(r'(Rope.*?)\s{2,}rope\s+at\s+x=(\d+)', line_stripped)
            if m:
                x = int(m.group(2))
                current_guardians.append({
                    'name': m.group(1).strip(),
                    'type': 'rope',
                    'x': x, 'y': 0,
                    'x0': x, 'y0': 0, 'x1': x, 'y1': 0,
                })
                continue

    if current_room:
        rooms[current_room] = current_guardians

    return rooms


# --- TMX manipulation ---

def get_guardians_firstgid(root):
    """Get the firstgid for guardians.tsx from a TMX root."""
    for ts in root.findall('tileset'):
        src = ts.get('source', '')
        if 'guardians.tsx' in src:
            return int(ts.get('firstgid'))
    return None


def get_next_object_id(root):
    """Get the next available object ID."""
    return int(root.get('nextobjectid', '1'))


def get_max_layer_id(root):
    """Get the max layer/objectgroup ID in use."""
    max_id = 0
    for elem in root:
        lid = elem.get('id')
        if lid:
            max_id = max(max_id, int(lid))
    return max_id


def guardian_gid(name, firstgid):
    """Get the GID for a guardian by name."""
    tile_id = GUARDIAN_TILES.get(name)
    if tile_id is None:
        return None
    return firstgid + tile_id


def populate_room(tmx_path, guardians, dry_run=False):
    """Add guardians and routes to a gorgeous TMX file.

    Returns (num_guardians_added, warnings)
    """
    tree = ET.parse(tmx_path)
    root = tree.getroot()
    warnings = []

    firstgid = get_guardians_firstgid(root)
    if firstgid is None:
        return 0, ["No guardians.tsx tileset found"]

    # Filter to guardians we can place (skip arrows/ropes/unused for now)
    placeable = []
    for g in guardians:
        if g['type'] in ('arrow', 'rope'):
            continue
        if g['name'] == 'unused':
            continue
        gid = guardian_gid(g['name'], firstgid)
        if gid is None:
            warnings.append(f"Unknown guardian: {g['name']}")
            continue
        placeable.append((g, gid))

    if not placeable:
        return 0, warnings

    next_obj_id = get_next_object_id(root)
    max_layer_id = get_max_layer_id(root)

    # Find or create Enemies objectgroup
    enemies_og = None
    for og in root.findall('objectgroup'):
        if og.get('name') == 'Enemies':
            enemies_og = og
            break

    if enemies_og is None:
        warnings.append("No Enemies objectgroup found")
        return 0, warnings

    # Find insert position for Routes (after Enemies, before Spawn)
    children = list(root)
    enemies_idx = children.index(enemies_og)
    routes_insert_idx = enemies_idx + 1

    # Create Routes objectgroup
    routes_layer_id = max_layer_id + 1
    routes_og = ET.Element('objectgroup')
    routes_og.set('color', '#00ffff')
    routes_og.set('id', str(routes_layer_id))
    routes_og.set('name', 'Routes')
    routes_og.tail = '\n '

    guardian_count = 0
    for g, gid in placeable:
        guardian_obj_id = next_obj_id
        route_obj_id = next_obj_id + 1
        next_obj_id += 2

        # Guardian position: gid objects use bottom-left anchor
        # x_px = tile_x * 8, y_px = tile_y * 8 + sprite_height (16)
        gx = g['x'] * 8
        gy = g['y'] * 8 + 16

        # Create guardian object
        guardian_elem = ET.SubElement(enemies_og, 'object')
        guardian_elem.set('id', str(guardian_obj_id))
        guardian_elem.set('name', g['name'])
        guardian_elem.set('type', 'Guardian')
        guardian_elem.set('gid', str(gid))
        guardian_elem.set('x', str(gx))
        guardian_elem.set('y', str(gy))
        guardian_elem.set('width', '16')
        guardian_elem.set('height', '16')
        guardian_elem.text = '\n   '
        guardian_elem.tail = '\n  '

        props = ET.SubElement(guardian_elem, 'properties')
        props.text = '\n    '
        props.tail = '\n  '
        color_prop = ET.SubElement(props, 'property')
        color_prop.set('name', 'Color')
        color_prop.set('type', 'color')
        color_prop.set('value', '#ffffffff')
        color_prop.tail = '\n   '

        # Create route object (polyline format)
        if g['type'] == 'vertical':
            # Vertical: fixed x, patrols y range
            # Route polyline is vertical, centered on sprite
            route_x = g['x'] * 8 + 8      # sprite center x
            route_y = g['y0'] * 8 + 8     # sprite center y at start
            dy = (g['y1'] - g['y0']) * 8   # vertical extent
            polyline_str = f"0,0 0,{dy}"
            direction = 1  # Down
        else:
            # Horizontal: fixed y, patrols x range
            # Route polyline is horizontal, centered on sprite
            route_x = g['x0'] * 8         # patrol start x
            route_y = g['y'] * 8 + 8      # sprite center y
            dx = (g['x1'] - g['x0']) * 8  # horizontal extent
            polyline_str = f"0,0 {dx},0"
            direction = 2  # Left

        route_elem = ET.SubElement(routes_og, 'object')
        route_elem.set('id', str(route_obj_id))
        route_elem.set('type', 'Route')
        route_elem.set('x', str(route_x))
        route_elem.set('y', str(route_y))
        route_elem.text = '\n   '
        route_elem.tail = '\n  '

        route_props = ET.SubElement(route_elem, 'properties')
        route_props.text = '\n    '
        route_props.tail = '\n   '
        for pname, pval, ptype, pptype in [
            ('Direction', str(direction), 'int', 'Direction'),
            ('Guardian', str(guardian_obj_id), 'object', None),
            ('Speed', '1', 'int', 'Speed'),
            ('Traversal', '0', 'int', 'Traversal'),
        ]:
            p = ET.SubElement(route_props, 'property')
            p.set('name', pname)
            p.set('type', ptype)
            if pptype:
                p.set('propertytype', pptype)
            p.set('value', pval)
            p.tail = '\n    '
        # Fix last property tail
        list(route_props)[-1].tail = '\n   '

        polyline = ET.SubElement(route_elem, 'polyline')
        polyline.set('points', polyline_str)
        polyline.tail = '\n  '

        guardian_count += 1

    # Insert Routes objectgroup
    if guardian_count > 0:
        root.insert(routes_insert_idx, routes_og)

        # Update nextobjectid and nextlayerid
        root.set('nextobjectid', str(next_obj_id))
        root.set('nextlayerid', str(routes_layer_id + 1))

        if not dry_run:
            tree.write(tmx_path, encoding='unicode', xml_declaration=True)

    return guardian_count, warnings


def main():
    parser = argparse.ArgumentParser(description="Populate gorgeous TMX with guardians from original data")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    # Parse original room data
    room_data = parse_room_data()
    print(f"Parsed {len(room_data)} rooms from original data")

    # Build name -> gorgeous TMX path mapping
    # Use normalized whitespace for matching (some gorgeous rooms have extra spaces)
    gorgeous_rooms = {}       # display_name -> tmx_path
    gorgeous_norm_map = {}    # normalized_name -> display_name
    for filename in sorted(os.listdir(GORGEOUS_DIR)):
        if not filename.endswith('.tmx') or not filename[0].isdigit():
            continue
        tmx_path = os.path.join(GORGEOUS_DIR, filename)
        try:
            tree = ET.parse(tmx_path)
            root = tree.getroot()
            props = root.find('properties')
            if props is not None:
                for prop in props.findall('property'):
                    if prop.get('name') == 'Name':
                        room_name = prop.get('value', '').strip()
                        if room_name:
                            gorgeous_rooms[room_name] = tmx_path
                            norm_name = ' '.join(room_name.split())
                            gorgeous_norm_map[norm_name] = room_name
        except Exception as e:
            print(f"  Error parsing {filename}: {e}")

    print(f"Found {len(gorgeous_rooms)} gorgeous rooms")

    total_placed = 0
    all_warnings = []

    for room_name, tmx_path in sorted(gorgeous_rooms.items(), key=lambda x: x[1]):
        norm_name = ' '.join(room_name.split())
        if room_name in SKIP_ROOMS or norm_name in SKIP_ROOMS:
            print(f"  SKIP {os.path.basename(tmx_path)}: {room_name}")
            continue

        # Match by exact name first, then normalized whitespace
        guardians = room_data.get(room_name, [])
        if not guardians:
            guardians = room_data.get(norm_name, [])
        if not guardians:
            continue

        # Filter to non-arrow/rope guardians for count
        placeable_count = sum(1 for g in guardians
                              if g['type'] not in ('arrow', 'rope') and g['name'] != 'unused')
        if placeable_count == 0:
            continue

        count, warnings = populate_room(tmx_path, guardians, dry_run=args.dry_run)
        total_placed += count
        all_warnings.extend([(room_name, w) for w in warnings])

        status = "[DRY RUN]" if args.dry_run else "OK"
        print(f"  {status} {os.path.basename(tmx_path)}: {room_name} — {count} guardians")

    print(f"\nTotal: {total_placed} guardians placed")

    if all_warnings:
        print(f"\nWarnings ({len(all_warnings)}):")
        for room, w in all_warnings:
            print(f"  {room}: {w}")


if __name__ == "__main__":
    main()
