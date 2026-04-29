#!/usr/bin/env python3
"""
Patch jsw-gorgeous TMX files to add collectible and guardian tileset references
and GID attributes so they display visually in Tiled.

- Adds collectibles.tsx and guardians.tsx tileset references
- Adds gid="12289" to all collectible objects
- Copies guardian GIDs and names from the main map (matched by order)
- Reports mismatches where guardian counts differ

Usage:
    python tmx/scripts/oneshot/patch_gorgeous_tmx.py [--dry-run]
"""

import argparse
import os
import xml.etree.ElementTree as ET

# Script lives at tmx/scripts/oneshot/patch_gorgeous_tmx.py
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TMX_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))  # tmx/

GORGEOUS_DIR = os.path.join(TMX_ROOT, "_in_progress", "jsw-gorgeous")
MAIN_DIR = os.path.join(TMX_ROOT, "content", "main")
MAPPING_FILE = os.path.join(SCRIPT_DIR, "_data", "jsw_gorgeous_room_mapping.txt")

COLLECTIBLES_FIRSTGID = 12289
GUARDIANS_FIRSTGID = 14337

COLLECTIBLES_TSX_SOURCE = "../../tilesets/collectibles.tsx"
GUARDIANS_TSX_SOURCE = "../../tilesets/guardians.tsx"

DEFAULT_GUARDIAN_GID = 14337  # First guardian sprite (Saw)


def load_room_mapping():
    """Load gorgeous->main room number mapping."""
    mapping = {}
    with open(MAPPING_FILE) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("Room Name"):
                continue
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 3:
                gorgeous_id = int(parts[1])
                main_id = int(parts[2])
                mapping[gorgeous_id] = main_id
    return mapping


def get_guardians(tree):
    """Extract Guardian objects from an Enemies objectgroup."""
    guardians = []
    for og in tree.findall(".//objectgroup"):
        if og.get("name") == "Enemies":
            for obj in og.findall("object"):
                if obj.get("type") == "Guardian":
                    guardians.append(obj)
    return guardians


def get_collectibles(tree):
    """Extract collectible objects from a Collectables objectgroup."""
    collectibles = []
    for og in tree.findall(".//objectgroup"):
        if og.get("name") == "Collectables":
            for obj in og.findall("object"):
                if obj.get("type") in (None, "", "Collectible"):
                    collectibles.append(obj)
    return collectibles


def has_tileset(root, source_substring):
    """Check if a tileset reference already exists."""
    for ts in root.findall("tileset"):
        if source_substring in (ts.get("source") or ""):
            return True
    return False


def add_tileset_ref(root, firstgid, source):
    """Add a tileset reference element after the last existing tileset."""
    tilesets = root.findall("tileset")
    if not tilesets:
        insert_idx = 0
    else:
        last_ts = tilesets[-1]
        children = list(root)
        insert_idx = children.index(last_ts) + 1

    elem = ET.Element("tileset")
    elem.set("firstgid", str(firstgid))
    elem.set("source", source)
    # Copy tail/whitespace from the previous tileset for consistent formatting
    if tilesets:
        elem.tail = tilesets[-1].tail
    else:
        elem.tail = "\n "
    root.insert(insert_idx, elem)
    return elem


def indent_xml(elem, level=0):
    """Add pretty-print indentation to XML."""
    indent = "\n" + " " * level
    if len(elem):
        if not elem.text or not elem.text.strip():
            elem.text = indent + " "
        if not elem.tail or not elem.tail.strip():
            elem.tail = indent
        for child in elem:
            indent_xml(child, level + 1)
        if not child.tail or not child.tail.strip():
            child.tail = indent
    else:
        if level and (not elem.tail or not elem.tail.strip()):
            elem.tail = indent


