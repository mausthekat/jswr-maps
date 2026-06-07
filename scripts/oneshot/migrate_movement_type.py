"""One-shot migration: consolidate the per-map JumpType + FallModel TMX
properties into a single MovementType (JSW1/JSW2/JSWR).

Every map set JumpType == FallModel (verified), so MovementType takes the
JumpType value (falling back to FallModel, then 0). For each .tiled-project:
  - top-level `properties`: add/set MovementType = (JumpType else FallModel else 0),
    remove JumpType + FallModel instances.
  - `propertyTypes`: rename the JumpType enum -> MovementType (keep its id/values),
    remove the FallModel enum.
Files are rewritten in Tiled's exact format (indent=4, sort_keys=True, +newline)
so only the intended lines diff.

Usage:  python tmx/scripts/oneshot/migrate_movement_type.py [--apply]
        (default is a dry run that prints the per-file plan)
"""
import json
import glob
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
TMX = os.path.join(ROOT, "tmx")


def dumps(data: dict) -> str:
    return json.dumps(data, indent=4, sort_keys=True) + "\n"


def migrate(path: str, apply: bool) -> str:
    raw = open(path, encoding="utf-8").read()
    data = json.loads(raw)
    if dumps(data) != raw:
        return f"SKIP (format mismatch, won't round-trip cleanly): {path}"

    props = data.get("properties", [])
    by_name = {p.get("name"): p for p in props}
    jt = by_name.get("JumpType")
    fm = by_name.get("FallModel")
    if jt is None and fm is None and "MovementType" not in by_name:
        return f"skip (no JumpType/FallModel/MovementType): {os.path.relpath(path, ROOT)}"

    mv = 0
    if jt is not None and isinstance(jt.get("value"), int):
        mv = jt["value"]
    elif fm is not None and isinstance(fm.get("value"), int):
        mv = fm["value"]
    elif "MovementType" in by_name and isinstance(by_name["MovementType"].get("value"), int):
        mv = by_name["MovementType"]["value"]
    mv = mv if mv in (0, 1, 2) else 0

    new_props = [p for p in props if p.get("name") not in ("JumpType", "FallModel", "MovementType")]
    new_props.append({"name": "MovementType", "propertytype": "MovementType",
                      "type": "int", "value": mv})
    data["properties"] = new_props

    ptypes = data.get("propertyTypes", [])
    for pt in ptypes:
        if pt.get("name") == "JumpType":
            pt["name"] = "MovementType"
    data["propertyTypes"] = [pt for pt in ptypes if pt.get("name") != "FallModel"]

    old_jt = jt.get("value") if jt else None
    old_fm = fm.get("value") if fm else None
    plan = (f"{os.path.relpath(path, ROOT)}: JumpType={old_jt} FallModel={old_fm} "
            f"-> MovementType={mv}")
    if apply:
        open(path, "w", encoding="utf-8").write(dumps(data))
    return plan


def main():
    apply = "--apply" in sys.argv
    files = sorted(glob.glob(os.path.join(TMX, "**", "*.tiled-project"), recursive=True))
    print(f"{'APPLYING' if apply else 'DRY RUN'} - {len(files)} .tiled-project files\n")
    for f in files:
        print("  " + migrate(f, apply))
    if not apply:
        print("\n(dry run; re-run with --apply to write)")


if __name__ == "__main__":
    main()
