#!/usr/bin/env python3
"""
Consolidated TMX project management.

Subcommands:
    create <name>                       Create a new project from the archetype
    update <path> [<path>...]           Update specific project(s)
    refresh                             Update ALL projects (content + _in_progress)

Examples:
    python tmx/scripts/tmx_project.py create my-map
    python tmx/scripts/tmx_project.py create my-map --location content
    python tmx/scripts/tmx_project.py update tmx/content/main
    python tmx/scripts/tmx_project.py update tmx/content/rj-* tmx/_in_progress/jsw-gorgeous
    python tmx/scripts/tmx_project.py refresh
    python tmx/scripts/tmx_project.py refresh --dry-run
"""

import argparse
import sys
from pathlib import Path

from tmx_project_lib import (
    get_template_dir,
    get_tmx_dir,
    update_project,
    find_all_projects,
    scaffold_project,
    bundle_extensions,
    sync_tune_select_enum,
    set_project_tune,
    GAMINGLOUNGE_PROJECT,
)


def cmd_create(args: argparse.Namespace) -> int:
    """Create a new project from the archetype."""
    name = args.name
    dry_run = args.dry_run
    tmx_dir = get_tmx_dir()
    target_dir = (tmx_dir / "content" / name) if args.location == "content" else (
        tmx_dir / "_in_progress" / name
    )

    print(f"{'[DRY RUN] ' if dry_run else ''}Creating project: {name}")
    print(f"  Location: {target_dir}")
    print()

    if dry_run:
        if target_dir.exists():
            print(f"Error: Directory already exists: {target_dir}")
            return 1
        template_dir = get_template_dir()
        print("Would create directory structure:")
        print(f"  {target_dir}/")
        print(f"    {name}.tiled-project")
        print(f"    {name}.world")
        print("    001.tmx  (empty room)")
        for sub in ("templates", ".extensions"):
            src = template_dir / sub
            if src.exists():
                print(f"    {sub}/")
                for f in src.rglob("*"):
                    if f.is_file():
                        print(f"      {f.relative_to(src)}")
        return 0

    target_dir = scaffold_project(name, location=args.location, force=False)
    for fname in (f"{name}.tiled-project", f"{name}.world", "001.tmx",
                  "templates", ".extensions"):
        if (target_dir / fname).exists():
            print(f"  Created: {fname}")

    print()
    print("Project created successfully!")
    print(f"Open in Tiled: {target_dir / f'{name}.tiled-project'}")
    return 0


def cmd_update(args: argparse.Namespace) -> int:
    """Update specific project(s)."""
    dry_run = args.dry_run
    prune = args.prune
    if not dry_run:
        bundle_extensions(get_template_dir())
    success = True

    for path_str in args.paths:
        path = Path(path_str)
        project_name = path.name

        print(f"{'[DRY RUN] ' if dry_run else ''}Updating project: {project_name}")
        print(f"  Location: {path}")
        print()

        ok, changes = update_project(path, dry_run, prune=prune)
        if not ok:
            for msg in changes:
                print(msg)
            success = False
            continue

        if changes:
            print("Changes:")
            for change in changes:
                print(f"  - {change}")
        else:
            print("No changes needed - project is up to date.")
        print()

    return 0 if success else 1


def cmd_refresh(args: argparse.Namespace) -> int:
    """Update ALL projects (content + _in_progress)."""
    dry_run = args.dry_run
    prune = args.prune

    # Bundle extensions-src/*.js into .extensions/jswr.js before deploying
    if not dry_run:
        bundle_extensions(get_template_dir())

    # Sync the map tune-select enum from the build-tunes manifest into the
    # archetype BEFORE propagating, so the per-project merge picks it up.
    lobby_idx: int | None = None
    ingame_idx = 0
    try:
        tune_changes, ingame_idx, lobby_idx = sync_tune_select_enum(dry_run)
        for c in tune_changes:
            print(f"{'[DRY RUN] ' if dry_run else ''}archetype: {c}")
        if tune_changes:
            print()
    except FileNotFoundError:
        print("Note: assets/tunes/__tune_codes.json not found - skipping tune "
              "enum sync (run the build-tunes pipeline first).\n")

    projects = find_all_projects()

    if not projects:
        print("No projects found.")
        return 0

    print(f"Found {len(projects)} project(s) to refresh:\n")

    all_ok = True
    total_changes = 0

    for project_path in projects:
        project_name = project_path.name
        print(f"{'[DRY RUN] ' if dry_run else ''}Updating: {project_name}")

        ok, changes = update_project(project_path, dry_run, prune=prune)
        if not ok:
            for msg in changes:
                print(f"  {msg}")
            all_ok = False
            continue

        if changes:
            for change in changes:
                print(f"  - {change}")
            total_changes += len(changes)
        else:
            print("  Up to date.")
        print()

    # The lobby (_gaminglounge) plays the lobby tune, not the gameplay default.
    # Apply it only where the map is still at the gameplay default, so a
    # hand-picked tune is preserved.
    if lobby_idx is not None:
        gl = get_tmx_dir() / "content" / GAMINGLOUNGE_PROJECT
        if gl.is_dir():
            for c in set_project_tune(gl, lobby_idx, ingame_idx, dry_run):
                print(f"{'[DRY RUN] ' if dry_run else ''}{GAMINGLOUNGE_PROJECT}: {c}")

    print(f"Done! Processed {len(projects)} project(s), {total_changes} change(s).")
    return 0 if all_ok else 1


def main():
    parser = argparse.ArgumentParser(
        description="Consolidated TMX project management.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s create my-map
  %(prog)s create my-map --location content
  %(prog)s update tmx/content/main
  %(prog)s update tmx/content/rj-* tmx/_in_progress/jsw-gorgeous
  %(prog)s refresh
  %(prog)s refresh --dry-run
"""
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # create
    p_create = subparsers.add_parser("create", help="Create a new project from the archetype")
    p_create.add_argument("name", help="Project name")
    p_create.add_argument("--location", choices=["content", "in_progress"],
                          default="in_progress",
                          help="Where to create (default: in_progress)")
    p_create.add_argument("--dry-run", action="store_true",
                          help="Show what would be done without making changes")
    p_create.set_defaults(func=cmd_create)

    # update
    p_update = subparsers.add_parser("update", help="Update specific project(s)")
    p_update.add_argument("paths", nargs="+",
                          help="Project path(s). Shell wildcards expand to multiple paths.")
    p_update.add_argument("--dry-run", action="store_true",
                          help="Show what would be done without making changes")
    p_update.add_argument("--prune", action="store_true",
                          help="Remove propertyTypes not in the archetype. "
                               "Without this flag, stale types are reported "
                               "as WARNINGs but left in place.")
    p_update.set_defaults(func=cmd_update)

    # refresh
    p_refresh = subparsers.add_parser("refresh", help="Update ALL projects")
    p_refresh.add_argument("--dry-run", action="store_true",
                           help="Show what would be done without making changes")
    p_refresh.add_argument("--prune", action="store_true",
                           help="Remove propertyTypes not in the archetype. "
                                "Without this flag, stale types are reported "
                                "as WARNINGs but left in place.")
    p_refresh.set_defaults(func=cmd_refresh)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
