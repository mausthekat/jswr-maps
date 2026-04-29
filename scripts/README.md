# tmx/scripts/

TMX map creation, maintenance, and validation. Anything that
operates on `.tmx` / `.world` / `.tiled-project` files lives here.

## What goes here

- TMX format converters (`dat_to_tmx.py`, `tmx_to_dat.py`,
  `dat_to_jsw.py`).
- TMX project orchestration (`tmx_project.py` + `tmx_project_lib.py`).
- TMX inspection / visualisation (`tmx_room_map.py`,
  `tmx_world_ascii.py`, `render_tmx_rooms.py`,
  `generate_tile_overlays.py`, `generate_reachability_debug.sh`).
- TMX content editors (`patch_gorgeous_tmx.py`,
  `populate_gorgeous_guardians.py`, `tile_image_to_tileset.py`).
- TMX validation (`validate_rooms.py`, `check_tmx_corruption.py`).

## What does NOT go here

- Anything invoked by the build (e.g. `regenerate_all_packs.py`,
  `tmx_to_jsw.py`) — those live in `build_scripts/tmx/`.
- Runtime tooling, asset generators — those live in `scripts/`.

## Conventions

- Scripts that import from `src/` use
  `sys.path.insert(0, str(Path(__file__).resolve().parents[2]))` —
  ONE more `..` than the `scripts/` convention because this
  directory lives one level deeper.
