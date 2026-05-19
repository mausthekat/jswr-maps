#!/usr/bin/env python3
"""One-shot: apply JSW1 ROM-derived guardian speeds to jsw-gorgeous.

Per-room mapping uses the now-aligned room-id convention (gorgeous
file `NNN.tmx` <-> JSW1 room id `NNN-1`).

Per-guardian mapping is by spawn-x proximity inside the room: the
gorgeous Guardian object's `x` is matched to the JSW1 entity with the
closest x in the same room. Tolerance is one tile (8 px) - anything
further apart is reported and skipped (no edit).

Speed semantics under the new identity Speed table:
  * vertical guardian: `Speed = |signed(byte[4])|`
  * horizontal guardian: `Speed = 4` (JSW1 horiz cadence is fixed at
    1 tile / 4 frames = 2 px/tick = Willy speed = identity-table 4)

Skipped (the user fixes manually):
  * gorgeous Guardian objects whose `width != 16` - these are
    oversized composites (Evil Head etc.) where the JSW1 source is 3
    separate vert entities sharing one sprite page.
  * gorgeous Guardian objects whose route's Direction is rope/arrow
    style (not 0/1 vert or 2/3 horiz).
  * rooms with no JSW1 counterpart (e.g. gorgeous's `060.tmx`
    "The Bow", which is past JSW1's playable 0..59 range).

Usage:
    python tmx/scripts/oneshot/apply_jsw1_speeds_to_gorgeous.py [--apply]
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from jsw_snapshot import (
    detect_engine, iter_rooms, load_snapshot, parse_room_guardians,
)


GORGEOUS_DIR = (
    Path(__file__).parent.parent.parent / "content" / "jsw-gorgeous"
)
JSW1_SNAPSHOT = (
    Path(__file__).parent.parent.parent.parent
    / "analysis" / "endless" / "input" / "JetSetWilly1.z80"
)

# Per-room file matching: gorgeous's `NNN.tmx` is JSW1 room `NNN - 1`
# now that the user has aligned the IDs. Anything past JSW1's
# populated-rooms count has no counterpart and is skipped.

GUARDIAN_OBJ_RE = re.compile(
    r'<object\s+id="(?P<id>\d+)"[^>]*'
    r'name="(?P<name>[^"]*)"[^>]*'
    r'type="Guardian"[^>]*'
    r'x="(?P<x>[^"]+)"[^>]*'
    r'y="(?P<y>[^"]+)"[^>]*'
    r'width="(?P<w>\d+)"[^>]*'
    r'height="(?P<h>\d+)"',
    re.DOTALL,
)


def parse_gorgeous_guardians(text: str) -> list[dict]:
    """Return guardians {id, name, x, y, w, h} for one gorgeous TMX."""
    out: list[dict] = []
    for m in GUARDIAN_OBJ_RE.finditer(text):
        out.append({
            "id": int(m["id"]),
            "name": m["name"],
            "x": float(m["x"]),
            "y": float(m["y"]),
            "w": int(m["w"]),
            "h": int(m["h"]),
        })
    return out


ROUTE_BLOCK_RE = re.compile(
    r'(?P<head><object\s+id="(?P<id>\d+)"\s+type="Route"[^>]*>)'
    r'(?P<body>.*?)'
    r'(?P<tail></object>)',
    re.DOTALL,
)


def parse_routes(text: str) -> list[dict]:
    """Parse Route objects: id, body span, guardian-id, direction, current speed."""
    out: list[dict] = []
    for m in ROUTE_BLOCK_RE.finditer(text):
        body = m["body"]
        gm = re.search(r'name="Guardian"[^/]+value="(\d+)"', body)
        sm = re.search(
            r'(<property\s+name="Speed"[^/]*value=")(\d+)("[^/]*/>)',
            body,
        )
        dm = re.search(r'name="Direction"[^/]+value="(\d+)"', body)
        if gm is None or sm is None or dm is None:
            continue
        out.append({
            "route_id": int(m["id"]),
            "guardian_id": int(gm.group(1)),
            "direction": int(dm.group(1)),
            "current_speed": int(sm.group(2)),
            "speed_tag_full_match_in_text": (
                m.start() + len(m["head"]) + sm.start(0),
                m.start() + len(m["head"]) + sm.end(0),
            ),
            "speed_prefix": sm.group(1),
            "speed_value": sm.group(2),
            "speed_suffix": sm.group(3),
        })
    return out


def jsw1_byte4_signed(raw_def: tuple) -> int:
    b = raw_def[4]
    return b - 256 if b >= 128 else b


def jsw1_speed_for(gref) -> int | None:
    """Speed value to write under the new identity table.
    None means 'not eligible for auto-mapping' (rope/arrow)."""
    if gref.kind == "vert":
        return abs(jsw1_byte4_signed(gref.raw_def))
    if gref.kind == "horiz":
        return 4
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true",
                    help="Write changes (default: dry-run)")
    ap.add_argument("--tolerance", type=int, default=8,
                    help="Max |Δx| (in px) for a gorgeous guardian to "
                         "match a JSW1 entity. Default 8 (one tile).")
    args = ap.parse_args()

    snap = load_snapshot(JSW1_SNAPSHOT)
    engine = detect_engine(snap)
    if engine is None:
        sys.exit("could not detect JSW1 engine in snapshot")

    # JSW1 room id -> [GuardianRef] for vert/horiz only
    jsw1_by_room: dict[int, list] = {}
    for r in iter_rooms(snap, engine):
        ents = [g for g in parse_room_guardians(snap, engine, r)
                if g.kind in ("vert", "horiz")]
        jsw1_by_room[r.id] = ents

    stats = defaultdict(int)
    skipped_oversized: list[str] = []
    skipped_no_match: list[str] = []
    skipped_no_jsw1_room: list[str] = []
    edits: list[tuple[Path, str, list[tuple[int, int]]]] = []

    for tmx_path in sorted(GORGEOUS_DIR.glob("*.tmx")):
        try:
            file_num = int(tmx_path.stem)
        except ValueError:
            continue
        room_id = file_num - 1
        if room_id not in jsw1_by_room or not jsw1_by_room[room_id]:
            skipped_no_jsw1_room.append(f"{tmx_path.name} → JSW1 room {room_id}: no entities")
            continue

        text = tmx_path.read_text()
        guardians = parse_gorgeous_guardians(text)
        if not guardians:
            continue
        routes = parse_routes(text)
        routes_by_gid = {r["guardian_id"]: r for r in routes}

        # Index JSW1 entities by direction class for matching
        jsw1_vert = [e for e in jsw1_by_room[room_id] if e.kind == "vert"]
        jsw1_horiz = [e for e in jsw1_by_room[room_id] if e.kind == "horiz"]

        # Build replacement plan: list of (start, end, new_text) in `text`
        replacements: list[tuple[int, int, str]] = []

        for gobj in guardians:
            stats["total_guardians"] += 1
            if gobj["w"] != 16 or gobj["h"] != 16:
                stats["skipped_oversized"] += 1
                skipped_oversized.append(
                    f"{tmx_path.name}: {gobj['name']!r} "
                    f"({gobj['w']}x{gobj['h']} at x={gobj['x']:.0f})"
                )
                continue
            route = routes_by_gid.get(gobj["id"])
            if route is None:
                stats["skipped_no_route"] += 1
                continue
            kind_pool = jsw1_vert if route["direction"] in (0, 1) else jsw1_horiz
            if not kind_pool:
                stats["skipped_no_pool"] += 1
                skipped_no_match.append(
                    f"{tmx_path.name}: {gobj['name']!r} "
                    f"dir={route['direction']} no matching JSW1 entity kind"
                )
                continue
            best = min(kind_pool, key=lambda e: abs(e.x - gobj["x"]))
            dx = abs(best.x - gobj["x"])
            if dx > args.tolerance:
                stats["skipped_too_far"] += 1
                skipped_no_match.append(
                    f"{tmx_path.name}: {gobj['name']!r} at x={gobj['x']:.0f} "
                    f"closest JSW1 entity dx={dx:.0f} > tolerance"
                )
                continue
            new_speed = jsw1_speed_for(best)
            if new_speed is None:
                stats["skipped_unmapped_kind"] += 1
                continue

            old_speed = route["current_speed"]
            if old_speed == new_speed:
                stats["already_correct"] += 1
                continue

            start, end = route["speed_tag_full_match_in_text"]
            new_text = (route["speed_prefix"] + str(new_speed)
                        + route["speed_suffix"])
            replacements.append((start, end, new_text))
            stats["updated"] += 1

        if replacements:
            replacements.sort(key=lambda r: r[0], reverse=True)
            new_text = text
            for s, e, n in replacements:
                new_text = new_text[:s] + n + new_text[e:]
            edits.append((tmx_path, new_text, replacements))
            if args.apply:
                tmx_path.write_text(new_text)

    # Reporting
    print(f"\n{'APPLYING' if args.apply else 'DRY RUN'} - JSW1 speed → jsw-gorgeous\n")
    print(f"Files visited:               {len(list(GORGEOUS_DIR.glob('*.tmx')))}")
    print(f"Files with edits:            {len(edits)}")
    for k in ("total_guardians", "updated", "already_correct",
              "skipped_oversized", "skipped_no_route", "skipped_no_pool",
              "skipped_too_far", "skipped_unmapped_kind"):
        print(f"  {k:30s} {stats[k]}")

    if skipped_oversized:
        print(f"\nOversized guardians SKIPPED ({len(skipped_oversized)}):")
        for line in skipped_oversized:
            print(f"  {line}")

    if skipped_no_match:
        print(f"\nNo JSW1 match SKIPPED ({len(skipped_no_match)}):")
        for line in skipped_no_match:
            print(f"  {line}")

    if skipped_no_jsw1_room:
        print(f"\nNo JSW1 room SKIPPED ({len(skipped_no_jsw1_room)}):")
        for line in skipped_no_jsw1_room:
            print(f"  {line}")

    if not args.apply:
        print(f"\n(dry-run; rerun with --apply to write {len(edits)} files)")

    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
