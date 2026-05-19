#!/usr/bin/env python3
"""Rename jsw1-e tileset PNG files to use the new room numbers.

The jsw1-e tilesets use "Old" room numbers in their filenames, but should use
the "New" room numbers according to the old-to-new-mappings.txt file.

Usage:
    python tmx/scripts/oneshot/rename_jsw1_e_tilesets.py [--dry-run]

With --dry-run, shows what would be renamed without making changes.
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import sys
from pathlib import Path


def parse_mapping_file(path: Path) -> dict[int, int]:
    """Parse the old-to-new-mappings.txt file.

    Returns a dict mapping Old room numbers -> New room numbers.
    """
    mapping: dict[int, int] = {}
    with path.open(encoding="utf-8") as f:
        reader = csv.reader(f)
        next(reader, None)  # Skip header
        for row in reader:
            if len(row) >= 3:
                new = int(row[1].strip())
                old = int(row[2].strip())
                mapping[old] = new
    return mapping


def rename_files(dry_run: bool) -> tuple[int, int]:
    """Rename tileset files from Old to New room numbers.

    Returns (changed_count, total_count).
    """
    tmx_root = Path(__file__).resolve().parent.parent.parent
    mapping_file = tmx_root / "scripts" / "oneshot" / "_data" / "jsw-gorgeous-old-to-new-mappings.txt"
    jsw1_e_dir = tmx_root / "content" / "jsw-gorgeous" / "tilesets" / "jsw1-e"
    corrected_dir = jsw1_e_dir / "corrected"

    # Parse the mapping
    mapping = parse_mapping_file(mapping_file)

    # Regex to match tileset files with room numbers
    # Pattern: tiles_<type>_jsw1-e_<room_number>.png
    pattern = re.compile(r"^(tiles_\w+_jsw1-e_)(\d+)(\.png)$")

    os.makedirs(corrected_dir, exist_ok=True)

    changed_count = 0
    total_count = 0

    for filepath in jsw1_e_dir.iterdir():
        if not filepath.is_file():
            continue

        match = pattern.match(filepath.name)
        if not match:
            continue

        total_count += 1
        prefix = match.group(1)
        old_room_str = match.group(2)  # Keep original string for padding
        old_room = int(old_room_str)
        suffix = match.group(3)

        # Look up the new room number
        new_room = mapping.get(old_room)
        if new_room is None:
            print(f"  WARNING: No mapping for Old room {old_room} ({filepath.name})")
            continue

        # Preserve original padding (3 digits)
        new_room_str = str(new_room).zfill(len(old_room_str))
        # Construct new filename
        new_name = f"{prefix}{new_room_str}{suffix}"
        new_path = corrected_dir / new_name

        print(f"  {old_room:3d} -> {new_room:3d}: {filepath.name} -> {new_name}")

        if not dry_run:
            # Copy file to corrected folder
            import shutil
            shutil.copy2(filepath, new_path)

        changed_count += 1

    return changed_count, total_count


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="Show what would be changed without making changes.")
    args = ap.parse_args()

    print("Renaming jsw1-e tileset files to use new room numbers...")
    print()

    changed_count, total_count = rename_files(args.dry_run)

    print()
    print(f"Total files processed: {total_count}")
    print(f"Files renamed: {changed_count}")

    if args.dry_run:
        print("  (dry-run - no files changed)")

    return 0


if __name__ == "__main__":
    sys.exit(main())