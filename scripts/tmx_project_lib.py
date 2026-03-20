#!/usr/bin/env python3
"""
Shared library for TMX project management.

Provides reusable functions for creating, updating, and maintaining
Tiled map projects from the project-template archetype.
"""

import json
import os
import re
import shutil
from pathlib import Path


def get_tmx_dir() -> Path:
    """Return the path to the tmx directory."""
    return Path(__file__).parent.parent


def get_template_dir() -> Path:
    """Return the path to the project-template directory."""
    return get_tmx_dir() / "project-template"


def get_tilesets_dir() -> Path:
    """Return the path to the tmx/tilesets directory."""
    return get_tmx_dir() / "tilesets"


def adjust_tileset_paths(content: str, dest_templates_dir: Path) -> str:
    """
    Rewrite tileset source paths in template XML content.

    Replaces source="<anything>/tilesets/..." with the correct relative path
    from dest_templates_dir back to tmx/tilesets/.

    Args:
        content: XML template file content
        dest_templates_dir: The destination templates directory (resolved/absolute)

    Returns:
        Content with adjusted tileset paths
    """
    tilesets_dir = get_tilesets_dir().resolve()
    dest_resolved = dest_templates_dir.resolve()
    rel_path = os.path.relpath(tilesets_dir, dest_resolved)

    # Replace source="<prefix>/tilesets/<rest>" with source="<rel_path>/<rest>"
    # This handles paths like ../tilesets/meta/meta_markers.tsx
    def replace_source(match):
        rest = match.group(1)
        return f'source="{rel_path}/{rest}"'

    return re.sub(r'source="[^"]*?/tilesets/([^"]*)"', replace_source, content)


def copy_templates(src_dir: Path, dst_dir: Path, dry_run: bool = False) -> list[str]:
    """
    Copy template files from src_dir to dst_dir with tileset path adjustment.

    Files are read as text, paths are adjusted for the destination location,
    then compared to existing files. Only changed files are written.

    Args:
        src_dir: Source templates directory (e.g. project-template/templates/)
        dst_dir: Destination templates directory (e.g. content/main/templates/)
        dry_run: If True, only report what would change

    Returns:
        List of change descriptions
    """
    changes = []

    if not src_dir.exists():
        return changes

    if not dst_dir.exists():
        if dry_run:
            changes.append(f"Would create templates directory: {dst_dir}")
            for src_file in src_dir.rglob("*"):
                if src_file.is_file():
                    rel = src_file.relative_to(src_dir)
                    changes.append(f"  Would copy: {rel}")
        else:
            dst_dir.mkdir(parents=True, exist_ok=True)
            for src_file in src_dir.rglob("*"):
                if src_file.is_file():
                    rel = src_file.relative_to(src_dir)
                    dst_file = dst_dir / rel
                    dst_file.parent.mkdir(parents=True, exist_ok=True)
                    src_content = src_file.read_text()
                    adjusted = adjust_tileset_paths(src_content, dst_dir)
                    dst_file.write_text(adjusted)
                    changes.append(f"Template created: {rel}")
        return changes

    # Compare and update existing files
    for src_file in src_dir.rglob("*"):
        if src_file.is_file():
            rel = src_file.relative_to(src_dir)
            dst_file = dst_dir / rel

            src_content = src_file.read_text()
            adjusted = adjust_tileset_paths(src_content, dst_dir)

            if dst_file.exists():
                dst_content = dst_file.read_text()
                if adjusted == dst_content:
                    continue

            changes.append(f"Template updated: {rel}")
            if not dry_run:
                dst_file.parent.mkdir(parents=True, exist_ok=True)
                dst_file.write_text(adjusted)

    return changes


def copy_extensions(src_dir: Path, dst_dir: Path, dry_run: bool = False) -> list[str]:
    """
    Copy extension files from src_dir to dst_dir with diff comparison.

    Only changed files are written.

    Args:
        src_dir: Source extensions directory (e.g. project-template/.extensions/)
        dst_dir: Destination extensions directory (e.g. content/main/.extensions/)
        dry_run: If True, only report what would change

    Returns:
        List of change descriptions
    """
    changes = []

    if not src_dir.exists():
        return changes

    if not dst_dir.exists():
        if dry_run:
            changes.append(f"Would create .extensions directory: {dst_dir}")
            for src_file in src_dir.rglob("*"):
                if src_file.is_file():
                    rel = src_file.relative_to(src_dir)
                    changes.append(f"  Would copy: {rel}")
        else:
            shutil.copytree(src_dir, dst_dir)
            changes.append(".extensions directory created")
        return changes

    # Compare and update existing files
    for src_file in src_dir.rglob("*"):
        if src_file.is_file():
            rel = src_file.relative_to(src_dir)
            dst_file = dst_dir / rel

            src_content = src_file.read_bytes()
            dst_content = dst_file.read_bytes() if dst_file.exists() else b""

            if src_content != dst_content:
                changes.append(f"Extension updated: {rel}")
                if not dry_run:
                    dst_file.parent.mkdir(parents=True, exist_ok=True)
                    dst_file.write_bytes(src_content)

    return changes


