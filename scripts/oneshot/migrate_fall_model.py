#!/usr/bin/env python3
"""One-off migration: FallDamageMode -> FallModel across all map projects.

The old FallDamageMode enum (0=Lenient, 1=Strict) becomes the 3-value FallModel
(0=JSWR, 1=JSW2, 2=JSW1). Per the agreed mapping: Lenient->JSWR (0->0),
Strict->JSW1 (1->2). Renames the property and the embedded enum def. Tiled writes
.tiled-project as json.dumps(indent=4, sort_keys=True)+newline, so this is a
minimal-diff rewrite.
"""
import json
import sys
from pathlib import Path

ROOTS = [Path("tmx/content"), Path("tmx/_in_progress")]
VALUE_MAP = {0: 0, 1: 2}   # Lenient->JSWR, Strict->JSW1


def migrate(path: Path) -> bool:
    data = json.loads(path.read_text())
    changed = False
    for p in data.get("properties", []):
        if p.get("name") == "FallDamageMode":
            p["name"] = "FallModel"
            if p.get("propertytype") == "FallDamageMode":
                p["propertytype"] = "FallModel"
            old = int(p.get("value", 0))
            p["value"] = VALUE_MAP.get(old, 0)
            changed = True
    for pt in data.get("propertyTypes", []):
        if pt.get("name") == "FallDamageMode":
            pt["name"] = "FallModel"
            pt["values"] = ["JSWR", "JSW2", "JSW1"]
            changed = True
    if changed:
        path.write_text(json.dumps(data, indent=4, sort_keys=True) + "\n")
    return changed


def main() -> int:
    n = 0
    for root in ROOTS:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.tiled-project")):
            if migrate(path):
                n += 1
                print(f"  migrated {path}")
    print(f"{n} projects migrated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
