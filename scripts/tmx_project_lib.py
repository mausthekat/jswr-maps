#!/usr/bin/env python3
"""
Shared library for TMX project management.

Provides reusable functions for creating, updating, and maintaining
Tiled map projects from the project-template archetype.
"""

import copy
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


def merge_properties(existing: list, archetype: list) -> tuple[list, list, list]:
    """
    Merge archetype project properties into existing list.

    Adds missing properties with their default values. Removes properties
    that exist in the project but not in the archetype. Never modifies
    existing property values.

    Returns:
        Tuple of (merged list, list of added property names, list of removed property names)
    """
    existing_by_name = {p["name"] for p in existing}
    archetype_by_name = {p["name"] for p in archetype}
    added = []
    removed = []

    # Add missing properties from archetype
    for arch_prop in archetype:
        name = arch_prop["name"]
        if name not in existing_by_name:
            existing.append(arch_prop.copy())
            added.append(name)

    # Remove properties not in archetype
    to_remove = [p for p in existing if p["name"] not in archetype_by_name]
    for prop in to_remove:
        existing.remove(prop)
        removed.append(prop["name"])

    return existing, added, removed


def merge_property_types(existing: list, archetype: list) -> tuple[list, list, list]:
    """
    Harmonize property types to match archetype exactly.

    The archetype is fully authoritative for:
    - Property type IDs
    - Enum values and ordering
    - Class members (adds missing, doesn't remove extras)

    Returns:
        Tuple of (merged_types, change_descriptions, tmx_remaps)
        tmx_remaps: list of dicts describing enum value remappings needed for TMX/TSX files
    """
    archetype_by_name = {t["name"]: t for t in archetype}
    existing_by_name = {t["name"]: t for t in existing}
    changes = []
    tmx_remaps = []

    for existing_type in existing:
        name = existing_type["name"]
        if name not in archetype_by_name:
            continue  # Keep project-specific types as-is

        arch_type = archetype_by_name[name]

        # ID harmonization
        old_id = existing_type.get("id")
        new_id = arch_type.get("id")
        if old_id != new_id and new_id is not None:
            existing_type["id"] = new_id
            changes.append(f"Remapped {name} id {old_id} → {new_id}")

        # Enum value harmonization
        if (existing_type.get("type") == "enum"
                and "values" in existing_type
                and "values" in arch_type):
            old_values = existing_type["values"]
            new_values = arch_type["values"]

            if old_values != new_values:
                is_flags = arch_type.get("valuesAsFlags", False)
                storage_type = arch_type.get("storageType", "string")

                # Build remap info BEFORE updating values
                remap_data = _build_enum_remap(
                    old_values, new_values, is_flags, storage_type
                )
                if remap_data:
                    tmx_remaps.append({
                        "property_type_name": name,
                        "remap_data": remap_data,
                    })

                # Update values to match archetype
                existing_type["values"] = list(new_values)

                # Sync other enum fields
                for field in ("valuesAsFlags", "storageType"):
                    if field in arch_type:
                        existing_type[field] = arch_type[field]

                # Build change description
                removed = [v for v in old_values if v not in new_values]
                added = [v for v in new_values if v not in old_values]
                desc_parts = []
                if removed:
                    desc_parts.append(f"removed {','.join(removed)}")
                if added:
                    desc_parts.append(f"added {','.join(added)}")
                if not removed and not added:
                    desc_parts.append("reordered")
                changes.append(f"Updated {name} values ({'; '.join(desc_parts)})")

        # Class member harmonization (add missing, don't remove extras)
        if existing_type.get("type") == "class" and "members" in arch_type:
            existing_members = {m["name"] for m in existing_type.get("members", [])}
            added_members = []

            for arch_member in arch_type["members"]:
                if arch_member["name"] not in existing_members:
                    existing_type.setdefault("members", []).append(
                        copy.deepcopy(arch_member)
                    )
                    added_members.append(arch_member["name"])

            if added_members:
                changes.append(
                    f"Added {', '.join(added_members)} member(s) to {name}"
                )

    # Add missing types from archetype (with archetype IDs)
    for arch_type in archetype:
        name = arch_type["name"]
        if name not in existing_by_name:
            existing.append(copy.deepcopy(arch_type))
            changes.append(f"Added property type: {name}")

    return existing, changes, tmx_remaps


