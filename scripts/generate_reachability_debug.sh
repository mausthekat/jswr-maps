#!/usr/bin/env bash
# Generate reachability debug PNGs (room images + composite map) for all maps.
# Usage: ./tmx/scripts/generate_reachability_debug.sh [--sims N] [--map-scale N]
#
# Requires: tools/bfs_builder (cargo build --release)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
BFS_BUILDER="$PROJECT_ROOT/tools/bfs_builder/target/release/bfs_builder"
TMX_CONTENT="$PROJECT_ROOT/tmx/content"
OUTPUT_ROOT="$PROJECT_ROOT/analysis/reachability_debug"

SIMS=250
MAP_SCALE=2
SHORTEST=""

# Parse args
while [[ $# -gt 0 ]]; do
    case "$1" in
        --sims) SIMS="$2"; shift 2 ;;
        --map-scale) MAP_SCALE="$2"; shift 2 ;;
        --shortest-paths) SHORTEST="--shortest-paths"; shift ;;
        *) echo "Unknown arg: $1"; exit 1 ;;
    esac
done

# Check binary exists
if [[ ! -x "$BFS_BUILDER" ]]; then
    echo "Building bfs_builder..."
    cargo build --release --manifest-path "$PROJECT_ROOT/tools/bfs_builder/Cargo.toml"
fi

echo "Generating reachability debug for all maps (sims=$SIMS, scale=$MAP_SCALE)"
echo ""

for map in "$TMX_CONTENT"/*/; do
    name=$(basename "$map")
    outdir="$OUTPUT_ROOT/$name"
    printf "%-24s" "$name:"
    result=$("$BFS_BUILDER" "$map" \
        --debug-all --debug-sims "$SIMS" --debug-format png \
        --map --map-scale "$MAP_SCALE" $SHORTEST \
        --output "$outdir" 2>&1 | grep -o '[0-9.]*s total')
    echo "$result"
done

echo ""
echo "Done. Output in $OUTPUT_ROOT"