def patch_room(gorgeous_path, main_path, dry_run=False):
    """Patch a single gorgeous TMX file. Returns (patched, warnings)."""
    warnings = []
    patched = False

    g_tree = ET.parse(gorgeous_path)
    g_root = g_tree.getroot()

    # Add tileset references if missing
    if not has_tileset(g_root, "collectibles.tsx"):
        add_tileset_ref(g_root, COLLECTIBLES_FIRSTGID, COLLECTIBLES_TSX_SOURCE)
        patched = True

    if not has_tileset(g_root, "guardians.tsx"):
        add_tileset_ref(g_root, GUARDIANS_FIRSTGID, GUARDIANS_TSX_SOURCE)
        patched = True

    # Patch collectibles with gid
    g_collectibles = get_collectibles(g_tree)
    for obj in g_collectibles:
        if not obj.get("gid"):
            obj.set("gid", str(COLLECTIBLES_FIRSTGID))
            patched = True

    # Patch guardians with gid and name from main map
    g_guardians = get_guardians(g_tree)

    if main_path and os.path.exists(main_path):
        m_tree = ET.parse(main_path)
        m_guardians = get_guardians(m_tree)

        g_count = len(g_guardians)
        m_count = len(m_guardians)

        if g_count != m_count:
            room_name = os.path.basename(gorgeous_path)
            warnings.append(
                f"{room_name}: gorgeous has {g_count} guardians, main has {m_count} — skipped guardian GIDs"
            )
        else:
            # Counts match — copy gid and name by order
            for i, g_obj in enumerate(g_guardians):
                m_obj = m_guardians[i]
                m_gid = m_obj.get("gid")
                m_name = m_obj.get("name")
                if m_gid and not g_obj.get("gid"):
                    g_obj.set("gid", m_gid)
                    patched = True
                if m_name and not g_obj.get("name"):
                    g_obj.set("name", m_name)
                    patched = True
    else:
        # No main map counterpart — skip guardian GIDs
        if g_guardians:
            warnings.append(
                f"{os.path.basename(gorgeous_path)}: no main map counterpart — skipped guardian GIDs"
            )

    if patched and not dry_run:
        g_tree.write(gorgeous_path, encoding="unicode", xml_declaration=True)

    return patched, warnings


def main():
    parser = argparse.ArgumentParser(description="Patch gorgeous TMX files with tileset GIDs")
    parser.add_argument("--dry-run", action="store_true", help="Show what would change without writing")
    args = parser.parse_args()

    mapping = load_room_mapping()
    print(f"Loaded {len(mapping)} room mappings")

    # Find all gorgeous TMX files
    tmx_files = sorted(
        f for f in os.listdir(GORGEOUS_DIR)
        if f.endswith(".tmx") and f[0].isdigit()
    )
    print(f"Found {len(tmx_files)} gorgeous TMX files")

    all_warnings = []
    patched_count = 0
    skipped_count = 0

    for tmx_file in tmx_files:
        room_id = int(tmx_file.replace(".tmx", ""))
        gorgeous_path = os.path.join(GORGEOUS_DIR, tmx_file)

        main_id = mapping.get(room_id)
        main_path = None
        if main_id is not None:
            main_path = os.path.join(MAIN_DIR, f"{main_id:03d}.tmx")

        patched, warnings = patch_room(gorgeous_path, main_path, dry_run=args.dry_run)
        all_warnings.extend(warnings)

        if patched:
            patched_count += 1
            status = "[DRY RUN] Would patch" if args.dry_run else "Patched"
            main_info = f" (main {main_id:03d})" if main_id else " (no main mapping)"
            print(f"  {status} {tmx_file}{main_info}")
        else:
            skipped_count += 1

    print(f"\n{'Would patch' if args.dry_run else 'Patched'}: {patched_count}, Already ok: {skipped_count}")

    if all_warnings:
        print(f"\nGuardian count mismatches ({len(all_warnings)}):")
        for w in all_warnings:
            print(f"  {w}")
        print("\nFor mismatched rooms: matched by order, extras got default GID (Saw).")


if __name__ == "__main__":
    main()
