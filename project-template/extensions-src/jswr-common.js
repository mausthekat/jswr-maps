/// <reference types="@mapeditor/tiled-api" />

/**
 * JSW:R Tiled Extensions — Common Utilities
 *
 * SOURCE FILE — do not edit the bundled output in .extensions/ directly.
 * Edit this file, then run: python tmx/scripts/tmx_project.py refresh
 * which bundles all extensions-src/*.js files into a single .extensions/jswr.js
 *
 * Shared constants and utility functions used by other jswr-*.js source files.
 * This file is concatenated first (alphabetically) during bundling.
 */

// Room dimensions in pixels
const ROOM_WIDTH = 256;   // 32 tiles * 8 pixels
const ROOM_HEIGHT = 128;  // 16 tiles * 8 pixels

// Guardian tileset name (for dynamic firstGid lookup - must match TSX file name exactly)
const TILESET_GUARDIANS = "Guardians";

// Guardian local tile IDs within guardians.tsx (collection of images)
const LOCAL_ID_LIFT = 70;               // guardians.tsx tile 70
const LOCAL_ID_ARROW_LEFT = 71;         // guardians.tsx tile 71
const LOCAL_ID_ARROW_RIGHT = 72;        // guardians.tsx tile 72
const LOCAL_ID_PERISCOPE_TANK = 73;     // guardians.tsx tile 73 (16x32)
const LOCAL_ID_EVIL_GIANT_HEAD = 74;    // guardians.tsx tile 74 (32x32)

/**
 * Get the tile count from the Guardians tileset in a map.
 * @param {TileMap} map - The map
 * @returns {number} - Tile count, or 0 if tileset not found
 */
function getGuardiansTileCount(map) {
    if (!map || !map.tilesets) return 0;
    for (let i = 0; i < map.tilesets.length; i++) {
        const ts = map.tilesets[i];
        if (!ts) continue;
        const tsName = (ts.name || "").replace(/\.tsx$/i, "");
        if (tsName === TILESET_GUARDIANS) return ts.tileCount || 0;
    }
    return 0;
}

// Cache for tileset firstGids (cleared when map changes)
let cachedTilesetFirstGids = {};
let cachedMapFileName = null;

// Guardian names loaded from text files
let guardianNames = [];
let periscopeTankName = "Periscope Tank";
let evilHeadName = "Evil Head";
let guardianNamesLoaded = false;

/**
 * Get the map folder path from current document
 */
function getMapFolder() {
    const map = tiled.activeAsset;
    if (!map || !map.fileName) {
        return null;
    }
    return FileInfo.path(map.fileName);
}

/**
 * Get map name from folder
 */
function getMapName(folder) {
    return FileInfo.fileName(folder);
}

/**
 * Get the firstGid for a tileset by name from a map
 * @param {TileMap} map - The map to search
 * @param {string} tilesetName - The tileset name (without .tsx extension)
 * @returns {number|null} - The firstGid or null if not found
 */
function getTilesetFirstGid(map, tilesetName) {
    if (!map || !map.tilesets || !tilesetName) return null;

    // Check cache
    if (cachedMapFileName === map.fileName && cachedTilesetFirstGids[tilesetName] !== undefined) {
        return cachedTilesetFirstGids[tilesetName];
    }

    // Clear cache if map changed
    if (cachedMapFileName !== map.fileName) {
        cachedTilesetFirstGids = {};
        cachedMapFileName = map.fileName;
    }

    // Compute firstGid by iterating through tilesets
    let firstGid = 1;
    for (let i = 0; i < map.tilesets.length; i++) {
        const ts = map.tilesets[i];
        if (!ts) continue;

        const tsName = ts.name || "";
        const tsBaseName = tsName.replace(/\.tsx$/i, "");

        if (tsBaseName === tilesetName || tsName === tilesetName) {
            cachedTilesetFirstGids[tilesetName] = firstGid;
            return firstGid;
        }

        const tileCount = ts.tileCount || 0;
        firstGid += tileCount;
    }

    return null;
}

