#!/usr/bin/env python3
"""One-shot Speed-enum migration (May 2026).

Applies the lockstep migration documented in docs/GUARDIAN_SPEED_MAPPING.md:
  old Speed -> new Speed: {0:0, 1:4, 2:5, 3:6, 4:7, 5:8, 6:9, 7:10, 8:1}

For every project under tmx/content/* and tmx/_in_progress/*:
  1. Remap <property propertytype="Speed" value="N"/> in every .tmx/.tsx
     (do TMX FIRST so a mid-script crash leaves the project clearly half-done:
     a project's `.tiled-project` Speed enum is the migration marker, so
     leaving it on the OLD enum until the TMX rewrite finishes means a
     re-run correctly identifies the project as not-yet-migrated).
  2. Rewrite the Speed enum in <project>.tiled-project to the canonical
     13-value form AND remap any project-level Speed-typed properties.

Idempotent: skips a project whose `.tiled-project` Speed enum already has
13 entries with "1 (Very Slow)" at index 1.

Usage:
    python tmx/scripts/oneshot/migrate_speed_2025.py [--dry-run]

After running successfully, every TMX route will store its Speed value on
the new identity scale (Speed=N → N/2 px/tick of visible motion). Engine
table, archetype enum, and template defaults must already be on the new
scale (see plan + commit message).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# Old Speed value (units of `_SPEED_MOD_X4` in the eyeballed table)
# -> New Speed value (identity / JSW1-faithful table). Each old physical
# speed (px/tick) is preserved by remapping the stored integer.
REMAP: dict[int, int] = {
    0: 0,    # stationary (unchanged)
    1: 4,    # was 2.0 px/tick (Normal); new Speed=4 still 2 px/tick
    2: 5,    # was 2.5 px/tick
    3: 6,    # was 3.0 px/tick
    4: 7,    # was 3.5 px/tick
    5: 8,    # was 4.0 px/tick
    6: 9,    # was 4.5 px/tick
    7: 10,   # was 5.0 px/tick
    8: 1,    # was 0.5 px/tick (Very Slow); new Speed=1 still 0.5 px/tick
}

CANONICAL_VALUES = [
    "0",
    "1 (Very Slow)",
    "2",
    "3",
    "4 (Normal)",
    "5",
    "6",
    "7",
    "8 (Fast)",
    "9",
    "10",
    "11",
    "12 (Very Fast)",
]
# Idempotency sentinel - match the new label at the position that
# unambiguously identifies "this enum is post-migration".
SENTINEL_LABEL_AT_INDEX_1 = "1 (Very Slow)"

# Per-property regex. Tiled writes either:
#   <property name="Speed" type="int" propertytype="Speed" value="N"/>
# or attributes in a different order. Anchor on `propertytype="Speed"` so
# we never touch unrelated properties whose name happens to be "Speed".
TMX_PATTERN = re.compile(
    r'(<property\b[^>]*?\bpropertytype="Speed"[^>]*?\bvalue=")(\d+)(")'
)


def remap_value(n: int) -> int:
    """Apply the migration table. Values outside 0..8 (shouldn't appear in
    pre-migration data) pass through unchanged."""
    return REMAP.get(n, n)


def migrate_tmx_file(path: Path, dry_run: bool) -> int:
    """Returns count of values actually changed in this file."""
    text = path.read_text(encoding="utf-8")
    count = 0

    def sub(m: re.Match) -> str:
        nonlocal count
        old = int(m.group(2))
        new = remap_value(old)
        if new != old:
            count += 1
        return f"{m.group(1)}{new}{m.group(3)}"

    new_text = TMX_PATTERN.sub(sub, text)
    if new_text != text and not dry_run:
        path.write_text(new_text, encoding="utf-8")
    return count


def migrate_tiled_project(path: Path, dry_run: bool) -> tuple[bool, int]:
    """Returns (was_already_migrated, project_props_remapped).

    Rewrites the Speed enum to CANONICAL_VALUES and applies the value
    remap to any project-level Speed-typed properties.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    speed_type = next(
        (t for t in data.get("propertyTypes", []) if t.get("name") == "Speed"),
        None,
    )
    if speed_type is None:
        # No Speed type defined in this project - nothing to migrate.
        return True, 0

    values = speed_type.get("values", [])
    if (len(values) >= 2
            and values[1] == SENTINEL_LABEL_AT_INDEX_1
            and len(values) == len(CANONICAL_VALUES)):
        return True, 0  # already migrated

    speed_type["values"] = list(CANONICAL_VALUES)
    speed_type["storageType"] = "int"
    speed_type["valuesAsFlags"] = False

    remapped = 0
    for prop in data.get("properties", []):
        if (prop.get("propertytype") == "Speed"
                and prop.get("type") == "int"):
            old = int(prop.get("value", 0))
            new = remap_value(old)
            if new != old:
                prop["value"] = new
                remapped += 1

    if not dry_run:
        path.write_text(
            json.dumps(data, indent=4) + "\n",
            encoding="utf-8",
        )
    return False, remapped


def project_already_migrated(path: Path) -> bool:
    """Read-only check - does the project's `.tiled-project` already have
    the post-migration Speed enum?"""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    speed_type = next(
        (t for t in data.get("propertyTypes", []) if t.get("name") == "Speed"),
        None,
    )
    if speed_type is None:
        return True  # no enum to migrate
    values = speed_type.get("values", [])
    return (len(values) >= 2
            and values[1] == SENTINEL_LABEL_AT_INDEX_1
            and len(values) == len(CANONICAL_VALUES))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true",
                    help="Report what would change without writing.")
    args = ap.parse_args()

    tmx_root = Path(__file__).resolve().parent.parent.parent
    project_dirs = sorted(
        list((tmx_root / "content").iterdir())
        + list((tmx_root / "_in_progress").iterdir())
    )

    total_tmx = 0
    total_props = 0
    skipped = 0
    migrated = 0
    no_project_file = 0

    for proj in project_dirs:
        if not proj.is_dir():
            continue
        proj_files = list(proj.glob("*.tiled-project"))
        if not proj_files:
            no_project_file += 1
            continue

        if project_already_migrated(proj_files[0]):
            print(f"  {proj.name}: already migrated, skipping")
            skipped += 1
            continue

        # Phase 1 (per project): remap TMX/TSX FIRST so a partial failure
        # leaves the .tiled-project on the OLD enum (= "not migrated"),
        # making a re-run correctly retry from scratch.
        tmx_count = 0
        for tmx in list(proj.rglob("*.tmx")) + list(proj.rglob("*.tsx")):
            if "templates" in tmx.parts:
                continue  # template copies are owned by the archetype
            tmx_count += migrate_tmx_file(tmx, args.dry_run)

        # Phase 2 (per project): rewrite the .tiled-project - the enum
        # update + any project-level Speed property remaps. This is the
        # commit-marker that flips the project's idempotency state.
        _, prop_count = migrate_tiled_project(proj_files[0], args.dry_run)

        total_tmx += tmx_count
        total_props += prop_count
        migrated += 1
        print(f"  {proj.name}: enum updated, "
              f"{tmx_count} TMX values + {prop_count} project props remapped")

    print()
    print(f"Done. {migrated} project(s) migrated, "
          f"{skipped} already done, "
          f"{no_project_file} dir(s) without `.tiled-project`.")
    print(f"      {total_tmx} TMX values + {total_props} project props remapped.")
    if args.dry_run:
        print("      (dry-run - no files written)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
