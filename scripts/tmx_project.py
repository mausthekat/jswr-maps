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

import json

from tmx_project_lib import (
    get_template_dir,
    get_tmx_dir,
    copy_templates,
    copy_extensions,
    bundle_extensions,
    update_project,
    find_all_projects,
)

def _make_empty_room_tmx(template_dir: Path, name: str = "Room 1") -> str:
    """Create an empty room TMX from the archetype template.

    Reads archetype.tmx from the template directory and substitutes the
    room name. The archetype contains the canonical tilesets, properties,
    and layer structure.
    """
    archetype = template_dir / "archetype.tmx"
    content = archetype.read_text()
    content = content.replace('value="Room 1"', f'value="{name}"')
    return content


def cmd_create(args) -> int:
    """Create a new project from the archetype."""
    name = args.name
    dry_run = args.dry_run
    template_dir = get_template_dir()
    if not dry_run:
        bundle_extensions(template_dir)
    tmx_dir = get_tmx_dir()

    # Validate project name
    if "/" in name or "\\" in name:
        print("Error: Project name cannot contain path separators")
        return 1

    # Determine target directory
    if args.location == "content":
        target_dir = tmx_dir / "content" / name
    else:
        target_dir = tmx_dir / "_in_progress" / name

    if target_dir.exists():
        print(f"Error: Directory already exists: {target_dir}")
        return 1

    print(f"{'[DRY RUN] ' if dry_run else ''}Creating project: {name}")
    print(f"  Location: {target_dir}")
    print()

    # Files to copy (with renaming and placeholder substitution)
    files_to_copy = [
        ("archetype.tiled-project", f"{name}.tiled-project"),
        ("archetype.world", f"{name}.world"),
    ]

    if dry_run:
        print("Would create directory structure:")
        print(f"  {target_dir}/")
        for src, dst in files_to_copy:
            print(f"    {dst}")
        print("    001.tmx  (empty room)")

        # Show templates
        src_templates = template_dir / "templates"
        if src_templates.exists():
            print("    templates/")
            for f in src_templates.rglob("*"):
                if f.is_file():
                    rel = f.relative_to(src_templates)
                    print(f"      {rel}")

        # Show extensions
        src_extensions = template_dir / ".extensions"
        if src_extensions.exists():
            print("    .extensions/")
            for f in src_extensions.rglob("*"):
                if f.is_file():
                    rel = f.relative_to(src_extensions)
                    print(f"      {rel}")

        return 0

    # Create target directory
    target_dir.mkdir(parents=True)

    # Copy and rename files with placeholder substitution.
    # The world file gets an initial room entry instead of an empty maps array.
    initial_world = json.dumps({
        "maps": [
            {"fileName": "001.tmx", "x": 0, "y": 0}
        ],
        "type": "world"
    }, indent=4) + "\n"

    for src_name, dst_name in files_to_copy:
        src_path = template_dir / src_name
        dst_path = target_dir / dst_name

        if src_path.exists():
            if src_name.endswith(".world"):
                # Use our initial world with room 001 placed at origin
                dst_path.write_text(initial_world)
            else:
                content = src_path.read_text()
                content = content.replace("{PROJECT_NAME}", name)
                dst_path.write_text(content)
            print(f"  Created: {dst_name}")

    # Create empty room 001.tmx from archetype
    room_path = target_dir / "001.tmx"
    room_path.write_text(_make_empty_room_tmx(template_dir, "Room 1"))
    print("  Created: 001.tmx")

    # Copy templates (with path adjustment)
    src_templates = template_dir / "templates"
    dst_templates = target_dir / "templates"
    changes = copy_templates(src_templates, dst_templates)
    if changes:
        print("  Copied:  templates/")

    # Copy extensions
    src_extensions = template_dir / ".extensions"
    dst_extensions = target_dir / ".extensions"
    changes = copy_extensions(src_extensions, dst_extensions)
    if changes:
        print("  Copied:  .extensions/")

    print()
    print("Project created successfully!")
    print(f"Open in Tiled: {target_dir / f'{name}.tiled-project'}")
    return 0


def cmd_update(args) -> int:
    """Update specific project(s)."""
    dry_run = args.dry_run
    if not dry_run:
        bundle_extensions(get_template_dir())
    success = True

    for path_str in args.paths:
        path = Path(path_str)
        project_name = path.name

        print(f"{'[DRY RUN] ' if dry_run else ''}Updating project: {project_name}")
        print(f"  Location: {path}")
        print()

        ok, changes = update_project(path, dry_run)
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


def cmd_refresh(args) -> int:
    """Update ALL projects (content + _in_progress)."""
    dry_run = args.dry_run

    # Bundle extensions-src/*.js into .extensions/jswr.js before deploying
    if not dry_run:
        bundle_extensions(get_template_dir())

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

        ok, changes = update_project(project_path, dry_run)
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
    p_update.set_defaults(func=cmd_update)

    # refresh
    p_refresh = subparsers.add_parser("refresh", help="Update ALL projects")
    p_refresh.add_argument("--dry-run", action="store_true",
                           help="Show what would be done without making changes")
    p_refresh.set_defaults(func=cmd_refresh)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