/**
 * Get the GID for a guardian tileset's local tile ID
 * @param {TileMap} map - The map
 * @param {number} localId - The local tile ID within guardians.tsx
 * @returns {number|null} - The global GID or null
 */
function getGuardianGid(map, localId) {
    const firstGid = getTilesetFirstGid(map, TILESET_GUARDIANS);
    return firstGid !== null ? firstGid + localId : null;
}

/**
 * Check if two rectangles overlap
 */
function rectsOverlap(r1, r2) {
    return !(r1.x + r1.width <= r2.x ||
             r2.x + r2.width <= r1.x ||
             r1.y + r1.height <= r2.y ||
             r2.y + r2.height <= r1.y);
}

/**
 * Parse polyline points string into array of {x, y} objects
 * @param {string} pointsStr - Points string like "0,0 0,120" or "0,0 88,0"
 * @returns {Array} - Array of {x, y} objects
 */
function parsePolylinePoints(pointsStr) {
    if (!pointsStr) return [];
    const points = [];
    const parts = pointsStr.trim().split(/\s+/);
    for (const part of parts) {
        const coords = part.split(',');
        if (coords.length >= 2) {
            points.push({
                x: parseFloat(coords[0]) || 0,
                y: parseFloat(coords[1]) || 0
            });
        }
    }
    return points;
}

/**
 * Calculate bounding box from route object position and polyline points
 * @param {number} objX - Route object x position
 * @param {number} objY - Route object y position
 * @param {Array} points - Array of {x, y} relative points
 * @returns {Object} - {x, y, width, height} bounding box
 */
function getPolylineBounds(objX, objY, points) {
    if (!points || points.length === 0) {
        return { x: objX, y: objY, width: 16, height: 16 };
    }

    const absPoints = points.map(p => ({
        x: objX + p.x,
        y: objY + p.y
    }));

    let minX = absPoints[0].x, maxX = absPoints[0].x;
    let minY = absPoints[0].y, maxY = absPoints[0].y;

    for (const p of absPoints) {
        if (p.x < minX) minX = p.x;
        if (p.x > maxX) maxX = p.x;
        if (p.y < minY) minY = p.y;
        if (p.y > maxY) maxY = p.y;
    }

    let width = maxX - minX;
    let height = maxY - minY;

    if (width === 0) width = 16;
    if (height === 0) height = 16;

    if (maxX === minX) minX -= 8;
    if (maxY === minY) minY -= 8;

    return { x: minX, y: minY, width: width, height: height };
}

/**
 * Check if a file is currently open in Tiled
 * @param {string} filePath - Path to check
 * @returns {TileMap|null} - The open map or null
 */
function getOpenMap(filePath) {
    for (const asset of tiled.openAssets) {
        if (asset.isTileMap && asset.fileName === filePath) {
            return asset;
        }
    }
    return null;
}

/**
 * Get the tile from a MapObject (handles both obj.tile and obj.cell.tile)
 * @param {MapObject} obj - The map object
 * @returns {Tile|null} - The tile or null
 */
function getObjectTile(obj) {
    if (!obj) return null;
    return obj.tile || (obj.cell && obj.cell.tile) || null;
}

/**
 * Get the GID of an object's tile
 * @param {MapObject} obj - The map object
 * @param {TileMap} map - The map containing the object
 * @returns {number|null} - The GID (with flip flags) or null
 */
function getObjectGid(obj, map) {
    if (obj.cell && typeof obj.cell.tileId === 'number' && !isNaN(obj.cell.tileId)) {
        return obj.cell.tileId;
    }

    const tile = getObjectTile(obj);
    if (!tile || typeof tile.id !== 'number') return null;

    if (tile.tileset && map && map.tilesets) {
        let firstGid = 1;
        for (let i = 0; i < map.tilesets.length; i++) {
            const ts = map.tilesets[i];
            if (!ts) continue;

            if (ts === tile.tileset || (ts.name && tile.tileset.name && ts.name === tile.tileset.name)) {
                const gid = firstGid + tile.id;
                if (!isNaN(gid)) return gid;
            }

            const tileCount = ts.tileCount || 0;
            firstGid += tileCount;
        }
    }
    return null;
}