def _build_enum_remap(
    old_values: list[str],
    new_values: list[str],
    is_flags: bool,
    storage_type: str,
) -> dict | None:
    """
    Build remapping info for enum value changes.

    Returns None if no remapping is needed (values are a prefix of archetype).
    """
    # If old values are a prefix of new, positions haven't changed — no remap needed
    if new_values[:len(old_values)] == old_values:
        return None

    new_positions = {name: i for i, name in enumerate(new_values)}

    if storage_type == "int":
        if is_flags:
            # Build bit position remap for flags bitmask values
            remap = {}
            dropped = []
            for old_pos, name in enumerate(old_values):
                if name in new_positions:
                    new_pos = new_positions[name]
                    if old_pos != new_pos:
                        remap[old_pos] = new_pos
                else:
                    remap[old_pos] = None
                    dropped.append(name)
            if not remap:
                return None
            return {
                "type": "flags_int",
                "remap": remap,
                "dropped": dropped,
                "num_old_values": len(old_values),
            }
        else:
            # Build index remap for non-flags integer values
            remap = {}
            dropped = []
            for old_idx, name in enumerate(old_values):
                if name in new_positions:
                    new_idx = new_positions[name]
                    if old_idx != new_idx:
                        remap[old_idx] = new_idx
                else:
                    remap[old_idx] = None
                    dropped.append(name)
            if not remap:
                return None
            return {
                "type": "index_int",
                "remap": remap,
                "dropped": dropped,
            }

    elif storage_type == "string":
        # String-stored enums use value names — only need remap if names removed
        removed = [v for v in old_values if v not in new_values]
        if not removed:
            return None
        return {
            "type": "string",
            "removed": set(removed),
            "is_flags": is_flags,
        }

    return None


def _apply_remap(value_str: str, remap_data: dict) -> str:
    """Apply a remap to a single property value string."""
    rtype = remap_data["type"]

    if rtype == "flags_int":
        try:
            old_int = int(value_str)
        except ValueError:
            return value_str
        remap = remap_data["remap"]
        num_old = remap_data["num_old_values"]
        new_int = 0
        for bit_pos in range(max(num_old, old_int.bit_length())):
            if old_int & (1 << bit_pos):
                if bit_pos in remap:
                    new_pos = remap[bit_pos]
                    if new_pos is not None:
                        new_int |= (1 << new_pos)
                    # else: bit dropped
                else:
                    new_int |= (1 << bit_pos)  # unchanged position
        return str(new_int)

    elif rtype == "index_int":
        try:
            old_int = int(value_str)
        except ValueError:
            return value_str
        remap = remap_data["remap"]
        if old_int in remap:
            new_int = remap[old_int]
            return str(new_int if new_int is not None else 0)
        return value_str

    elif rtype == "string":
        removed = remap_data["removed"]
        is_flags = remap_data["is_flags"]
        if is_flags:
            if not value_str:
                return value_str
            parts = [p.strip() for p in value_str.split(",")]
            filtered = [p for p in parts if p and p not in removed]
            return ",".join(filtered)
        else:
            return "" if value_str in removed else value_str

    return value_str