def merge_property_types(existing: list, archetype: list) -> tuple[list, list]:
    """
    Merge archetype property types into existing list.

    Adds missing types and extends existing flags enum values when the archetype
    has additional entries (only appends — never reorders or removes).

    Returns:
        Tuple of (merged list, list of change descriptions)
    """
    existing_by_name = {t["name"]: t for t in existing}
    changes = []
    max_id = max((t.get("id", 0) for t in existing), default=0)

    for arch_type in archetype:
        name = arch_type["name"]
        if name not in existing_by_name:
            # New type — add it
            max_id += 1
            new_type = arch_type.copy()
            new_type["id"] = max_id
            existing.append(new_type)
            changes.append(name)
        else:
            # Existing type — check if enum values need extending
            existing_type = existing_by_name[name]
            if (existing_type.get("type") == "enum"
                    and "values" in existing_type
                    and "values" in arch_type):
                existing_values = existing_type["values"]
                arch_values = arch_type["values"]
                # Only extend if archetype has more values and existing is a prefix
                if (len(arch_values) > len(existing_values)
                        and arch_values[:len(existing_values)] == existing_values):
                    new_values = arch_values[len(existing_values):]
                    existing_type["values"] = arch_values
                    changes.append(f"{name} +{','.join(new_values)}")

    return existing, changes


def find_all_projects() -> list[Path]:
    """
    Find all project folders (content + _in_progress) with .world files.

    Returns:
        Sorted list of project directory paths
    """
    tmx_dir = get_tmx_dir()
    projects = []

    for search_dir in [tmx_dir / "content", tmx_dir / "_in_progress"]:
        if not search_dir.is_dir():
            continue
        for entry in sorted(search_dir.iterdir()):
            if entry.is_dir():
                world_files = list(entry.glob("*.world"))
                if world_files:
                    projects.append(entry)

    return sorted(projects)


def update_project(project_path: Path, dry_run: bool = False) -> tuple[bool, list[str]]:
    """
    Update an existing project with latest archetype files.

    Updates templates (with path adjustment), extensions, and property types.

    Args:
        project_path: Path to the project directory
        dry_run: If True, only show what would be done

    Returns:
        Tuple of (success, list of change descriptions)
    """
    template_dir = get_template_dir()
    changes = []

    if not project_path.is_dir():
        return False, [f"Error: Not a directory: {project_path}"]

    # Find .tiled-project file
    project_files = list(project_path.glob("*.tiled-project"))
    if not project_files:
        return False, [f"Error: No .tiled-project file found in {project_path}"]

    project_file = project_files[0]

    # 1. Merge property types in .tiled-project
    archetype_project = template_dir / "archetype.tiled-project"
    if archetype_project.exists():
        with open(archetype_project, encoding="utf-8") as f:
            archetype_data = json.load(f)

        try:
            with open(project_file, encoding="utf-8") as f:
                project_data = json.load(f)
        except UnicodeDecodeError as e:
            # Debug: show which file and its raw bytes around the error
            raw = open(project_file, "rb").read()
            pos = e.start
            print(f"  ERROR reading {project_file}: {e}")
            print(f"  Raw bytes around pos {pos}: {raw[max(0,pos-10):pos+10].hex(' ')}")
            raise

        existing_types = project_data.get("propertyTypes", [])
        archetype_types = archetype_data.get("propertyTypes", [])

        merged, added = merge_property_types(existing_types, archetype_types)

        if added:
            changes.append(f"Property types added: {', '.join(added)}")
            if not dry_run:
                project_data["propertyTypes"] = merged
                with open(project_file, "w", encoding="utf-8") as f:
                    json.dump(project_data, f, indent=4)
                    f.write("\n")

    # 2. Update extensions
    src_extensions = template_dir / ".extensions"
    dst_extensions = project_path / ".extensions"
    changes.extend(copy_extensions(src_extensions, dst_extensions, dry_run))

    # 3. Update templates (with path adjustment)
    src_templates = template_dir / "templates"
    dst_templates = project_path / "templates"
    changes.extend(copy_templates(src_templates, dst_templates, dry_run))

    return True, changes
