# JSW:R Map Editing Toolkit

Map editing tools and content for **Jet Set Willy: Redux** using the
[Tiled Map Editor](https://www.mapeditor.org/).

## Getting Started

See [TILED_MAP_CREATION.md](TILED_MAP_CREATION.md) for the full guide — covers setup,
creating maps, placing guardians, routes, spawns, game modes, and building.

## Quick Setup

1. Install [Tiled](https://www.mapeditor.org/) 1.10+ (1.11+ recommended)
2. Install [uv](https://docs.astral.sh/uv/getting-started/installation/) (manages Python
   and dependencies automatically)
3. Clone this repo and open a map project in Tiled:
   - Open `content/training/training.tiled-project` as a learning reference
   - Or create a new map: `uv run scripts/tmx_project.py create <map-name>`

## Folder Structure

```
jswr-maps/
├── content/              # Published map projects
│   ├── main/             # The main 472-room mansion
│   ├── training/         # Small tutorial map (good reference)
│   ├── _gaminglounge/    # Multiplayer lobby infrastructure
│   └── .../              # Other community maps
├── _in_progress/         # Work-in-progress maps
├── tilesets/             # Shared tilesets (referenced by all maps)
│   ├── tiles_solid.tsx   # Solid blocks
│   ├── tiles_stairs.tsx  # Stairs/ramps
│   ├── tiles_platform.tsx # One-way platforms
│   ├── tiles_hazard.tsx  # Hazard tiles
│   ├── tiles_decoration.tsx # Decoration (no collision)
│   ├── tiles_conveyor.tsx # Conveyor belts (animated)
│   ├── tiles_collapsible.tsx # Collapsible platforms (animated)
│   ├── tiles_penrose.tsx # Penrose visual tiles (manually added)
│   ├── tiles_mm_exit.tsx # Manic Miner exit doors
│   ├── collectibles.tsx  # Collectible items
│   ├── guardians.tsx     # Guardian sprites
│   └── meta/             # Metadata and tile mappings
├── project-template/     # Archetype for new map projects
│   ├── archetype.tiled-project
│   ├── templates/        # Spawn and route object templates
│   └── .extensions/      # Tiled extension (jswo.js)
└── scripts/              # Map editing tools
    ├── tmx_project.py    # Create/manage map projects
    ├── dat_to_tmx.py     # Convert legacy .dat files to TMX
    └── ...               # Other utilities
```

## Contributing Maps

1. Fork this repo
2. Create a new map project: `uv run scripts/tmx_project.py create my-map`
3. Edit rooms in Tiled
4. Submit a pull request

Maps are reviewed and merged into the game's next release.

## License

Map content and tooling for Jet Set Willy: Redux. See the main game repository for
license details.