def remap_tmx_property_values(
    project_dir: Path,
    tmx_remaps: list[dict],
    dry_run: bool = False,
) -> list[str]:
    """
    Scan TMX/TSX files in project_dir and remap property values.

    Handles int-stored flags (bitmask remapping), int-stored indices,
    and string-stored enum values.
    """
    if not tmx_remaps:
        return []

    changes = []
    remap_count = 0

    # Find all TMX and TSX files (skip templates dir — those come from archetype)
    all_files = sorted(project_dir.rglob("*.tmx")) + sorted(project_dir.rglob("*.tsx"))
    tmx_files = [f for f in all_files if "templates" not in f.parts]

    for tmx_file in tmx_files:
        content = tmx_file.read_text(encoding="utf-8")
        original = content

        for remap_info in tmx_remaps:
            prop_name = remap_info["property_type_name"]
            remap_data = remap_info["remap_data"]

            # Match <property> elements with this propertytype that have a value attr.
            # Tiled consistently outputs: name, type, propertytype, value — so
            # propertytype always precedes value in the element.
            pattern = re.compile(
                r'(<property\b[^>]*?\bpropertytype="'
                + re.escape(prop_name)
                + r'"[^>]*?\bvalue=")([^"]*?)(")'
            )

            def _make_replacer(rd):
                def replacer(match):
                    nonlocal remap_count
                    prefix, old_val, suffix = (
                        match.group(1), match.group(2), match.group(3),
                    )
                    new_val = _apply_remap(old_val, rd)
                    if new_val != old_val:
                        remap_count += 1
                        return f"{prefix}{new_val}{suffix}"
                    return match.group(0)
                return replacer

            content = pattern.sub(_make_replacer(remap_data), content)

        if content != original:
            rel = tmx_file.relative_to(project_dir)
            changes.append(f"Remapped values in {rel}")
            if not dry_run:
                tmx_file.write_text(content, encoding="utf-8")

    if remap_count:
        changes.insert(0, f"Remapped {remap_count} property value(s) in TMX/TSX files")

    return changes


def _remap_json_properties(properties: list, tmx_remaps: list[dict]) -> list[str]:
    """
    Remap property values in a .tiled-project properties list.

    Handles the same remap types as TMX remapping but operates on JSON dicts.
    """
    if not tmx_remaps:
        return []

    changes = []
    remap_by_type = {r["property_type_name"]: r["remap_data"] for r in tmx_remaps}

    for prop in properties:
        ptype = prop.get("propertytype")
        if ptype and ptype in remap_by_type:
            remap_data = remap_by_type[ptype]
            old_val = prop.get("value")
            if old_val is not None:
                old_str = str(old_val)
                new_str = _apply_remap(old_str, remap_data)
                if new_str != old_str:
                    if prop.get("type") == "int":
                        try:
                            prop["value"] = int(new_str)
                        except ValueError:
                            prop["value"] = new_str
                    else:
                        prop["value"] = new_str
                    changes.append(
                        f"Remapped project property {prop['name']}: "
                        f"{old_str} → {new_str}"
                    )

    return changes


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

        dirty = False

        existing_types = project_data.get("propertyTypes", [])
        archetype_types = archetype_data.get("propertyTypes", [])

        merged_types, type_changes, tmx_remaps = merge_property_types(
            existing_types, archetype_types
        )

        if type_changes:
            for change in type_changes:
                changes.append(f"Property type: {change}")
            project_data["propertyTypes"] = merged_types
            dirty = True

        # Remap TMX/TSX property values (must happen before writing .tiled-project)
        if tmx_remaps:
            tmx_changes = remap_tmx_property_values(
                project_path, tmx_remaps, dry_run
            )
            changes.extend(tmx_changes)
            for remap_info in tmx_remaps:
                rd = remap_info["remap_data"]
                dropped = rd.get("dropped", [])
                if not dropped and "removed" in rd:
                    dropped = sorted(rd["removed"])
                if dropped:
                    changes.append(
                        f"WARNING: Dropped values from "
                        f"{remap_info['property_type_name']}: "
                        f"{', '.join(dropped)}"
                    )

        # Remap .tiled-project property values
        existing_props = project_data.get("properties", [])
        if tmx_remaps:
            prop_changes = _remap_json_properties(existing_props, tmx_remaps)
            if prop_changes:
                changes.extend(prop_changes)
                dirty = True

        # Merge project-level properties (add missing, remove obsolete)
        archetype_props = archetype_data.get("properties", [])
        merged_props, added_props, removed_props = merge_properties(existing_props, archetype_props)

        if added_props:
            changes.append(f"Properties added: {', '.join(added_props)}")
            project_data["properties"] = merged_props
            dirty = True

        if removed_props:
            changes.append(f"Properties removed: {', '.join(removed_props)}")
            project_data["properties"] = merged_props
            dirty = True

        if dirty and not dry_run:
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
