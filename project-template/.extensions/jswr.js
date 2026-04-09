/// <reference types="@mapeditor/tiled-api" />

// =======================================================================
// JSW:R Tiled Extension (bundled from extensions-src/*.js)
// DO NOT EDIT — edit the source files in extensions-src/ instead,
// then run: python tmx/scripts/tmx_project.py refresh
// =======================================================================

// --- jswr-common.js ---

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

// --- jswr-guardians.js ---
/**
 * JSW:R Tiled Extensions — Guardian & Route Tools
 *
 * SOURCE FILE — do not edit the bundled output in .extensions/ directly.
 * Edit this file, then run: python tmx/scripts/tmx_project.py refresh
 *
 * Guardian/route property fixing and validation, orphaned-route repair,
 * spawn-point validation, and game-mode reporting.
 *
 * Requires: jswr-common.js (bundled before this file alphabetically)
 *
 * Contents:
 *   - TMX parsing for guardians and routes (parseRoomObjects,
 *     parseRoomObjectsFromMap, findObjectById, assignGuardianToRoute)
 *   - Orphaned route repair (fixOrphanedRoutesInMap, fixOrphanedRoutes)
 *   - Guardian name loading and lookup (loadGuardianNames, getGuardianBaseName)
 *   - Object classification helpers (isGuardianObject, isRouteObject,
 *     isRouteOrphaned, isArrowObject)
 *   - Property fixing (fixObjectProperties, countGuardiansByType,
 *     fixRoomProperties, fixAllGuardianProperties,
 *     fixSelectedGuardianProperties)
 *   - Selection-driven action state (updateFixSelectedAction,
 *     connectSelectionSignal, currentMapConnection)
 *   - Spawn-point validation constants and functions (TEAM_NAMES,
 *     SPAWN_KIND_NAMES, GAME_MODE_BITS, formatGameModes, parseSpawnPoints,
 *     validateSpawnPoints)
 *   - Game-mode report constants and functions (ROOM_PURPOSE_NAMES,
 *     GAME_MODE_FULL_NAMES, ALL_GAMEPLAY_MODES, parseRoomPurpose,
 *     formatFullGameModes, showGameModeReport)
 *   - Action registrations: JSWRValidateSpawns, JSWRGameModeReport,
 *     JSWRFixRoutes, JSWRFixRoomProperties, JSWRFixProperties, JSWRFixSelected
 */

// =========================================================================
// Guardian & Route parsing and fixing
// =========================================================================

/**
 * Parse a map and extract guardians and routes
 * Uses API for files already open, text parsing for others (fast)
 * @param {string} tmxPath - Path to the TMX file
 * @returns {Object} - {guardians: [], routes: [], roomName: string}
 */
function parseRoomObjects(tmxPath) {
    const result = {
        guardians: [],
        routes: [],
        roomName: ""
    };

    // Check if file is already open - use API if so
    const openMap = getOpenMap(tmxPath);
    if (openMap) {
        return parseRoomObjectsFromMap(openMap);
    }

    // File not open - use fast text parsing
    try {
        const file = new TextFile(tmxPath, TextFile.ReadOnly);
        const content = file.readAll();
        file.close();

        // Extract room name
        const nameMatch = content.match(/<property\s+name="Name"\s+value="([^"]*)"/);
        if (nameMatch) {
            result.roomName = nameMatch[1];
        }

        // Parse all objects
        const objectGroupRegex = /<objectgroup[^>]*>([\s\S]*?)<\/objectgroup>/g;
        let groupMatch;

        while ((groupMatch = objectGroupRegex.exec(content)) !== null) {
            const groupContent = groupMatch[1];
            const objectRegex = /<object\s+([^>]*?)(?:\/>|>([\s\S]*?)<\/object>)/g;
            let objMatch;

            while ((objMatch = objectRegex.exec(groupContent)) !== null) {
                const attrs = objMatch[1];
                const innerContent = objMatch[2] || "";

                const idMatch = attrs.match(/id="(\d+)"/);
                const xMatch = attrs.match(/x="([^"]+)"/);
                const yMatch = attrs.match(/y="([^"]+)"/);
                const widthMatch = attrs.match(/width="([^"]+)"/);
                const heightMatch = attrs.match(/height="([^"]+)"/);
                const typeMatch = attrs.match(/type="([^"]*)"/);
                const objNameMatch = attrs.match(/name="([^"]*)"/);

                const objId = idMatch ? idMatch[1] : null;
                const x = xMatch ? parseFloat(xMatch[1]) : 0;
                const y = yMatch ? parseFloat(yMatch[1]) : 0;
                const width = widthMatch ? parseFloat(widthMatch[1]) : 16;
                const height = heightMatch ? parseFloat(heightMatch[1]) : 16;
                const objType = typeMatch ? typeMatch[1] : "";
                const objName = objNameMatch ? objNameMatch[1] : "";

                // Detect guardians by type="Guardian" or by having a gid in guardian range
                const gidMatch = attrs.match(/gid="(\d+)"/); // eslint-disable-line no-unused-vars

                if (objType === "Guardian" || objType === "Arrow") {
                    result.guardians.push({
                        id: objId,
                        name: objName,
                        x: x,
                        y: y,
                        width: width,
                        height: height
                    });
                } else if (objType === "Route" || objName === "Route") {
                    // Detect routes by type="Route" OR name="Route" (for template-based routes)
                    const guardianMatch = innerContent.match(/<property\s+name="Guardian"\s+type="object"\s+value="(\d*)"/);
                    const guardianValue = guardianMatch ? guardianMatch[1] : "";
                    const guardianId = (guardianValue === "0" || guardianValue === "") ? "" : guardianValue;

                    // Parse polyline points
                    const polylineMatch = innerContent.match(/<polyline\s+points="([^"]*)"/);
                    const points = polylineMatch ? parsePolylinePoints(polylineMatch[1]) : [];
                    const routeBounds = getPolylineBounds(x, y, points);

                    result.routes.push({
                        id: objId,
                        x: routeBounds.x,
                        y: routeBounds.y,
                        width: routeBounds.width,
                        height: routeBounds.height,
                        guardianId: guardianId
                    });
                }
            }
        }
    } catch (e) {
        tiled.warn("Failed to parse " + tmxPath + ": " + e);
    }

    return result;
}

/**
 * Parse guardians and routes from an already-open TileMap
 * @param {TileMap} map - The open map
 * @returns {Object} - {guardians: [], routes: [], roomName: string}
 */
function parseRoomObjectsFromMap(map) {
    const result = {
        guardians: [],
        routes: [],
        roomName: map.property("Name") || ""
    };

    for (let i = 0; i < map.layerCount; i++) {
        const layer = map.layerAt(i);
        if (!layer.isObjectLayer) continue;

        for (let j = 0; j < layer.objectCount; j++) {
            const obj = layer.objectAt(j);

            if (obj.type === "Guardian" || obj.type === "Arrow") {
                result.guardians.push({
                    id: String(obj.id),
                    name: obj.name || "",
                    x: obj.x,
                    y: obj.y,
                    width: obj.width || 16,
                    height: obj.height || 16
                });
            } else if (obj.type === "Route" || obj.name === "Route") {
                const guardianRef = obj.property("Guardian");
                let guardianId = "";

                // Handle object reference, number, or null
                // API returns {id: N} for object references, where id=0 means unassigned
                if (guardianRef !== null && guardianRef !== undefined) {
                    if (typeof guardianRef === "object") {
                        // Object reference - check if id exists and is non-zero
                        if (guardianRef.id && guardianRef.id !== 0) {
                            guardianId = String(guardianRef.id);
                        }
                    } else if (guardianRef !== 0) {
                        guardianId = String(guardianRef);
                    }
                }

                // Calculate bounds from polyline - obj.polygon returns array of {x, y} relative points
                const points = obj.polygon || [];
                const routeBounds = getPolylineBounds(obj.x, obj.y, points);

                result.routes.push({
                    id: String(obj.id),
                    x: routeBounds.x,
                    y: routeBounds.y,
                    width: routeBounds.width,
                    height: routeBounds.height,
                    guardianId: guardianId
                });
            }
        }
    }

    return result;
}

/**
 * Find a MapObject by ID in a TileMap
 * @param {TileMap} map - The map to search
 * @param {number} objectId - The object ID to find
 * @returns {MapObject|null} - The found object or null
 */
function findObjectById(map, objectId) {
    for (let i = 0; i < map.layerCount; i++) {
        const layer = map.layerAt(i);
        if (!layer.isObjectLayer) continue;

        for (let j = 0; j < layer.objectCount; j++) {
            const obj = layer.objectAt(j);
            if (obj.id === objectId) {
                return obj;
            }
        }
    }
    return null;
}

/**
 * Update a route's Guardian property using Tiled's API
 * @param {string} tmxPath - Path to the TMX file
 * @param {string} routeId - ID of the route object (as string)
 * @param {string} guardianId - ID of the guardian to assign (as string)
 * @returns {boolean} - Success
 */
function assignGuardianToRoute(tmxPath, routeId, guardianId) {
    try {
        // Open the map (or get it if already open)
        const map = tiled.open(tmxPath);
        if (!map || !map.isTileMap) {
            tiled.warn("Could not open map: " + tmxPath);
            return false;
        }

        // Find the route object by ID
        const routeIdNum = parseInt(routeId);
        const routeObj = findObjectById(map, routeIdNum);

        if (!routeObj) {
            tiled.warn("Could not find route object " + routeId + " in " + tmxPath);
            return false;
        }

        // Find the guardian object to create a proper object reference
        const guardianIdNum = parseInt(guardianId);
        const guardianObj = findObjectById(map, guardianIdNum);

        if (!guardianObj) {
            tiled.warn("Could not find guardian object " + guardianId + " in " + tmxPath);
            return false;
        }

        // Set the Guardian property as an object reference
        routeObj.setProperty("Guardian", guardianObj);

        tiled.log("Set Guardian property on route " + routeId + " to object " + guardianId + " in " + FileInfo.fileName(tmxPath));
        return true;
    } catch (e) {
        tiled.warn("Failed to update route in " + tmxPath + ": " + e);
        return false;
    }
}

/**
 * Fix orphaned routes in a single open map using the Tiled API
 * @param {TileMap} map - The open map to fix
 * @returns {Object} - {fixedCount, orphanedCount, report: string[]}
 */
function fixOrphanedRoutesInMap(map) {
    const result = { fixedCount: 0, orphanedCount: 0, report: [] };

    // Collect all guardians and routes from the map
    const allGuardians = [];
    const allRoutes = [];

    for (let i = 0; i < map.layerCount; i++) {
        const layer = map.layerAt(i);
        if (!layer.isObjectLayer) continue;

        for (let j = 0; j < layer.objectCount; j++) {
            const obj = layer.objectAt(j);
            if (isGuardianObject(obj, map)) {
                allGuardians.push(obj);
            } else if (isRouteObject(obj)) {
                allRoutes.push(obj);
            }
        }
    }

    // Build set of valid guardian IDs in the map
    const validGuardianIds = new Set(allGuardians.map(g => g.id));

    // Find which guardians are already assigned to (non-orphaned) routes
    const assignedGuardianIds = new Set();
    for (const route of allRoutes) {
        if (!isRouteOrphaned(route, validGuardianIds)) {
            const guardianRef = route.property("Guardian");
            if (typeof guardianRef === "object" && guardianRef.id) {
                assignedGuardianIds.add(guardianRef.id);
            } else if (typeof guardianRef === "number" && guardianRef !== 0) {
                assignedGuardianIds.add(guardianRef);
            }
        }
    }

    // Find orphaned routes (blank ref, zero ref, or dangling ref to non-existent object)
    const orphanedRoutes = allRoutes.filter(route => isRouteOrphaned(route, validGuardianIds));

    // Find unassigned guardians
    const unassignedGuardians = allGuardians.filter(g => !assignedGuardianIds.has(g.id));

    // Try to auto-fix each orphaned route
    for (const route of orphanedRoutes) {
        // Calculate bounds from polyline
        const points = route.polygon || [];
        const routeRect = getPolylineBounds(route.x, route.y, points);

        // Find overlapping unassigned guardians
        const overlapping = unassignedGuardians.filter(g => {
            const gHeight = g.height || 16;
            const gWidth = g.width || 16;
            const guardianRect = {
                x: g.x,
                y: g.y - gHeight,
                width: gWidth,
                height: gHeight
            };
            return rectsOverlap(routeRect, guardianRect);
        });

        if (overlapping.length === 1) {
            // Unambiguous - auto-fix
            const guardian = overlapping[0];
            route.setProperty("Guardian", guardian);
            const guardianDesc = guardian.name || ("Guardian " + guardian.id);
            result.report.push("Route " + route.id + " -> " + guardianDesc);
            result.fixedCount++;

            // Mark guardian as assigned
            assignedGuardianIds.add(guardian.id);
            const idx = unassignedGuardians.indexOf(guardian);
            if (idx >= 0) unassignedGuardians.splice(idx, 1);
        } else {
            result.orphanedCount++;
        }
    }

    return result;
}

/**
 * Fix orphaned routes across all rooms
 */
function fixOrphanedRoutes() {
    const folder = getMapFolder();
    if (!folder) {
        tiled.alert("Please open a map file first.");
        return;
    }

    const existingIds = getExistingRoomIds(folder);
    if (existingIds.length === 0) {
        tiled.alert("No rooms found in folder.");
        return;
    }

    const report = [];
    let fixedCount = 0;
    let orphanedRouteCount = 0;
    let unassignedGuardianCount = 0;

    for (const roomId of existingIds) {
        const tmxPath = folder + "/" + String(roomId).padStart(3, '0') + ".tmx";
        const roomData = parseRoomObjects(tmxPath);

        const roomLabel = String(roomId).padStart(3, '0') + (roomData.roomName ? ": " + roomData.roomName : "");

        // Build set of valid guardian IDs in this room
        const validGuardianIds = new Set(roomData.guardians.map(g => g.id));

        // Find which guardians are assigned to valid (non-orphaned) routes
        const assignedGuardianIds = new Set();
        for (const route of roomData.routes) {
            if (route.guardianId && route.guardianId !== "" && route.guardianId !== "0"
                && validGuardianIds.has(route.guardianId)) {
                assignedGuardianIds.add(route.guardianId);
            }
        }

        // Find orphaned routes (empty/zero guardianId, or references non-existent guardian)
        const orphanedRoutes = roomData.routes.filter(r =>
            !r.guardianId || r.guardianId === "" || r.guardianId === "0"
            || !validGuardianIds.has(r.guardianId));

        // Find unassigned guardians (guardians not referenced by any valid route)
        const unassignedGuardians = roomData.guardians.filter(g => !assignedGuardianIds.has(g.id));

        // Try to auto-fix unambiguous cases
        const roomReportLines = [];
        const fixedInRoom = [];

        for (const route of orphanedRoutes) {
            // Route bounds are pre-calculated from polyline in parseRoomObjects
            const routeRect = {
                x: route.x,
                y: route.y,
                width: route.width,
                height: route.height
            };

            // Find unassigned guardians that overlap this route
            const overlappingGuardians = unassignedGuardians.filter(g => {
                // Guardian y is bottom of sprite, convert to top-left
                // Most guardians are 16x16
                const gHeight = g.height || 16;
                const gWidth = g.width || 16;
                const guardianRect = {
                    x: g.x,
                    y: g.y - gHeight,
                    width: gWidth,
                    height: gHeight
                };
                return rectsOverlap(routeRect, guardianRect);
            });

            if (overlappingGuardians.length === 1) {
                // Unambiguous case - auto-fix
                const guardian = overlappingGuardians[0];
                if (assignGuardianToRoute(tmxPath, route.id, guardian.id)) {
                    fixedCount++;
                    const guardianDesc = guardian.name || ("Guardian " + guardian.id);
                    fixedInRoom.push("  Fixed: Route " + route.id + " -> " + guardianDesc);
                    // Mark this guardian as assigned so we don't try to assign it again
                    assignedGuardianIds.add(guardian.id);
                    // Remove from unassigned list
                    const idx = unassignedGuardians.indexOf(guardian);
                    if (idx >= 0) unassignedGuardians.splice(idx, 1);
                }
            } else if (overlappingGuardians.length === 0) {
                orphanedRouteCount++;
                roomReportLines.push("  Orphaned Route " + route.id + " at (" + route.x + ", " + route.y + ") - no overlapping guardians");
            } else {
                orphanedRouteCount++;
                const guardianList = overlappingGuardians.map(g => g.name || ("Guardian " + g.id)).join(", ");
                roomReportLines.push("  Orphaned Route " + route.id + " at (" + route.x + ", " + route.y + ") - multiple overlapping guardians: " + guardianList);
            }
        }

        // Report remaining unassigned guardians
        for (const guardian of unassignedGuardians) {
            unassignedGuardianCount++;
            const gY = guardian.y - (guardian.height || 16);
            const guardianDesc = guardian.name || ("Guardian " + guardian.id);
            roomReportLines.push("  Unassigned " + guardianDesc + " at (" + guardian.x + ", " + gY + ")");
        }

        // Add room to report if it has issues or fixes
        if (fixedInRoom.length > 0 || roomReportLines.length > 0) {
            report.push("Room " + roomLabel);
            for (const line of fixedInRoom) {
                report.push(line);
            }
            for (const line of roomReportLines) {
                report.push(line);
            }
            report.push("");
        }
    }

    // Build summary
    const summary = [
        "=== Route Fix Summary ===",
        "Routes auto-fixed: " + fixedCount,
        "Remaining orphaned routes: " + orphanedRouteCount,
        "Unassigned guardians: " + unassignedGuardianCount,
        ""
    ];

    const fullReport = summary.concat(report);

    // Show dialog with report
    const dialog = new Dialog("Route Fix Report");
    dialog.minimumWidth = 600;
    dialog.newRowMode = Dialog.ManualRows;

    dialog.addHeading("Routes auto-fixed: " + fixedCount);
    dialog.addNewRow();
    dialog.addHeading("Remaining orphaned routes: " + orphanedRouteCount);
    dialog.addNewRow();
    dialog.addHeading("Unassigned guardians: " + unassignedGuardianCount);
    dialog.addNewRow();
    dialog.addSeparator();

    // Add scrollable text area with report
    dialog.addNewRow();
    const reportText = dialog.addTextEdit("");
    reportText.plainText = fullReport.join("\n");
    reportText.readOnly = true;

    dialog.addNewRow();
    const saveButton = dialog.addButton("Save Report");
    const closeButton = dialog.addButton("Close");

    saveButton.clicked.connect(function() {
        const reportPath = folder + "/route_report.txt";
        try {
            const outFile = new TextFile(reportPath, TextFile.WriteOnly);
            outFile.write(fullReport.join("\n"));
            outFile.close();
            tiled.log("Report saved to: " + reportPath);
            tiled.alert("Report saved to:\n" + reportPath);
        } catch (e) {
            tiled.alert("Failed to save report: " + e);
        }
    });

    closeButton.clicked.connect(function() {
        dialog.accept();
    });

    dialog.show();
}

/**
 * Load guardian names from guardians.txt in the tilesets folder
 * @param {string} folder - The map folder path (e.g., tmx/content/main)
 */
function loadGuardianNames(folder) {
    if (guardianNamesLoaded) return;

    // Guardian names are in tmx/tilesets/guardians.txt
    const contentFolder = FileInfo.path(folder);  // e.g., tmx/content or tmx/_in_progress
    const tmxFolder = FileInfo.path(contentFolder);  // tmx/
    const tilesetsFolder = tmxFolder + "/tilesets";

    // Load all guardian names from single file (one line per tile)
    const guardiansFile = tilesetsFolder + "/guardians.txt";
    if (File.exists(guardiansFile)) {
        try {
            const file = new TextFile(guardiansFile, TextFile.ReadOnly);
            const content = file.readAll();
            file.close();
            guardianNames = content.split("\n").map(line => line.trim()).filter(line => line.length > 0);

            // Extract periscope tank and evil head names from lines 74-75 (tiles 73-74)
            if (guardianNames.length > LOCAL_ID_PERISCOPE_TANK) {
                periscopeTankName = guardianNames[LOCAL_ID_PERISCOPE_TANK];
            }
            if (guardianNames.length > LOCAL_ID_EVIL_GIANT_HEAD) {
                evilHeadName = guardianNames[LOCAL_ID_EVIL_GIANT_HEAD];
            }
        } catch (e) {
            tiled.warn("Failed to load guardians.txt: " + e);
        }
    }

    guardianNamesLoaded = true;
}

/**
 * Get the base name of a guardian from its GID (without numbering)
 * @param {number} gid - The GID (with flip flags stripped)
 * @param {TileMap} map - The map (for dynamic firstGid lookup)
 * @returns {string|null} - The guardian name or null
 */
function getGuardianBaseName(gid, map) {
    // Get dynamic firstGid from map tilesets
    const guardiansFirstGid = getTilesetFirstGid(map, TILESET_GUARDIANS);
    if (guardiansFirstGid === null) return null;

    // Calculate tile index within guardians collection
    const index = gid - guardiansFirstGid;

    // Check for oversized guardians (now tiles 73-74 in collection)
    if (index === LOCAL_ID_PERISCOPE_TANK) {
        return periscopeTankName;
    } else if (index === LOCAL_ID_EVIL_GIANT_HEAD) {
        return evilHeadName;
    } else if (index >= 0 && index < guardianNames.length) {
        // Normal guardian - index into guardianNames
        return guardianNames[index];
    }
    return null;
}

/**
 * Check if an object is a guardian (type="Guardian" or type="Arrow", or by GID range)
 * @param {MapObject} obj - The map object
 * @param {TileMap} [map] - Optional map (uses activeAsset if not provided)
 * @returns {boolean}
 */
function isGuardianObject(obj, map) {
    if (!obj) return false;
    // Check by type first
    if (obj.type === "Guardian" || obj.type === "Arrow") return true;
    // Also detect by GID range (for objects missing type attribute)
    const activeMap = map || tiled.activeAsset;
    if (!activeMap || !activeMap.isTileMap) return false;

    const gid = getObjectGid(obj, activeMap);
    if (gid !== null) {
        const rawGid = gid & 0x0FFFFFFF; // Strip flip flags

        // Check if GID falls within guardians collection
        const guardiansFirstGid = getTilesetFirstGid(activeMap, TILESET_GUARDIANS);
        if (guardiansFirstGid !== null) {
            const localId = rawGid - guardiansFirstGid;
            if (localId >= 0 && localId < getGuardiansTileCount(activeMap)) return true;
        }
    }
    return false;
}

/**
 * Check if an object is a route (type="Route" or name="Route" for template-based objects)
 * @param {MapObject} obj - The map object
 * @returns {boolean}
 */
function isRouteObject(obj) {
    if (!obj) return false;
    // Check type first (standard case)
    if (obj.type === "Route") return true;
    // Also check name for template-based objects where type may be inherited from template
    // but not directly accessible via obj.type
    if (obj.name === "Route") return true;
    return false;
}

/**
 * Check if a route's Guardian reference points to a valid object in the map.
 * Returns true if the route is orphaned (no ref, zero ref, or dangling ref).
 * @param {MapObject} route - The route object
 * @param {Set<number>} validGuardianIds - Set of guardian object IDs that exist in the map
 * @returns {boolean}
 */
function isRouteOrphaned(route, validGuardianIds) {
    const guardianRef = route.property("Guardian");
    if (guardianRef === null || guardianRef === undefined) return true;
    if (typeof guardianRef === "object") {
        if (!guardianRef.id || guardianRef.id === 0) return true;
        // Check the referenced object actually exists
        return !validGuardianIds.has(guardianRef.id);
    }
    if (typeof guardianRef === "number") {
        if (guardianRef === 0) return true;
        return !validGuardianIds.has(guardianRef);
    }
    return true;
}

/**
 * Check if an object is an arrow (type="Arrow" or by GID for arrow tiles)
 * @param {MapObject} obj - The map object
 * @param {TileMap} [map] - Optional map (uses activeAsset if not provided)
 * @returns {boolean}
 */
function isArrowObject(obj, map) {
    if (!obj) return false;
    // Check by type first
    if (obj.type === "Arrow") return true;
    // Also detect by GID range (for objects missing type attribute)
    const activeMap = map || tiled.activeAsset;
    if (!activeMap || !activeMap.isTileMap) return false;

    const gid = getObjectGid(obj, activeMap);
    if (gid !== null) {
        const rawGid = gid & 0x0FFFFFFF; // Strip flip flags
        const arrowLeftGid = getGuardianGid(activeMap, LOCAL_ID_ARROW_LEFT);
        const arrowRightGid = getGuardianGid(activeMap, LOCAL_ID_ARROW_RIGHT);
        if (rawGid === arrowLeftGid || rawGid === arrowRightGid) {
            return true;
        }
    }
    return false;
}

/**
 * Fix properties on a single guardian or route object
 * @param {MapObject} obj - The map object to fix
 * @param {Object} guardianCounts - Map of base name to count (for numbering)
 * @param {Object} guardianInstances - Map of base name to current instance number
 * @returns {Object} - {changes: [], wasModified: boolean}
 */
function fixObjectProperties(obj, guardianCounts, guardianInstances, map) {
    const changes = [];
    let wasModified = false;
    const activeMap = map || tiled.activeAsset;

    if (isGuardianObject(obj, activeMap)) {
        const gid = getObjectGid(obj, activeMap);
        if (gid === null) return { changes, wasModified };
        const rawGid = gid & 0x0FFFFFFF;
        const baseName = getGuardianBaseName(rawGid, activeMap);

        // Set correct type if missing or wrong
        const arrowLeftGid = getGuardianGid(activeMap, LOCAL_ID_ARROW_LEFT);
        const arrowRightGid = getGuardianGid(activeMap, LOCAL_ID_ARROW_RIGHT);
        const isArrow = (rawGid === arrowLeftGid || rawGid === arrowRightGid);
        const expectedType = isArrow ? "Arrow" : "Guardian";
        if (obj.type !== expectedType) {
            changes.push("Type: '" + (obj.type || "") + "' -> '" + expectedType + "'");
            obj.type = expectedType;
            wasModified = true;
        }

        if (baseName) {
            // Calculate name with numbering if needed
            let newName = baseName;
            if (guardianCounts && guardianInstances) {
                guardianInstances[baseName] = (guardianInstances[baseName] || 0) + 1;
                if (guardianCounts[baseName] > 1) {
                    newName = baseName + " " + guardianInstances[baseName];
                }
            }

            // Always refresh the name
            if (obj.name !== newName) {
                changes.push("Name: '" + obj.name + "' -> '" + newName + "'");
            }
            obj.name = newName;
            wasModified = true;
        }

        // Check Color property - add if missing (default to white)
        // Use tiled.color() to create a proper color type
        if (obj.property("Color") === undefined) {
            obj.setProperty("Color", tiled.color("white"));
            changes.push("Added Color: white");
            wasModified = true;
        }

        // For arrows, check FlightDirection and Speed
        // For non-arrows, check Flags
        if (isArrowObject(obj)) {
            if (obj.property("FlightDirection") === undefined) {
                obj.setProperty("FlightDirection", tiled.propertyValue("FlightDirection", 0));
                changes.push("Added FlightDirection: 0");
                wasModified = true;
            }
            if (obj.property("Speed") === undefined) {
                obj.setProperty("Speed", tiled.propertyValue("Speed", 4));
                changes.push("Added Speed: 4");
                wasModified = true;
            }
        } else {
            // Non-arrow guardians need Flags property (GuardianFlags type)
            if (obj.property("Flags") === undefined) {
                obj.setProperty("Flags", tiled.propertyValue("GuardianFlags", ""));
                changes.push("Added Flags: (none)");
                wasModified = true;
            }
        }
    } else if (isRouteObject(obj)) {
        // Routes need Direction, Guardian, Speed, and Traversal properties
        if (obj.property("Direction") === undefined) {
            obj.setProperty("Direction", tiled.propertyValue("Direction", 0));
            changes.push("Added Direction: 0");
            wasModified = true;
        }
        if (obj.property("Speed") === undefined) {
            obj.setProperty("Speed", tiled.propertyValue("Speed", 1));
            changes.push("Added Speed: 1");
            wasModified = true;
        }
        if (obj.property("Traversal") === undefined) {
            obj.setProperty("Traversal", tiled.propertyValue("Traversal", 0));
            changes.push("Added Traversal: 0 (ping-pong)");
            wasModified = true;
        }
        // Guardian property should exist but may be empty - don't add a default
    }

    return { changes, wasModified };
}

/**
 * Count guardians by base name in a map for numbering
 * @param {TileMap} map - The map to scan
 * @returns {Object} - Map of base name to count
 */
function countGuardiansByType(map) {
    const counts = {};

    for (let i = 0; i < map.layerCount; i++) {
        const layer = map.layerAt(i);
        if (!layer.isObjectLayer) continue;

        for (let j = 0; j < layer.objectCount; j++) {
            const obj = layer.objectAt(j);
            if (isGuardianObject(obj, map)) {
                const gid = getObjectGid(obj, map);
                if (gid === null) continue;
                const rawGid = gid & 0x0FFFFFFF;
                const baseName = getGuardianBaseName(rawGid, map);
                if (baseName) {
                    counts[baseName] = (counts[baseName] || 0) + 1;
                }
            }
        }
    }

    return counts;
}

/**
 * Fix/add missing room properties in the current map
 */
function fixRoomProperties() {
    const map = tiled.activeAsset;
    if (!map || !map.isTileMap) {
        tiled.alert("Please open a map file first.");
        return;
    }

    const folder = getMapFolder();
    if (!folder) {
        tiled.alert("Map must be saved first.");
        return;
    }

    const report = [];
    let totalFixed = 0;

    // Check and add missing room properties
    // Flags (RoomFlags type)
    if (map.property("Flags") === undefined) {
        map.setProperty("Flags", tiled.propertyValue("RoomFlags", ""));
        report.push("Added Flags: (none)");
        totalFixed++;
    }

    // Rope Offset (int)
    if (map.property("Rope Offset") === undefined) {
        map.setProperty("Rope Offset", 0);
        report.push("Added Rope Offset: 0");
        totalFixed++;
    }

    // Rope (bool) - ensure it exists
    if (map.property("Rope") === undefined) {
        map.setProperty("Rope", false);
        report.push("Added Rope: false");
        totalFixed++;
    }

    // Name (string) - ensure it exists
    if (map.property("Name") === undefined) {
        map.setProperty("Name", "");
        report.push("Added Name: (empty)");
        totalFixed++;
    }

    // Direction properties (file type) - ensure they exist
    const directions = ["Up", "Down", "Left", "Right"];
    for (const dir of directions) {
        if (map.property(dir) === undefined) {
            map.setProperty(dir, "");
            report.push("Added " + dir + ": (none)");
            totalFixed++;
        }
    }

    // WillySuit (WillySuit enum type)
    if (map.property("WillySuit") === undefined) {
        map.setProperty("WillySuit", tiled.propertyValue("WillySuit", "Normal"));
        report.push("Added WillySuit: Normal");
        totalFixed++;
    }

    // Show dialog with report
    const dialog = new Dialog("Room Properties Report");
    dialog.minimumWidth = 400;
    dialog.newRowMode = Dialog.ManualRows;

    dialog.addHeading("Properties fixed/added: " + totalFixed);
    dialog.addNewRow();
    dialog.addSeparator();

    dialog.addNewRow();
    const reportText = dialog.addTextEdit("");
    if (report.length > 0) {
        reportText.plainText = report.join("\n");
    } else {
        reportText.plainText = "All room properties are present.";
    }
    reportText.readOnly = true;

    dialog.addNewRow();
    const saveButton = dialog.addButton("Save Report");
    const closeButton = dialog.addButton("Close");

    saveButton.clicked.connect(function() {
        const reportPath = folder + "/room_properties_report.txt";
        try {
            const outFile = new TextFile(reportPath, TextFile.WriteOnly);
            outFile.write("Properties fixed/added: " + totalFixed + "\n\n");
            outFile.write(report.join("\n"));
            outFile.close();
            tiled.log("Report saved to: " + reportPath);
            tiled.alert("Report saved to:\n" + reportPath);
        } catch (e) {
            tiled.alert("Failed to save report: " + e);
        }
    });

    closeButton.clicked.connect(function() {
        dialog.accept();
    });

    dialog.show();
}

/**
 * Fix all guardian/route properties in the current map
 */
function fixAllGuardianProperties() {
    const map = tiled.activeAsset;
    if (!map || !map.isTileMap) {
        tiled.alert("Please open a map file first.");
        return;
    }

    const folder = getMapFolder();
    if (!folder) {
        tiled.alert("Map must be saved first.");
        return;
    }

    // Load guardian names
    loadGuardianNames(folder);

    // Count guardians by type for numbering
    const guardianCounts = countGuardiansByType(map);
    const guardianInstances = {};

    const report = [];
    let totalFixed = 0;
    let objectsChecked = 0;

    // Iterate all object layers
    tiled.log("Scanning " + map.layerCount + " layers in " + map.fileName);
    for (let i = 0; i < map.layerCount; i++) {
        const layer = map.layerAt(i);
        tiled.log("  Layer " + i + ": " + layer.name + " isObjectLayer=" + layer.isObjectLayer);
        if (!layer.isObjectLayer) continue;

        tiled.log("  Found " + layer.objectCount + " objects in layer " + layer.name);
        for (let j = 0; j < layer.objectCount; j++) {
            const obj = layer.objectAt(j);

            const isGuardian = isGuardianObject(obj, map);
            const isRoute = isRouteObject(obj);

            if (!isGuardian && !isRoute) continue;

            objectsChecked++;
            const result = fixObjectProperties(obj, guardianCounts, guardianInstances, map);

            if (result.changes.length > 0) {
                const objDesc = obj.name || ("Object " + obj.id);
                report.push(objDesc + ":");
                for (const change of result.changes) {
                    report.push("  " + change);
                    totalFixed++;
                }
            }
        }
    }

    // Also fix orphaned routes in this map
    const orphanResult = fixOrphanedRoutesInMap(map);
    if (orphanResult.fixedCount > 0) {
        report.push("");
        report.push("Orphaned routes fixed:");
        for (const line of orphanResult.report) {
            report.push("  " + line);
            totalFixed++;
        }
    }

    // Show dialog with report
    const dialog = new Dialog("Guardian/Route Properties Report");
    dialog.minimumWidth = 600;
    dialog.newRowMode = Dialog.ManualRows;

    dialog.addHeading("Objects checked: " + objectsChecked);
    dialog.addNewRow();
    dialog.addHeading("Properties fixed/updated: " + totalFixed);
    if (orphanResult.fixedCount > 0) {
        dialog.addNewRow();
        dialog.addHeading("Orphaned routes fixed: " + orphanResult.fixedCount);
    }
    dialog.addNewRow();
    dialog.addSeparator();

    dialog.addNewRow();
    const reportText = dialog.addTextEdit("");
    if (report.length > 0) {
        reportText.plainText = report.join("\n");
    } else {
        reportText.plainText = "All guardian and route properties are correct.";
    }
    reportText.readOnly = true;

    dialog.addNewRow();
    const saveButton = dialog.addButton("Save Report");
    const closeButton = dialog.addButton("Close");

    saveButton.clicked.connect(function() {
        const reportPath = folder + "/properties_report.txt";
        try {
            const outFile = new TextFile(reportPath, TextFile.WriteOnly);
            outFile.write("Objects checked: " + objectsChecked + "\n");
            outFile.write("Properties fixed/updated: " + totalFixed + "\n\n");
            outFile.write(report.join("\n"));
            outFile.close();
            tiled.log("Report saved to: " + reportPath);
            tiled.alert("Report saved to:\n" + reportPath);
        } catch (e) {
            tiled.alert("Failed to save report: " + e);
        }
    });

    closeButton.clicked.connect(function() {
        dialog.accept();
    });

    dialog.show();
}

/**
 * Fix properties on the currently selected guardian/route
 */
function fixSelectedGuardianProperties() {
    const map = tiled.activeAsset;
    if (!map || !map.isTileMap) {
        tiled.alert("Please open a map file first.");
        return;
    }

    const folder = getMapFolder();
    if (!folder) {
        tiled.alert("Map must be saved first.");
        return;
    }

    const selected = map.selectedObjects;
    if (!selected || selected.length === 0) {
        tiled.alert("No objects selected.");
        return;
    }

    // Load guardian names
    loadGuardianNames(folder);

    // Count guardians by type for numbering (full map scan needed for correct numbering)
    const guardianCounts = countGuardiansByType(map);
    const guardianInstances = {};

    // We need to process objects in order to get correct instance numbers
    // First pass: assign instance numbers to all guardians up to and including selected ones
    let foundSelected = false;
    for (let i = 0; i < map.layerCount && !foundSelected; i++) {
        const layer = map.layerAt(i);
        if (!layer.isObjectLayer) continue;

        for (let j = 0; j < layer.objectCount; j++) {
            const obj = layer.objectAt(j);
            if (!isGuardianObject(obj, map)) continue;

            const gid = getObjectGid(obj, map);
            if (gid === null) continue;
            const rawGid = gid & 0x0FFFFFFF;
            const baseName = getGuardianBaseName(rawGid, map);
            if (baseName) {
                guardianInstances[baseName] = (guardianInstances[baseName] || 0) + 1;
            }

            // Check if this is one of our selected objects
            if (selected.includes(obj)) {
                foundSelected = true;
            }
        }
    }

    // Reset instances and process selected objects properly
    const instancesForSelected = {};
    let fixedCount = 0;

    for (const obj of selected) {
        if (!isGuardianObject(obj, map) && !isRouteObject(obj)) continue;

        // For guardians, we need to figure out the correct instance number
        // This is a simplification - we just use the count as-is for selected
        const result = fixObjectProperties(obj, guardianCounts, instancesForSelected, map);
        if (result.wasModified) {
            fixedCount++;
        }
    }

    // Also fix orphaned routes if any selected routes are orphaned
    const selectedRoutes = selected.filter(obj => isRouteObject(obj));
    let orphanFixedCount = 0;

    if (selectedRoutes.length > 0) {
        // Collect all guardians from the map
        const allGuardians = [];
        for (let i = 0; i < map.layerCount; i++) {
            const layer = map.layerAt(i);
            if (!layer.isObjectLayer) continue;
            for (let j = 0; j < layer.objectCount; j++) {
                const obj = layer.objectAt(j);
                if (isGuardianObject(obj, map)) {
                    allGuardians.push(obj);
                }
            }
        }

        // Collect all routes to find which guardians are already assigned
        const allRoutes = [];
        for (let i = 0; i < map.layerCount; i++) {
            const layer = map.layerAt(i);
            if (!layer.isObjectLayer) continue;
            for (let j = 0; j < layer.objectCount; j++) {
                const obj = layer.objectAt(j);
                if (isRouteObject(obj)) {
                    allRoutes.push(obj);
                }
            }
        }

        // Build set of valid guardian IDs
        const validGuardianIds = new Set(allGuardians.map(g => g.id));

        // Find which guardians are already assigned to non-orphaned routes
        const assignedGuardianIds = new Set();
        for (const route of allRoutes) {
            if (!isRouteOrphaned(route, validGuardianIds)) {
                const guardianRef = route.property("Guardian");
                if (typeof guardianRef === "object" && guardianRef.id) {
                    assignedGuardianIds.add(guardianRef.id);
                } else if (typeof guardianRef === "number" && guardianRef !== 0) {
                    assignedGuardianIds.add(guardianRef);
                }
            }
        }

        // Find unassigned guardians
        const unassignedGuardians = allGuardians.filter(g => !assignedGuardianIds.has(g.id));

        // Try to fix orphaned selected routes
        for (const route of selectedRoutes) {
            if (!isRouteOrphaned(route, validGuardianIds)) continue;

            // Calculate bounds from polyline
            const points = route.polygon || [];
            const routeRect = getPolylineBounds(route.x, route.y, points);

            // Find overlapping unassigned guardians
            const overlapping = unassignedGuardians.filter(g => {
                const gHeight = g.height || 16;
                const gWidth = g.width || 16;
                const guardianRect = {
                    x: g.x,
                    y: g.y - gHeight,
                    width: gWidth,
                    height: gHeight
                };
                return rectsOverlap(routeRect, guardianRect);
            });

            if (overlapping.length === 1) {
                const guardian = overlapping[0];
                route.setProperty("Guardian", guardian);
                orphanFixedCount++;

                // Mark guardian as assigned for subsequent routes
                assignedGuardianIds.add(guardian.id);
                const idx = unassignedGuardians.indexOf(guardian);
                if (idx >= 0) unassignedGuardians.splice(idx, 1);
            }
        }
    }

    // Build report
    const report = [];

    if (fixedCount > 0) {
        report.push("Properties fixed on " + fixedCount + " object(s).");
    }
    if (orphanFixedCount > 0) {
        report.push("Orphaned routes fixed: " + orphanFixedCount);
    }

    // Show dialog with report
    const dialog = new Dialog("Selected Guardian/Route Properties Report");
    dialog.minimumWidth = 400;
    dialog.newRowMode = Dialog.ManualRows;

    dialog.addHeading("Objects checked: " + selected.length);
    dialog.addNewRow();
    dialog.addHeading("Properties fixed: " + fixedCount);
    if (orphanFixedCount > 0) {
        dialog.addNewRow();
        dialog.addHeading("Orphaned routes fixed: " + orphanFixedCount);
    }
    dialog.addNewRow();
    dialog.addSeparator();

    dialog.addNewRow();
    const reportText = dialog.addTextEdit("");
    if (report.length > 0) {
        reportText.plainText = report.join("\n");
    } else {
        reportText.plainText = "All selected guardian and route properties are correct.";
    }
    reportText.readOnly = true;

    dialog.addNewRow();
    const closeButton = dialog.addButton("Close");

    closeButton.clicked.connect(function() {
        dialog.accept();
    });

    dialog.show();
}

/**
 * Update the Fix Selected action based on current selection
 */
function updateFixSelectedAction() {
    const map = tiled.activeAsset;
    if (!map || !map.isTileMap) {
        fixSelectedAction.enabled = false;
        return;
    }

    const selected = map.selectedObjects;
    if (!selected || selected.length === 0) {
        fixSelectedAction.enabled = false;
        return;
    }

    // Check if any selected object is a guardian or route
    const hasValidSelection = selected.some(obj =>
        isGuardianObject(obj, map) || isRouteObject(obj)
    );

    fixSelectedAction.enabled = hasValidSelection;
}

/**
 * Connect selection changed signal for the current map
 */
let currentMapConnection = null;

function connectSelectionSignal() {
    // Disconnect previous connection
    if (currentMapConnection) {
        try {
            currentMapConnection.disconnect();
        } catch (e) {
            // Ignore disconnect errors
        }
        currentMapConnection = null;
    }

    const map = tiled.activeAsset;
    if (map && map.isTileMap) {
        currentMapConnection = map.selectedObjectsChanged.connect(updateFixSelectedAction);
    }

    updateFixSelectedAction();
}

// =============================================================================
// Validate Spawn Points
// =============================================================================

// Team names by value (matches constants.py TEAM_* values)
const TEAM_NAMES = { 0: "Neutral", 1: "Red", 2: "Blue", 3: "It", 4: "Green", 5: "Orange" };
// Kind names by value
const SPAWN_KIND_NAMES = { 0: "Player Start", 1: "Flag", 2: "Exit", 3: "Ball Spawn" };

// GameMode + MapFlags bit values (matches game_settings.py GameMode/MapFlags IntFlag)
const GAME_MODE_BITS = {
    0x0001: "COLLECT",
    0x0002: "TIMED",
    0x0004: "RACE",
    0x0008: "DISCOVERY",
    0x0010: "GOLDEN",
    0x0020: "TAG",
    0x0040: "BULLDOG",
    0x0080: "TEAMS",
    0x0100: "CTF",
    0x0200: "LOBBY",
    0x0400: "F2C",
    0x0800: "COLLECT_ALL",
    0x1000: "CHAIN",
    0x2000: "IT",
    0x4000: "MM_START",
    0x8000: "WILLY_BALL"
};

/**
 * Format a GameModes bitmask as a human-readable string
 * @param {number} modes - GameModes bitmask
 * @returns {string} - Formatted string like "COLLECT|TIMED" or "ALL" or "(none)"
 */
function formatGameModes(modes) {
    if (modes === 0) return "ALL";
    const names = [];
    for (const bit in GAME_MODE_BITS) {
        if (modes & parseInt(bit)) {
            names.push(GAME_MODE_BITS[bit]);
        }
    }
    return names.length > 0 ? names.join("|") : "(none)";
}

/**
 * Parse spawn points from a TMX file using text parsing (fast, no need to open in Tiled)
 * @param {string} tmxPath - Path to the TMX file
 * @returns {Array} - Array of {kind, team, gameModes, x, y} objects
 */
function parseSpawnPoints(tmxPath) {
    const spawns = [];

    try {
        const file = new TextFile(tmxPath, TextFile.ReadOnly);
        const content = file.readAll();
        file.close();

        // Find all objects in Spawn layer
        // Look for objectgroup named "Spawn"
        const spawnGroupRegex = /<objectgroup[^>]*name="Spawn"[^>]*>([\s\S]*?)<\/objectgroup>/;
        const groupMatch = content.match(spawnGroupRegex);
        if (!groupMatch) return spawns;

        const groupContent = groupMatch[1];

        // Parse each object in the Spawn group
        const objectRegex = /<object\s+([^>]*?)(?:\/>|>([\s\S]*?)<\/object>)/g;
        let objMatch;

        while ((objMatch = objectRegex.exec(groupContent)) !== null) {
            const attrs = objMatch[1];
            const innerContent = objMatch[2] || "";

            // Get object position
            const xMatch = attrs.match(/x="([^"]+)"/);
            const yMatch = attrs.match(/y="([^"]+)"/);
            const x = xMatch ? parseFloat(xMatch[1]) : 0;
            const y = yMatch ? parseFloat(yMatch[1]) : 0;

            // Check for template reference
            const templateMatch = attrs.match(/template="([^"]+)"/);

            // Default values from template
            let kind = 0;
            let team = 0;
            let gameModes = 0;

            if (templateMatch) {
                const templateName = templateMatch[1];
                // Extract defaults from template filename
                if (templateName.includes("flag_red")) { kind = 1; team = 1; }
                else if (templateName.includes("flag_blue")) { kind = 1; team = 2; }
                else if (templateName.includes("flag_green")) { kind = 1; team = 4; }
                else if (templateName.includes("flag_orange")) { kind = 1; team = 5; }
                else if (templateName.includes("flag_neutral")) { kind = 1; team = 0; }
                else if (templateName.includes("player_red")) { kind = 0; team = 1; }
                else if (templateName.includes("player_blue")) { kind = 0; team = 2; }
                else if (templateName.includes("player_green")) { kind = 0; team = 4; }
                else if (templateName.includes("player_orange")) { kind = 0; team = 5; }
                else if (templateName.includes("spawn_player")) { kind = 0; team = 0; }
                else if (templateName.includes("spawn_ball")) { kind = 3; team = 0; }
            }

            // Check for per-object property overrides
            if (innerContent) {
                const kindMatch = innerContent.match(/<property\s+name="Kind"[^>]*value="(\d+)"/);
                const teamMatch = innerContent.match(/<property\s+name="Team"[^>]*value="(\d+)"/);
                const modesMatch = innerContent.match(/<property\s+name="GameModes"[^>]*value="(\d+)"/);

                if (kindMatch) kind = parseInt(kindMatch[1]);
                if (teamMatch) team = parseInt(teamMatch[1]);
                if (modesMatch) gameModes = parseInt(modesMatch[1]);
            }

            spawns.push({ kind: kind, team: team, gameModes: gameModes, x: x, y: y });
        }
    } catch (e) {
        tiled.warn("Failed to parse spawns in " + tmxPath + ": " + e);
    }

    return spawns;
}

/**
 * Validate spawn points across all rooms in the map
 */
function validateSpawnPoints() {
    let folder = getMapFolder();

    // If no map is open, try to find a loaded world
    if (!folder) {
        const worlds = tiled.worlds;
        if (worlds.length === 0) {
            tiled.alert("Please open a world file (.world) or map first.");
            return;
        }
        folder = getFolderFromWorld(worlds[0]);
    }

    if (!folder) {
        tiled.alert("Could not determine map folder.");
        return;
    }

    const mapName = getMapName(folder);
    const existingIds = getExistingRoomIds(folder);
    const roomInfo = getRoomInfo(folder, existingIds);

    if (existingIds.length === 0) {
        tiled.alert("No rooms found.");
        return;
    }

    const report = [];
    let totalSpawns = 0;
    let roomsWithSpawns = 0;
    let roomsWithoutSpawns = 0;

    // Track spawn coverage by team and kind
    const spawnsByTeam = {};       // team -> [{roomId, kind, gameModes, x, y}]
    const spawnsByKind = {};       // kind -> [{roomId, team, gameModes, x, y}]
    const roomsWithTeamSpawns = {}; // team -> Set of room IDs

    for (const roomId of existingIds) {
        const tmxPath = folder + "/" + String(roomId).padStart(3, '0') + ".tmx";
        const spawns = parseSpawnPoints(tmxPath);
        const info = roomInfo[roomId];
        const roomLabel = info ? info.label : String(roomId).padStart(3, '0');

        if (spawns.length === 0) {
            roomsWithoutSpawns++;
            continue;
        }

        roomsWithSpawns++;
        totalSpawns += spawns.length;

        const roomLines = [];
        for (const spawn of spawns) {
            const kindName = SPAWN_KIND_NAMES[spawn.kind] || ("Kind " + spawn.kind);
            const teamName = TEAM_NAMES[spawn.team] || ("Team " + spawn.team);
            const modesStr = formatGameModes(spawn.gameModes);

            roomLines.push("  " + kindName + " [" + teamName + "] Modes=" + modesStr +
                " (" + Math.round(spawn.x) + "," + Math.round(spawn.y) + ")");

            // Track by team
            if (!spawnsByTeam[spawn.team]) spawnsByTeam[spawn.team] = [];
            spawnsByTeam[spawn.team].push({ roomId: roomId, kind: spawn.kind, gameModes: spawn.gameModes });

            if (!roomsWithTeamSpawns[spawn.team]) roomsWithTeamSpawns[spawn.team] = new Set();
            roomsWithTeamSpawns[spawn.team].add(roomId);

            // Track by kind
            if (!spawnsByKind[spawn.kind]) spawnsByKind[spawn.kind] = [];
            spawnsByKind[spawn.kind].push({ roomId: roomId, team: spawn.team, gameModes: spawn.gameModes });
        }

        report.push("Room " + roomLabel + " (" + spawns.length + " spawn" + (spawns.length > 1 ? "s" : "") + "):");
        for (const line of roomLines) {
            report.push(line);
        }
        report.push("");
    }

    // Build summary
    const summary = [];
    summary.push("=== Spawn Point Validation for " + mapName + " ===");
    summary.push("");
    summary.push("Rooms scanned: " + existingIds.length);
    summary.push("Rooms with spawns: " + roomsWithSpawns);
    summary.push("Rooms without spawns: " + roomsWithoutSpawns);
    summary.push("Total spawn points: " + totalSpawns);
    summary.push("");

    // Team coverage summary
    summary.push("--- Team Coverage ---");
    for (let t = 0; t <= 5; t++) {
        const teamName = TEAM_NAMES[t] || ("Team " + t);
        const count = spawnsByTeam[t] ? spawnsByTeam[t].length : 0;
        const rooms = roomsWithTeamSpawns[t] ? roomsWithTeamSpawns[t].size : 0;
        if (count > 0) {
            summary.push(teamName + ": " + count + " spawn(s) in " + rooms + " room(s)");
        }
    }
    summary.push("");

    // Kind coverage summary
    summary.push("--- Kind Coverage ---");
    const playerStarts = spawnsByKind[0] || [];
    const flags = spawnsByKind[1] || [];
    summary.push("Player Starts: " + playerStarts.length);
    summary.push("Flags: " + flags.length);
    summary.push("");

    // Flag detail: list each flag with its team and room
    if (flags.length > 0) {
        summary.push("--- Flag Locations ---");
        for (const flag of flags) {
            const teamName = TEAM_NAMES[flag.team] || ("Team " + flag.team);
            const info = roomInfo[flag.roomId];
            const roomLabel = info ? info.label : String(flag.roomId).padStart(3, '0');
            const modesStr = formatGameModes(flag.gameModes);
            summary.push(teamName + " Flag in Room " + roomLabel + " (Modes=" + modesStr + ")");
        }
        summary.push("");
    }

    // Warnings
    const warnings = [];

    // Check: If any red spawns exist, blue should too (and vice versa)
    const hasRedStart = playerStarts.some(s => s.team === 1);
    const hasBlueStart = playerStarts.some(s => s.team === 2);
    if (hasRedStart && !hasBlueStart) warnings.push("WARNING: Red team player starts exist but no Blue team player starts");
    if (hasBlueStart && !hasRedStart) warnings.push("WARNING: Blue team player starts exist but no Red team player starts");

    // Check: If green spawns exist, orange should too (and vice versa)
    const hasGreenStart = playerStarts.some(s => s.team === 4);
    const hasOrangeStart = playerStarts.some(s => s.team === 5);
    if (hasGreenStart && !hasOrangeStart) warnings.push("WARNING: Green team player starts exist but no Orange team player starts");
    if (hasOrangeStart && !hasGreenStart) warnings.push("WARNING: Orange team player starts exist but no Green team player starts");

    // Check: No neutral player starts at all
    const hasNeutralStart = playerStarts.some(s => s.team === 0);
    if (!hasNeutralStart) warnings.push("WARNING: No neutral player start spawns found");

    // Flag/player-start cross-validation:
    // For each flag team, there must be a compatible player start of the same team.
    // "Compatible" means GameModes overlap (or either is 0 = ALL).
    for (let t = 0; t <= 5; t++) {
        const teamName = TEAM_NAMES[t] || ("Team " + t);
        const teamFlags = flags.filter(s => s.team === t);
        const teamStarts = playerStarts.filter(s => s.team === t);

        if (teamFlags.length > 0 && teamStarts.length === 0) {
            warnings.push("WARNING: " + teamName + " flag(s) exist but no " + teamName + " player start — players cannot reach the flag");
        }

        // Check GameModes compatibility: each flag's modes must overlap with at least one start's modes
        for (const flag of teamFlags) {
            const flagModes = flag.gameModes;  // 0 = all modes
            const hasCompatibleStart = teamStarts.some(function(start) {
                const startModes = start.gameModes;  // 0 = all modes
                // Both 0 = compatible with everything
                if (flagModes === 0 || startModes === 0) return true;
                // Otherwise need overlapping bits
                return (flagModes & startModes) !== 0;
            });
            if (!hasCompatibleStart) {
                const flagRoom = roomInfo[flag.roomId];
                const flagLabel = flagRoom ? flagRoom.label : String(flag.roomId).padStart(3, '0');
                warnings.push("WARNING: " + teamName + " flag in Room " + flagLabel +
                    " (Modes=" + formatGameModes(flagModes) + ") has no compatible " + teamName + " player start");
            }
        }
    }

    if (warnings.length > 0) {
        summary.push("--- Warnings ---");
        for (const w of warnings) {
            summary.push(w);
        }
        summary.push("");
    }

    const fullReport = summary.concat(["--- Room Details ---", ""], report);

    // Show dialog
    const dialog = new Dialog("Spawn Point Validation: " + mapName);
    dialog.minimumWidth = 650;
    dialog.newRowMode = Dialog.ManualRows;

    dialog.addHeading("Rooms: " + roomsWithSpawns + " with spawns, " + roomsWithoutSpawns + " without");
    dialog.addNewRow();
    dialog.addHeading("Total spawn points: " + totalSpawns);

    if (warnings.length > 0) {
        dialog.addNewRow();
        dialog.addHeading(warnings.length + " warning(s) found");
    }

    dialog.addNewRow();
    dialog.addSeparator();

    dialog.addNewRow();
    const reportText = dialog.addTextEdit("");
    reportText.plainText = fullReport.join("\n");
    reportText.readOnly = true;

    dialog.addNewRow();
    const saveButton = dialog.addButton("Save Report");
    const closeButton = dialog.addButton("Close");

    saveButton.clicked.connect(function() {
        const reportPath = folder + "/spawn_report.txt";
        try {
            const outFile = new TextFile(reportPath, TextFile.WriteOnly);
            outFile.write(fullReport.join("\n"));
            outFile.close();
            tiled.log("Report saved to: " + reportPath);
            tiled.alert("Report saved to:\n" + reportPath);
        } catch (e) {
            tiled.alert("Failed to save report: " + e);
        }
    });

    closeButton.clicked.connect(function() {
        dialog.accept();
    });

    dialog.show();
}

// =============================================================================
// Game Mode Report
// =============================================================================

// RoomPurpose values (matches jswr_format.py RoomPurpose enum)
const ROOM_PURPOSE_NAMES = {
    0: "Gameplay", 1: "Lobby", 2: "Team Select", 3: "Launchpad",
    4: "Victory Room", 5: "Briefing", 6: "Team Select 4"
};

// Full GameMode names for the report (matches game_settings.py)
const GAME_MODE_FULL_NAMES = {
    0x0001: "COLLECT_X_ITEMS",
    0x0002: "TIMED_GAMES",
    0x0004: "RACE_TO_GAMES",
    0x0008: "DISCOVERY_GAMES",
    0x0010: "GOLDEN_WILLY",
    0x0020: "WILLY_TAG",
    0x0040: "BRITISH_BULLDOG",
    0x0080: "WILLY_TEAMS",
    0x0100: "CAPTURE_THE_FLAG",
    0x0200: "LOBBY",
    0x0400: "FIRST_TO_COLLECT",
    0x0800: "COLLECT_ALL",
    0x1000: "CHAIN_GAMES",
    0x2000: "IT_TAG",
    0x4000: "MM_START",
    0x8000: "WILLY_BALL"
};

// All gameplay mode bits (excludes LOBBY and MM_START infrastructure flags)
const ALL_GAMEPLAY_MODES = 0x0001 | 0x0002 | 0x0004 | 0x0008 | 0x0010 | 0x0020 |
    0x0040 | 0x0080 | 0x0100 | 0x0400 | 0x0800 | 0x1000 | 0x2000 | 0x8000;

/**
 * Parse RoomPurpose from a TMX file using text parsing
 * @param {string} tmxPath - Path to the TMX file
 * @returns {number} - RoomPurpose value (0=Gameplay if not found)
 */
function parseRoomPurpose(tmxPath) {
    try {
        const file = new TextFile(tmxPath, TextFile.ReadOnly);
        const content = file.readAll();
        file.close();

        const match = content.match(/<property\s+name="RoomPurpose"[^>]*value="(\d+)"/);
        if (match) {
            return parseInt(match[1]);
        }
    } catch (e) {
        // Ignore read errors
    }
    return 0; // Default: Gameplay
}

/**
 * Format a bitmask as "NAME1 | NAME2" using full mode names
 */
function formatFullGameModes(modes) {
    if (modes === 0) return "(none)";
    const names = [];
    for (const bit in GAME_MODE_FULL_NAMES) {
        if (modes & parseInt(bit)) {
            names.push(GAME_MODE_FULL_NAMES[bit]);
        }
    }
    return names.length > 0 ? names.join(" | ") : "(none)";
}

/**
 * Generate Game Mode Report for the current map project
 */
function showGameModeReport() {
    let folder = getMapFolder();

    // If no map is open, try to find a loaded world
    if (!folder) {
        const worlds = tiled.worlds;
        if (worlds.length === 0) {
            tiled.alert("Please open a world file (.world) or map first.");
            return;
        }
        folder = getFolderFromWorld(worlds[0]);
    }

    if (!folder) {
        tiled.alert("Could not determine map folder.");
        return;
    }

    const mapName = getMapName(folder);
    const existingIds = getExistingRoomIds(folder);
    const roomInfo = getRoomInfo(folder, existingIds);

    if (existingIds.length === 0) {
        tiled.alert("No rooms found.");
        return;
    }

    // Collect all spawns and room purposes
    const allSpawns = [];  // {kind, team, gameModes, x, y, roomId, roomName}
    const roomPurposes = {};  // roomId -> purpose value

    for (const roomId of existingIds) {
        const tmxPath = folder + "/" + String(roomId).padStart(3, '0') + ".tmx";
        const spawns = parseSpawnPoints(tmxPath);
        const purpose = parseRoomPurpose(tmxPath);
        const info = roomInfo[roomId];
        const roomLabel = info ? info.label : String(roomId).padStart(3, '0');

        roomPurposes[roomId] = purpose;

        for (const spawn of spawns) {
            allSpawns.push({
                kind: spawn.kind,
                team: spawn.team,
                gameModes: spawn.gameModes,
                x: spawn.x,
                y: spawn.y,
                roomId: roomId,
                roomLabel: roomLabel
            });
        }
    }

    // --- Compute ValidGameModes ---

    // Union of game_modes from all spawns
    var spawnModesUnion = 0;
    for (const s of allSpawns) {
        spawnModesUnion |= s.gameModes;
    }

    // Computed game modes = gameplay bits from spawn union
    var computedModes = spawnModesUnion & ALL_GAMEPLAY_MODES;

    // Add LOBBY flag if any room has non-GAMEPLAY RoomPurpose
    var hasNonGameplay = false;
    for (const rid in roomPurposes) {
        if (roomPurposes[rid] !== 0) {
            hasNonGameplay = true;
            break;
        }
    }
    if (hasNonGameplay) {
        computedModes |= 0x0200; // LOBBY
    }

    // Add MM_START if any spawn has it
    if (spawnModesUnion & 0x4000) {
        computedModes |= 0x4000; // MM_START
    }

    // --- Build report ---
    const report = [];
    report.push("=== Game Mode Report for " + mapName + " ===");
    report.push("");
    report.push("Computed ValidGameModes: 0x" + computedModes.toString(16).toUpperCase().padStart(4, '0') +
        " (" + formatFullGameModes(computedModes) + ")");
    report.push("");

    // --- Mode Breakdown ---
    report.push("--- Mode Breakdown ---");

    // Group spawns by contributing mode
    var anyModeShown = false;
    for (const bitStr in GAME_MODE_FULL_NAMES) {
        const bit = parseInt(bitStr);
        if (!(computedModes & bit)) continue;

        const modeName = GAME_MODE_FULL_NAMES[bit];

        // Skip LOBBY and MM_START in spawn breakdown (they're inferred)
        if (bit === 0x0200) {
            report.push(modeName + " (0x" + bit.toString(16).toUpperCase().padStart(4, '0') + "):");
            report.push("  (inferred from non-GAMEPLAY RoomPurpose rooms)");
            // List the rooms
            for (const rid in roomPurposes) {
                if (roomPurposes[rid] !== 0) {
                    const info = roomInfo[rid];
                    const label = info ? info.label : String(rid).padStart(3, '0');
                    const purposeName = ROOM_PURPOSE_NAMES[roomPurposes[rid]] || ("Purpose " + roomPurposes[rid]);
                    report.push("  Room " + label + ": " + purposeName);
                }
            }
            report.push("");
            anyModeShown = true;
            continue;
        }

        if (bit === 0x4000) {
            report.push(modeName + " (0x" + bit.toString(16).toUpperCase().padStart(4, '0') + "):");
            report.push("  (inferred from spawns with MM_START in game_modes)");
            report.push("");
            anyModeShown = true;
            continue;
        }

        // WILLY_TEAMS: check if implied by team-coloured spawns
        if (bit === 0x0080) {
            const hasTeamSpawns = allSpawns.some(function(s) {
                return s.kind === 0 && s.team !== 0 && (s.gameModes & 0x0080);
            });
            report.push(modeName + " (0x" + bit.toString(16).toUpperCase().padStart(4, '0') + "):");
            if (hasTeamSpawns) {
                report.push("  (implied by team-coloured PLAYER_START spawns)");
            }
            // List contributing team spawns
            for (const s of allSpawns) {
                if ((s.gameModes & bit) && s.kind === 0 && s.team !== 0) {
                    const teamName = TEAM_NAMES[s.team] || ("Team " + s.team);
                    report.push("  Room " + s.roomLabel + ": PLAYER_START [" + teamName + "] at (" +
                        Math.round(s.x) + "," + Math.round(s.y) + ")");
                }
            }
            report.push("");
            anyModeShown = true;
            continue;
        }

        // Regular gameplay modes
        const contributors = [];
        for (const s of allSpawns) {
            if (s.gameModes & bit) {
                const kindName = SPAWN_KIND_NAMES[s.kind] || ("Kind " + s.kind);
                const teamName = TEAM_NAMES[s.team] || ("Team " + s.team);
                contributors.push("  Room " + s.roomLabel + ": " + kindName + " [" + teamName + "] at (" +
                    Math.round(s.x) + "," + Math.round(s.y) + ")");
            }
        }

        if (contributors.length > 0) {
            report.push(modeName + " (0x" + bit.toString(16).toUpperCase().padStart(4, '0') + "):");
            for (const line of contributors) {
                report.push(line);
            }
            report.push("");
            anyModeShown = true;
        }
    }

    if (!anyModeShown) {
        report.push("(no gameplay modes detected)");
        report.push("");
    }

    // --- Structural Warnings ---
    const warnings = [];
    const spawns = allSpawns;
    const playerStarts = spawns.filter(function(s) { return s.kind === 0; });
    const flags = spawns.filter(function(s) { return s.kind === 1; });

    // Rule: game_modes=0 on non-EXIT spawns
    for (const s of spawns) {
        if (s.gameModes === 0 && s.kind !== 2) {
            const kindName = SPAWN_KIND_NAMES[s.kind] || ("Kind " + s.kind);
            warnings.push("Room " + s.roomLabel + ": " + kindName + " at (" +
                Math.round(s.x) + "," + Math.round(s.y) + ") has game_modes=0 (must be explicit)");
        }
    }

    // Rule: Neutral spawn must not have WILLY_TEAMS
    for (const s of spawns) {
        if (s.team === 0 && s.kind === 0 && (s.gameModes & 0x0080)) {
            warnings.push("Room " + s.roomLabel + ": Neutral spawn at (" +
                Math.round(s.x) + "," + Math.round(s.y) + ") has WILLY_TEAMS in game_modes");
        }
    }

    // Team symmetry
    const hasRedStart = playerStarts.some(function(s) { return s.team === 1; });
    const hasBlueStart = playerStarts.some(function(s) { return s.team === 2; });
    const hasGreenStart = playerStarts.some(function(s) { return s.team === 4; });
    const hasOrangeStart = playerStarts.some(function(s) { return s.team === 5; });
    const hasNeutralStart = playerStarts.some(function(s) { return s.team === 0; }); // eslint-disable-line no-unused-vars
    const hasRedFlag = flags.some(function(s) { return s.team === 1; }); // eslint-disable-line no-unused-vars
    const hasBlueFlag = flags.some(function(s) { return s.team === 2; }); // eslint-disable-line no-unused-vars
    const hasGreenFlag = flags.some(function(s) { return s.team === 4; }); // eslint-disable-line no-unused-vars
    const hasOrangeFlag = flags.some(function(s) { return s.team === 5; }); // eslint-disable-line no-unused-vars
    // TODO: add validation for neutral spawns and flag symmetry

    if (hasRedStart && !hasBlueStart) warnings.push("Red team spawns exist but no Blue team spawns");
    if (hasBlueStart && !hasRedStart) warnings.push("Blue team spawns exist but no Red team spawns");
    if (hasGreenStart && !hasOrangeStart) warnings.push("Green team spawns exist but no Orange team spawns");
    if (hasOrangeStart && !hasGreenStart) warnings.push("Orange team spawns exist but no Green team spawns");

    // CTF validation
    if (computedModes & 0x0100) {
        if (computedModes & 0x0080) {
            // Team CTF
            var ctfTeamFlags = 0;
            var ctfTeamSpawns = 0;
            for (const s of spawns) {
                if (s.kind === 1 && (s.gameModes & 0x0100) && s.team !== 0) {
                    ctfTeamFlags |= (1 << s.team);
                }
                if (s.kind === 0 && (s.gameModes & 0x0100) && s.team !== 0) {
                    ctfTeamSpawns |= (1 << s.team);
                }
            }
            var paired = ctfTeamFlags & ctfTeamSpawns;
            var teamCount = 0;
            for (var b = 0; b < 8; b++) { if (paired & (1 << b)) teamCount++; }
            if (teamCount < 2) {
                warnings.push("CTF | TEAMS: only " + teamCount + " team(s) have paired CTF-tagged spawn AND flag (need >=2)");
            }
        } else {
            // Solo CTF
            var hasNeutralCtfSpawn = spawns.some(function(s) { return s.kind === 0 && s.team === 0 && (s.gameModes & 0x0100); });
            var hasNeutralCtfFlag = spawns.some(function(s) { return s.kind === 1 && s.team === 0 && (s.gameModes & 0x0100); });
            if (!hasNeutralCtfSpawn) warnings.push("Solo CTF: no CTF-tagged neutral spawn");
            if (!hasNeutralCtfFlag) warnings.push("Solo CTF: no CTF-tagged neutral flag");
        }

        // Per-team CTF pairing
        var teams = [1, 2, 4, 5];
        for (var ti = 0; ti < teams.length; ti++) {
            var t = teams[ti];
            var tName = TEAM_NAMES[t];
            var hasCtfFlag = spawns.some(function(s) { return s.kind === 1 && s.team === t && (s.gameModes & 0x0100); });
            var hasCtfSpawn = spawns.some(function(s) { return s.kind === 0 && s.team === t && (s.gameModes & 0x0100); });
            if (hasCtfFlag && !hasCtfSpawn) warnings.push("CTF-tagged " + tName + " flag but no CTF-tagged " + tName + " spawn");
            if (hasCtfSpawn && !hasCtfFlag) warnings.push("CTF-tagged " + tName + " spawn but no CTF-tagged " + tName + " flag");
        }
    }

    // WILLY_BALL validation
    if (computedModes & 0x8000) {
        if (!(computedModes & 0x0080)) {
            warnings.push("WILLY_BALL present but WILLY_TEAMS missing (WILLY_BALL is always team-based)");
        }
        var hasBallSpawn = spawns.some(function(s) { return s.kind === 3; });
        if (!hasBallSpawn) {
            warnings.push("WILLY_BALL enabled but no BALL_SPAWN found");
        }
        var wbFlags = 0, wbSpawns = 0;
        for (const s of spawns) {
            if (s.gameModes & 0x8000) {
                if (s.kind === 1 && s.team !== 0) wbFlags |= (1 << s.team);
                if (s.kind === 0 && s.team !== 0) wbSpawns |= (1 << s.team);
            }
        }
        var wbPaired = wbFlags & wbSpawns;
        var wbCount = 0;
        for (var wb = 0; wb < 8; wb++) { if (wbPaired & (1 << wb)) wbCount++; }
        if (wbCount < 2) {
            warnings.push("WILLY_BALL: need >=2 teams with WILLY_BALL-tagged spawn AND flag (found " + wbCount + ")");
        }
    }

    // Duplicate non-GAMEPLAY purposes
    var purposeSeen = {};
    for (const rid in roomPurposes) {
        var rp = roomPurposes[rid];
        if (rp !== 0) {
            if (purposeSeen[rp] !== undefined) {
                var pName = ROOM_PURPOSE_NAMES[rp] || ("Purpose " + rp);
                warnings.push("Duplicate " + pName + ": rooms " + purposeSeen[rp] + " and " + rid);
            } else {
                purposeSeen[rp] = rid;
            }
        }
    }

    // Add warnings section
    report.push("--- Warnings ---");
    if (warnings.length === 0) {
        report.push("(none)");
    } else {
        for (const w of warnings) {
            report.push("WARNING: " + w);
        }
    }
    report.push("");

    // Show dialog
    const dialog = new Dialog("Game Mode Report: " + mapName);
    dialog.minimumWidth = 700;
    dialog.newRowMode = Dialog.ManualRows;

    dialog.addHeading("Computed ValidGameModes: 0x" +
        computedModes.toString(16).toUpperCase().padStart(4, '0'));
    dialog.addNewRow();
    dialog.addHeading(formatFullGameModes(computedModes));

    if (warnings.length > 0) {
        dialog.addNewRow();
        dialog.addHeading(warnings.length + " warning(s) found");
    }

    dialog.addNewRow();
    dialog.addSeparator();

    dialog.addNewRow();
    const reportText = dialog.addTextEdit("");
    reportText.plainText = report.join("\n");
    reportText.readOnly = true;

    dialog.addNewRow();
    const saveButton = dialog.addButton("Save Report");
    const closeButton = dialog.addButton("Close");

    saveButton.clicked.connect(function() {
        const reportPath = folder + "/game_mode_report.txt";
        try {
            const outFile = new TextFile(reportPath, TextFile.WriteOnly);
            outFile.write(report.join("\n"));
            outFile.close();
            tiled.log("Report saved to: " + reportPath);
            tiled.alert("Report saved to:\n" + reportPath);
        } catch (e) {
            tiled.alert("Failed to save report: " + e);
        }
    });

    closeButton.clicked.connect(function() {
        dialog.accept();
    });

    dialog.show();
}

// Register the Validate Spawn Points action
const validateSpawnsAction = tiled.registerAction("JSWRValidateSpawns", validateSpawnPoints);
validateSpawnsAction.text = "[WORLD] Validate Spawn Points...";

// Register the Game Mode Report action
const gameModeReportAction = tiled.registerAction("JSWRGameModeReport", showGameModeReport);
gameModeReportAction.text = "[WORLD] Game Mode Report...";

// Register the Fix Orphaned Routes action
const fixRoutesAction = tiled.registerAction("JSWRFixRoutes", fixOrphanedRoutes);
fixRoutesAction.text = "[WORLD] Check/Fix Orphaned Guardian Routes...";

// Register the Fix Room Properties action
const fixRoomPropertiesAction = tiled.registerAction("JSWRFixRoomProperties", fixRoomProperties);
fixRoomPropertiesAction.text = "[ROOM] Check/Fix Room Properties...";

// Register the Fix Guardian/Route Properties action
const fixPropertiesAction = tiled.registerAction("JSWRFixProperties", fixAllGuardianProperties);
fixPropertiesAction.text = "[ROOM] Check/Fix Guardian/Guardian Route Properties...";

// Register the Fix Selected Guardian/Route action (selection-dependent)
var fixSelectedAction = tiled.registerAction("JSWRFixSelected", fixSelectedGuardianProperties);
fixSelectedAction.text = "[SELECTED] Check/Fix Guardian/Guardian Route Properties...";
fixSelectedAction.enabled = false;

// --- jswr-rooms.js ---
/**
 * JSW:R Tiled Extensions — Room Management
 *
 * SOURCE FILE — do not edit the bundled output in .extensions/ directly.
 * Edit this file, then run: python tmx/scripts/tmx_project.py refresh
 *
 * Handles room scanning, world placement, room creation (New Room dialog),
 * and exit-based navigation (Snap to Exit, Go to Exit).
 *
 * Requires: jswr-common.js (bundled before this file alphabetically)
 *
 * Contents:
 *   - Room scanning helpers (getExistingRoomIds, getAvailableIds, getRoomInfo,
 *     extractRoomIdFromLabel)
 *   - World placement (findWorldPlacement, updateWorldFile, getFolderFromWorld)
 *   - New Room dialog and room creation (showNewRoomDialog, createRoom)
 *   - Exit navigation (getExitProperty, findWorldForCurrentMap, getMapRect,
 *     goToExit, snapToExit, isPositionOccupied)
 *   - Dynamic action state management (snapActions, goToActions,
 *     updateSnapActions, updateGoToActions, updateAllActions)
 *   - Action registrations: JSWRNewRoom, JSWRSnap*, JSWRGo*
 *   - Menu extension: Map menu (all items), New menu
 *   - tiled.activeAssetChanged signal connection
 */

/**
 * Scan folder for existing room IDs (001.tmx - 255.tmx)
 */
function getExistingRoomIds(folder) {
    const ids = [];
    for (let i = 1; i <= 255; i++) {
        const filename = folder + "/" + String(i).padStart(3, '0') + ".tmx";
        if (File.exists(filename)) {
            ids.push(i);
        }
    }
    return ids;
}

/**
 * Get all available room IDs (not yet used)
 */
function getAvailableIds(existingIds) {
    const available = [];
    for (let i = 1; i <= 255; i++) {
        if (!existingIds.includes(i)) {
            available.push(i);
        }
    }
    return available;
}

/**
 * Get room info (ID and Name) for existing rooms
 * Uses fast text parsing instead of opening each file in Tiled
 * @param {string} folder - The map folder path
 * @param {number[]} existingIds - Array of existing room IDs
 * @returns {Object} - Map of room ID to {id, name, label}
 */
function getRoomInfo(folder, existingIds) {
    const roomInfo = {};
    for (const id of existingIds) {
        const filename = folder + "/" + String(id).padStart(3, '0') + ".tmx";
        const idStr = String(id).padStart(3, '0');

        // Skip if file doesn't exist
        if (!File.exists(filename)) {
            tiled.warn("Room file not found, skipping: " + filename);
            continue;
        }

        let name = "";

        // Fast: read TMX as text and extract Name property via regex
        try {
            const file = new TextFile(filename, TextFile.ReadOnly);
            const content = file.readAll();
            file.close();

            // Match: <property name="Name" value="..."/>
            const match = content.match(/<property\s+name="Name"\s+value="([^"]*)"/);
            if (match) {
                name = match[1];
            }
        } catch (e) {
            tiled.warn("Failed to read room " + idStr + ": " + e);
            continue;  // Skip rooms that can't be read
        }

        roomInfo[id] = {
            id: id,
            idStr: idStr,
            name: name,
            label: name ? idStr + ": " + name : idStr
        };
    }
    return roomInfo;
}

/**
 * Extract room ID from a label like "001: Room Name" or "001"
 */
function extractRoomIdFromLabel(label) {
    if (!label || label === "(none)") return "(none)";
    // Extract the first 3 digits
    const match = label.match(/^(\d{3})/);
    return match ? match[1] : label;
}

/**
 * Find placement position in world file based on exit connections.
 * If the new room has exits specified, place it adjacent to those rooms.
 *
 * @param {Object} worldData - The world file data
 * @param {Object} exits - The exits {up, down, left, right} as room IDs or "(none)"
 * @returns {Object} - {x, y} position for the new room
 */
function findWorldPlacement(worldData, exits) {
    const maps = worldData.maps || [];
    if (maps.length === 0) {
        return { x: 0, y: 0 };
    }

    // Build map of filename -> position and set of occupied positions
    const roomPositions = {};
    const occupied = new Set();
    let minX = Infinity, minY = Infinity;
    let maxX = -Infinity, maxY = -Infinity;

    for (const map of maps) {
        roomPositions[map.fileName] = { x: map.x, y: map.y };
        occupied.add(`${map.x},${map.y}`);
        minX = Math.min(minX, map.x);
        minY = Math.min(minY, map.y);
        maxX = Math.max(maxX, map.x);
        maxY = Math.max(maxY, map.y);
    }

    // Try to place based on exit connections
    // If new room has Left exit to room X, place new room to the RIGHT of X
    // If new room has Right exit to room X, place new room to the LEFT of X
    // If new room has Up exit to room X, place new room BELOW X
    // If new room has Down exit to room X, place new room ABOVE X
    const exitPlacements = [
        { exit: exits.left, dx: ROOM_WIDTH, dy: 0 },    // Left exit -> place to the right
        { exit: exits.right, dx: -ROOM_WIDTH, dy: 0 },  // Right exit -> place to the left
        { exit: exits.up, dx: 0, dy: ROOM_HEIGHT },     // Up exit -> place below
        { exit: exits.down, dx: 0, dy: -ROOM_HEIGHT }   // Down exit -> place above
    ];

    for (const placement of exitPlacements) {
        if (placement.exit && placement.exit !== "(none)") {
            const targetFile = placement.exit.padStart(3, '0') + ".tmx";
            const targetPos = roomPositions[targetFile];
            if (targetPos) {
                const newX = targetPos.x + placement.dx;
                const newY = targetPos.y + placement.dy;
                if (!occupied.has(`${newX},${newY}`)) {
                    tiled.log("Placing adjacent to room " + targetFile + " at (" + newX + ", " + newY + ")");
                    return { x: newX, y: newY };
                }
            }
        }
    }

    // No valid exit-based placement found, find nearest free spot to center of map
    const centerX = Math.floor((minX + maxX) / 2 / ROOM_WIDTH) * ROOM_WIDTH;
    const centerY = Math.floor((minY + maxY) / 2 / ROOM_HEIGHT) * ROOM_HEIGHT;

    // Spiral outward from center to find free spot
    for (let radius = 0; radius < 50; radius++) {
        for (let dy = -radius; dy <= radius; dy++) {
            for (let dx = -radius; dx <= radius; dx++) {
                if (Math.abs(dx) === radius || Math.abs(dy) === radius) {
                    const x = centerX + dx * ROOM_WIDTH;
                    const y = centerY + dy * ROOM_HEIGHT;
                    if (!occupied.has(`${x},${y}`)) {
                        return { x, y };
                    }
                }
            }
        }
    }

    // Fallback: place to the right of the rightmost room
    return { x: maxX + ROOM_WIDTH, y: minY };
}

/**
 * Update world file with new room
 */
function updateWorldFile(worldPath, roomId, x, y) {
    const file = new TextFile(worldPath, TextFile.ReadOnly);
    const content = file.readAll();
    file.close();

    const worldData = JSON.parse(content);
    worldData.maps.push({
        fileName: String(roomId).padStart(3, '0') + ".tmx",
        x: x,
        y: y
    });

    // Sort by fileName
    worldData.maps.sort((a, b) => a.fileName.localeCompare(b.fileName));

    const outFile = new TextFile(worldPath, TextFile.WriteOnly);
    outFile.write(JSON.stringify(worldData, null, 4));
    outFile.close();
}

/**
 * Get folder from a loaded world file
 */
function getFolderFromWorld(world) {
    if (!world || !world.fileName) return null;
    return FileInfo.path(world.fileName);
}

/**
 * Show the New Room dialog using Tiled's Dialog class with manual row layout
 */
function showNewRoomDialog() {
    let folder = getMapFolder();

    // If no map is open, try to find a loaded world
    if (!folder) {
        const worlds = tiled.worlds;
        if (worlds.length === 0) {
            tiled.alert("Please open a world file (.world) or map first.\n\nTo create a new map, use:\npython tmx/scripts/dat_to_tmx.py --new mapname");
            return;
        } else if (worlds.length === 1) {
            // Only one world loaded - use it
            folder = getFolderFromWorld(worlds[0]);
        } else {
            // Multiple worlds loaded - need to let user choose
            // For now, use the first one and log the others
            folder = getFolderFromWorld(worlds[0]);
            tiled.log("Multiple worlds loaded, using: " + worlds[0].fileName);
        }
    }

    if (!folder) {
        tiled.alert("Could not determine map folder.");
        return;
    }

    if (!File.exists(folder)) {
        tiled.alert("Folder does not exist: " + folder);
        return;
    }

    const mapName = getMapName(folder);
    const existingIds = getExistingRoomIds(folder);
    const availableIds = getAvailableIds(existingIds);

    if (availableIds.length === 0) {
        tiled.alert("Map is full! All 255 room slots are in use.");
        return;
    }

    const roomInfo = getRoomInfo(folder, existingIds);
    const exitLabels = existingIds.map(id => roomInfo[id] ? roomInfo[id].label : String(id).padStart(3, '0'));
    const exitOptions = ["(none)"].concat(exitLabels);
    const roomIdOptions = availableIds.map(id => String(id).padStart(3, '0'));

    // Build dialog using Tiled's Dialog class with manual row control
    const dialog = new Dialog("Create room for " + mapName);
    dialog.newRowMode = Dialog.ManualRows;
    dialog.minimumWidth = 500;

    // Apply stylesheet for better spacing
    dialog.styleSheet = `
        QComboBox { min-width: 200px; }
        QLineEdit { min-width: 200px; }
    `;

    // Room ID
    dialog.addHeading("Room ID:");
    const roomIdCombo = dialog.addComboBox("", roomIdOptions);

    // Room Name
    dialog.addNewRow();
    dialog.addHeading("Room Name:");
    const roomNameEdit = dialog.addTextInput("");

    // Exits section
    dialog.addNewRow();
    dialog.addSeparator();

    // Row 1: Up exit (centered conceptually via label)
    dialog.addNewRow();
    dialog.addHeading("          ↑ Up:");
    const upExitCombo = dialog.addComboBox("", exitOptions);

    // Row 2: Left exit
    dialog.addNewRow();
    dialog.addHeading("          ← Left:");
    const leftExitCombo = dialog.addComboBox("", exitOptions);

    // Row 3: Right exit
    dialog.addNewRow();
    dialog.addHeading("          → Right:");
    const rightExitCombo = dialog.addComboBox("", exitOptions);

    // Row 4: Down exit (centered conceptually via label)
    dialog.addNewRow();
    dialog.addHeading("          ↓ Down:");
    const downExitCombo = dialog.addComboBox("", exitOptions);

    // Rope checkbox
    dialog.addNewRow();
    dialog.addSeparator();
    dialog.addNewRow();
    const ropeCheckBox = dialog.addCheckBox("Has Rope", false);

    // Buttons
    dialog.addNewRow();
    const cancelButton = dialog.addButton("Cancel");
    const okButton = dialog.addButton("OK");

    okButton.clicked.connect(function() {
        const roomId = parseInt(roomIdCombo.currentText);
        const roomName = roomNameEdit.text.substring(0, 32);
        const exits = {
            up: extractRoomIdFromLabel(upExitCombo.currentText),
            down: extractRoomIdFromLabel(downExitCombo.currentText),
            left: extractRoomIdFromLabel(leftExitCombo.currentText),
            right: extractRoomIdFromLabel(rightExitCombo.currentText)
        };
        const hasRope = ropeCheckBox.checked;

        dialog.accept();
        createRoom(folder, mapName, roomId, roomName, exits, hasRope);
    });

    cancelButton.clicked.connect(function() {
        dialog.reject();
    });

    dialog.show();
}

/**
 * Create a new room with the given parameters
 */
function createRoom(folder, mapName, roomId, roomName, exits, hasRope) {
    const tmxPath = folder + "/" + String(roomId).padStart(3, '0') + ".tmx";
    tiled.log("Creating room at: " + tmxPath);

    const newMap = new TileMap();
    newMap.setSize(32, 16);
    newMap.setTileSize(8, 8);
    newMap.orientation = TileMap.Orthogonal;
    newMap.renderOrder = TileMap.RightDown;
    newMap.layerDataFormat = TileMap.CSV;
    newMap.backgroundColor = "#040204";

    newMap.setProperty("Down", exits.down === "(none)" ? "" : exits.down + ".tmx");
    newMap.setProperty("Flags", tiled.propertyValue("RoomFlags", ""));
    newMap.setProperty("Left", exits.left === "(none)" ? "" : exits.left + ".tmx");
    newMap.setProperty("Name", roomName);
    newMap.setProperty("Right", exits.right === "(none)" ? "" : exits.right + ".tmx");
    newMap.setProperty("Rope", hasRope);
    newMap.setProperty("Rope Offset", 0);
    newMap.setProperty("Up", exits.up === "(none)" ? "" : exits.up + ".tmx");
    newMap.setProperty("WillySuit", tiled.propertyValue("WillySuit", "Normal"));

    // Tilesets are in tmx/tilesets/ (sibling to content/_in_progress folders)
    const contentFolder = FileInfo.path(folder);  // e.g., tmx/content or tmx/_in_progress
    const tmxFolder = FileInfo.path(contentFolder);  // tmx/
    const tilesetsFolder = tmxFolder + "/tilesets";

    const tilesetFiles = [
        "tiles_solid.tsx",
        "tiles_stairs.tsx",
        "tiles_platform.tsx",
        "tiles_hazard.tsx",
        "tiles_decoration.tsx",
        "tiles_conveyor.tsx",
        "collectibles.tsx",
        "guardians.tsx",
        "tiles_collapsible.tsx"
    ];
    let mainTileset = null;
    for (const tsName of tilesetFiles) {
        const tsPath = tilesetsFolder + "/" + tsName;
        if (File.exists(tsPath)) {
            const tileset = tiled.open(tsPath);
            if (tileset && tileset.isTileset) {
                newMap.addTileset(tileset);
                if (tsName === "tiles_solid.tsx") {
                    mainTileset = tileset;
                }
            }
        }
    }

    const tileLayer = new TileLayer("Tiles");
    tileLayer.width = 32;
    tileLayer.height = 16;
    newMap.addLayer(tileLayer);

    if (mainTileset) {
        const tile1 = mainTileset.tile(0);
        if (tile1) {
            const edit = tileLayer.edit();
            for (let y = 0; y < 16; y++) {
                for (let x = 0; x < 32; x++) {
                    edit.setTile(x, y, tile1);
                }
            }
            edit.apply();
        }
    }

    newMap.addLayer(new ObjectGroup("Collectables"));
    newMap.addLayer(new ObjectGroup("Enemies"));

    const routesLayer = new ObjectGroup("Routes");
    routesLayer.color = "#ff00ffff";
    newMap.addLayer(routesLayer);

    newMap.addLayer(new ObjectGroup("Spawn"));

    const format = tiled.mapFormat("tmx");
    if (!format) {
        tiled.alert("TMX format not available!");
        return;
    }

    const error = format.write(newMap, tmxPath);
    if (error) {
        tiled.alert("Failed to write map: " + error);
        return;
    }

    // Add to world
    const worldPath = folder + "/" + mapName + ".world";
    let world = null;
    for (const w of tiled.worlds) {
        if (w.fileName === worldPath) {
            world = w;
            break;
        }
    }

    if (world) {
        try {
            const worldFile = new TextFile(worldPath, TextFile.ReadOnly);
            const worldContent = worldFile.readAll();
            worldFile.close();

            const worldData = JSON.parse(worldContent);
            const pos = findWorldPlacement(worldData, exits);
            world.addMap(tmxPath, Qt.rect(pos.x, pos.y, ROOM_WIDTH, ROOM_HEIGHT));
            tiled.log("Added room at (" + pos.x + ", " + pos.y + ")");
        } catch (e) {
            tiled.warn("Failed to add to world: " + e);
        }
    } else if (File.exists(worldPath)) {
        tiled.warn("World file not loaded in Tiled - writing directly to disk. Open the .world file to use the API instead.");
        try {
            const worldFile = new TextFile(worldPath, TextFile.ReadOnly);
            const worldContent = worldFile.readAll();
            worldFile.close();

            const worldData = JSON.parse(worldContent);
            const pos = findWorldPlacement(worldData, exits);
            updateWorldFile(worldPath, roomId, pos.x, pos.y);
        } catch (e) {
            tiled.warn("Failed to update world file: " + e);
        }
    }

    if (File.exists(tmxPath)) {
        tiled.open(tmxPath);
    }
}

/**
 * Get the exit property from current map (returns room ID without .tmx, or null)
 */
function getExitProperty(direction) {
    const map = tiled.activeAsset;
    if (!map || !map.isTileMap) return null;

    const exitValue = map.property(direction);
    if (!exitValue || exitValue === "") return null;

    // Convert to string (property may return URL object for file types)
    const exitStr = String(exitValue);
    if (exitStr === "" || exitStr === "undefined") return null;

    // Extract just the filename and remove .tmx extension
    const fileName = FileInfo.fileName(exitStr);
    return fileName.replace(/\.tmx$/, "");
}

/**
 * Find loaded world for current map
 */
function findWorldForCurrentMap() {
    const map = tiled.activeAsset;
    if (!map || !map.fileName) return null;

    const folder = FileInfo.path(map.fileName);
    const mapName = getMapName(folder);
    const worldPath = folder + "/" + mapName + ".world";

    for (const w of tiled.worlds) {
        if (w.fileName === worldPath) {
            return w;
        }
    }
    return null;
}

/**
 * Get a map's rect from the world (World doesn't have a getter, so search allMaps)
 */
function getMapRect(world, targetFileName) {
    const allMaps = world.allMaps();
    const targetName = FileInfo.fileName(targetFileName);
    for (const entry of allMaps) {
        if (entry.fileName === targetName || FileInfo.fileName(entry.fileName) === targetName) {
            return entry.rect;
        }
    }
    return null;
}

/**
 * Open the room connected via the specified exit direction
 * @param {string} direction - "Up", "Down", "Left", or "Right"
 */
function goToExit(direction) {
    const map = tiled.activeAsset;
    if (!map || !map.isTileMap || !map.fileName) {
        tiled.alert("Please open a map file first.");
        return;
    }

    const exitRoomId = getExitProperty(direction);
    if (!exitRoomId) {
        tiled.alert("No " + direction + " exit defined for this room.");
        return;
    }

    const folder = FileInfo.path(map.fileName);
    const targetFile = folder + "/" + exitRoomId.padStart(3, '0') + ".tmx";

    if (!File.exists(targetFile)) {
        tiled.alert("Target room file not found: " + targetFile);
        return;
    }

    tiled.open(targetFile);

    // Fit the new map in view (Cmd+/ / Ctrl+/)
    tiled.trigger("FitInView");
}

/**
 * Snap current room to align with its exit in the specified direction
 * @param {string} direction - "Up", "Down", "Left", or "Right"
 */
function snapToExit(direction) {
    const map = tiled.activeAsset;
    if (!map || !map.isTileMap || !map.fileName) {
        tiled.alert("Please open a map file first.");
        return;
    }

    const exitRoomId = getExitProperty(direction);
    if (!exitRoomId) {
        tiled.alert("No " + direction + " exit defined for this room.");
        return;
    }

    const world = findWorldForCurrentMap();
    if (!world) {
        tiled.alert("World file not loaded. Open the .world file first.");
        return;
    }

    const folder = FileInfo.path(map.fileName);
    const targetFile = folder + "/" + exitRoomId.padStart(3, '0') + ".tmx";

    // Check if target room exists in world
    if (!world.containsMap(targetFile)) {
        tiled.alert("Target room " + exitRoomId + " is not in the world.");
        return;
    }

    // Get target room's position
    const targetRect = getMapRect(world, targetFile);
    if (!targetRect) {
        tiled.alert("Could not get position of room " + exitRoomId);
        return;
    }

    // Calculate new position based on direction
    // If this room's Up exit goes to X, we should be BELOW X
    // If this room's Down exit goes to X, we should be ABOVE X
    // If this room's Left exit goes to X, we should be RIGHT of X
    // If this room's Right exit goes to X, we should be LEFT of X
    let newX, newY;
    switch (direction) {
        case "Up":
            newX = targetRect.x;
            newY = targetRect.y + ROOM_HEIGHT;  // Below target
            break;
        case "Down":
            newX = targetRect.x;
            newY = targetRect.y - ROOM_HEIGHT;  // Above target
            break;
        case "Left":
            newX = targetRect.x + ROOM_WIDTH;   // Right of target
            newY = targetRect.y;
            break;
        case "Right":
            newX = targetRect.x - ROOM_WIDTH;   // Left of target
            newY = targetRect.y;
            break;
    }

    // Move the map in the world
    world.setMapRect(map.fileName, Qt.rect(newX, newY, ROOM_WIDTH, ROOM_HEIGHT));
    tiled.log("Snapped room to (" + newX + ", " + newY + ") based on " + direction + " exit to " + exitRoomId);

    // Update menu items to reflect new position
    updateSnapActions();
}

// Store references to actions for updating
const snapActions = {};
const goToActions = {};

/**
 * Check if a position in the world is occupied by any room
 */
function isPositionOccupied(world, x, y, excludeFile) {
    // Get all maps in a rect at this position
    const checkRect = Qt.rect(x, y, ROOM_WIDTH - 1, ROOM_HEIGHT - 1);
    const mapsAtPos = world.mapsInRect(checkRect);

    // Filter out the current map (we're moving it, so it doesn't count)
    for (const mapEntry of mapsAtPos) {
        if (mapEntry.fileName !== excludeFile) {
            return true;
        }
    }
    return false;
}

/**
 * Update snap action states based on current map's exits
 */
function updateSnapActions() {
    const directions = ["Up", "Down", "Left", "Right"];
    const arrows = { "Up": "↑", "Down": "↓", "Left": "←", "Right": "→" };

    const map = tiled.activeAsset;
    const world = (map && map.isTileMap) ? findWorldForCurrentMap() : null;

    let anyEnabled = false;

    for (const dir of directions) {
        const action = snapActions[dir];
        if (!action) continue;

        const exitRoomId = getExitProperty(dir);
        if (!exitRoomId) {
            action.enabled = false;
            action.text = "Snap " + arrows[dir] + " (no exit)";
            continue;
        }

        // Check if we can actually snap (world loaded and target exists)
        if (!world || !map || !map.fileName) {
            action.enabled = false;
            action.text = "Snap " + arrows[dir] + " to " + exitRoomId;
            continue;
        }

        const folder = FileInfo.path(map.fileName);
        const targetFile = folder + "/" + exitRoomId.padStart(3, '0') + ".tmx";

        if (!world.containsMap(targetFile)) {
            action.enabled = false;
            action.text = "Snap " + arrows[dir] + " to " + exitRoomId + " (not in world)";
            continue;
        }

        // Get target room's position and calculate where we'd move to
        const targetRect = getMapRect(world, targetFile);
        if (!targetRect) {
            action.enabled = false;
            action.text = "Snap " + arrows[dir] + " to " + exitRoomId;
            continue;
        }

        let newX, newY;
        switch (dir) {
            case "Up":
                newX = targetRect.x;
                newY = targetRect.y + ROOM_HEIGHT;
                break;
            case "Down":
                newX = targetRect.x;
                newY = targetRect.y - ROOM_HEIGHT;
                break;
            case "Left":
                newX = targetRect.x + ROOM_WIDTH;
                newY = targetRect.y;
                break;
            case "Right":
                newX = targetRect.x - ROOM_WIDTH;
                newY = targetRect.y;
                break;
        }

        // Get current room's position
        const currentRect = getMapRect(world, map.fileName);
        const alreadySnapped = currentRect && currentRect.x === newX && currentRect.y === newY;

        // Check if already at correct position or target position is occupied
        if (alreadySnapped) {
            action.enabled = false;
            action.text = "Snap " + arrows[dir] + " to " + exitRoomId + " (aligned)";
        } else if (isPositionOccupied(world, newX, newY, map.fileName)) {
            action.enabled = false;
            action.text = "Snap " + arrows[dir] + " to " + exitRoomId + " (occupied)";
        } else {
            action.enabled = true;
            action.text = "Snap " + arrows[dir] + " to " + exitRoomId;
            anyEnabled = true;
        }
    }

    // Hide all snap actions if none are available
    for (const dir of directions) {
        const action = snapActions[dir];
        if (action) {
            action.visible = anyEnabled;
        }
    }
}

/**
 * Update go-to action states based on current map's exits
 */
function updateGoToActions() {
    const directions = ["Up", "Down", "Left", "Right"];
    const arrows = { "Up": "↑", "Down": "↓", "Left": "←", "Right": "→" };

    const map = tiled.activeAsset;
    let anyVisible = false; // eslint-disable-line no-unused-vars

    for (const dir of directions) {
        const action = goToActions[dir];
        if (!action) continue;

        const exitRoomId = getExitProperty(dir);
        if (!exitRoomId) {
            action.enabled = false;
            action.visible = false;
            action.text = "Go " + arrows[dir];
            continue;
        }

        // Check if target file exists
        if (map && map.fileName) {
            const folder = FileInfo.path(map.fileName);
            const targetFile = folder + "/" + exitRoomId.padStart(3, '0') + ".tmx";

            if (File.exists(targetFile)) {
                action.enabled = true;
                action.visible = true;
                action.text = "Go " + arrows[dir] + " to " + exitRoomId;
                anyVisible = true;
            } else {
                action.enabled = false;
                action.visible = true;
                action.text = "Go " + arrows[dir] + " to " + exitRoomId + " (missing)";
                anyVisible = true;
            }
        } else {
            action.enabled = false;
            action.visible = false;
            action.text = "Go " + arrows[dir] + " to " + exitRoomId;
        }
    }

}

/**
 * Update all dynamic menu actions
 */
function updateAllActions() {
    updateSnapActions();
    updateGoToActions();
}

// Register the New Room action
const newRoomAction = tiled.registerAction("JSWRNewRoom", showNewRoomDialog);
newRoomAction.text = "New JSW:R Room...";
newRoomAction.shortcut = "Ctrl+Shift+N";

// Register Snap actions (start hidden until a valid room is selected)
// Shortcut: Ctrl+Arrow (Command+Arrow on Mac)
snapActions["Up"] = tiled.registerAction("JSWRSnapUp", function() { snapToExit("Up"); });
snapActions["Up"].text = "Snap ↑ (no exit)";
snapActions["Up"].shortcut = "Shift+Up";
snapActions["Up"].enabled = false;
snapActions["Up"].visible = false;

snapActions["Down"] = tiled.registerAction("JSWRSnapDown", function() { snapToExit("Down"); });
snapActions["Down"].text = "Snap ↓ (no exit)";
snapActions["Down"].shortcut = "Shift+Down";
snapActions["Down"].enabled = false;
snapActions["Down"].visible = false;

snapActions["Left"] = tiled.registerAction("JSWRSnapLeft", function() { snapToExit("Left"); });
snapActions["Left"].text = "Snap ← (no exit)";
snapActions["Left"].shortcut = "Shift+Left";
snapActions["Left"].enabled = false;
snapActions["Left"].visible = false;

snapActions["Right"] = tiled.registerAction("JSWRSnapRight", function() { snapToExit("Right"); });
snapActions["Right"].text = "Snap → (no exit)";
snapActions["Right"].shortcut = "Shift+Right";
snapActions["Right"].enabled = false;
snapActions["Right"].visible = false;

// Register Go to actions (start hidden until a valid room is selected)
// Shortcut: Shift+Arrow
goToActions["Up"] = tiled.registerAction("JSWRGoUp", function() { goToExit("Up"); });
goToActions["Up"].text = "Go ↑";
goToActions["Up"].shortcut = "Ctrl+Up";
goToActions["Up"].enabled = false;
goToActions["Up"].visible = false;

goToActions["Down"] = tiled.registerAction("JSWRGoDown", function() { goToExit("Down"); });
goToActions["Down"].text = "Go ↓";
goToActions["Down"].shortcut = "Ctrl+Down";
goToActions["Down"].enabled = false;
goToActions["Down"].visible = false;

goToActions["Left"] = tiled.registerAction("JSWRGoLeft", function() { goToExit("Left"); });
goToActions["Left"].text = "Go ←";
goToActions["Left"].shortcut = "Ctrl+Left";
goToActions["Left"].enabled = false;
goToActions["Left"].visible = false;

goToActions["Right"] = tiled.registerAction("JSWRGoRight", function() { goToExit("Right"); });
goToActions["Right"].text = "Go →";
goToActions["Right"].shortcut = "Ctrl+Right";
goToActions["Right"].enabled = false;
goToActions["Right"].visible = false;

// Update all actions when active asset changes
tiled.activeAssetChanged.connect(function() {
    updateAllActions();
    connectSelectionSignal();
});

// Initial update (in case a map is already open when extension loads)
updateAllActions();
connectSelectionSignal();

// Add menu items to Map and New menus
tiled.extendMenu("Map", [
    { separator: true, before: "MapProperties" },
    { action: "JSWRNewRoom", before: "MapProperties" },
    { separator: true, before: "MapProperties" },
    { action: "JSWRValidateSpawns", before: "MapProperties" },
    { action: "JSWRGameModeReport", before: "MapProperties" },
    { action: "JSWRFixRoutes", before: "MapProperties" },
    { action: "JSWRFixSelected", before: "MapProperties" },
    { separator: true, before: "MapProperties" },
    { action: "JSWRFixRoomProperties", before: "MapProperties" },
    { action: "JSWRFixProperties", before: "MapProperties" },
    { separator: true, before: "MapProperties" },
    { action: "JSWRSnapUp", before: "MapProperties" },
    { action: "JSWRSnapDown", before: "MapProperties" },
    { action: "JSWRSnapLeft", before: "MapProperties" },
    { action: "JSWRSnapRight", before: "MapProperties" },
    { separator: true, before: "MapProperties" },
    { action: "JSWRGoUp", before: "MapProperties" },
    { action: "JSWRGoDown", before: "MapProperties" },
    { action: "JSWRGoLeft", before: "MapProperties" },
    { action: "JSWRGoRight", before: "MapProperties" },
    { separator: true, before: "MapProperties" },
]);
tiled.extendMenu("New", [
    { separator: true },
    { action: "JSWRNewRoom" }
]);

// --- jswr-triggers.js ---
/**
 * JSW:R Tiled Extensions — Trigger Property Helper
 *
 * SOURCE FILE — do not edit the bundled output in .extensions/ directly.
 * Edit this file, then run: python tmx/scripts/tmx_project.py refresh
 *
 * Adds items to the Map menu that stamp the correct TriggerType, Action,
 * and any type-specific extra properties onto selected objects in a Special
 * layer.  Menu items are enabled only when valid objects are selected.
 *
 * Self-contained — no dependencies on other jswr-*.js source files.
 */

// =========================================================================
// Trigger Property Helper
// =========================================================================

/**
 * Extra properties to add for specific TriggerType values.
 * TriggerType and Action are always added. These define additional
 * properties needed for each condition type.
 */
const TRIGGER_EXTRA_PROPERTIES = {
    ScoreThreshold:      { Threshold: 0 },
    ScorePctThreshold:   { Threshold: 50 },
    ItemCollectedInRoom: { Threshold: 1 },
    RoomEntered:         { Threshold: 0 },
    ExternalEvent:       { Name: "" },
};

/**
 * Default Action value for each TriggerType.
 * If not listed, defaults to "Complete".
 */
const TRIGGER_DEFAULT_ACTIONS = {
    CollisionWith: "TeleportPlayerTo",
};

/**
 * Read the TriggerType enum values from the project's custom property types.
 * Falls back to a hardcoded list if the project API is unavailable.
 * @returns {string[]} Array of TriggerType value names
 */
function getTriggerTypeValues() {
    if (tiled.project && tiled.project.findTypeByName) {
        const enumType = tiled.project.findTypeByName("TriggerType");
        if (enumType && enumType.isEnum && enumType.values && enumType.values.length > 0) {
            return enumType.values;
        }
    }
    // Fallback for Tiled < 1.12 or missing project type
    return [
        "GameStart", "ScoreThreshold", "ScorePctThreshold",
        "RoomAllCollected", "ItemCollectedInRoom", "CollisionWith",
        "RoomEntered", "ExternalEvent", "Never"
    ];
}

/**
 * Check whether any selected object is on a Special layer.
 * @param {TileMap} map
 * @returns {boolean}
 */
function hasSpecialLayerSelection(map) {
    if (!map || !map.selectedObjects || map.selectedObjects.length === 0) {
        return false;
    }
    var selected = map.selectedObjects;
    for (var i = 0; i < selected.length; i++) {
        var obj = selected[i];
        // Walk up to find the containing layer
        var layer = obj.layer;
        if (layer && layer.name && layer.name.indexOf("Special") === 0) {
            return true;
        }
    }
    return false;
}

/**
 * Apply trigger properties to the selected object(s).
 * Sets TriggerType and Action, plus any extra properties for that type.
 * Only adds properties that are missing — does not overwrite existing values.
 */
function applyTriggerTemplate(triggerTypeName) {
    var map = tiled.activeAsset;
    if (!map || !map.selectedObjects || map.selectedObjects.length === 0) {
        return;
    }

    var defaultAction = TRIGGER_DEFAULT_ACTIONS[triggerTypeName] || "Complete";
    var extras = TRIGGER_EXTRA_PROPERTIES[triggerTypeName] || {};

    var objects = map.selectedObjects;
    var count = 0;

    for (var i = 0; i < objects.length; i++) {
        var obj = objects[i];
        var added = 0;

        // Always set TriggerType and Action (if missing)
        if (obj.property("TriggerType") === undefined) {
            obj.setProperty("TriggerType", tiled.propertyValue("TriggerType", triggerTypeName));
            added++;
        }
        if (obj.property("Action") === undefined) {
            obj.setProperty("Action", tiled.propertyValue("Action", defaultAction));
            added++;
        }

        // Add extra properties for this trigger type
        for (var propName in extras) {
            if (obj.property(propName) === undefined) {
                obj.setProperty(propName, extras[propName]);
                added++;
            }
        }

        if (added > 0) count++;
    }

    tiled.log("Trigger: applied " + triggerTypeName + " to " + count + " object(s)");
}

// =========================================================================
// Action registration
// =========================================================================

var triggerTypeValues = getTriggerTypeValues();
var triggerActionObjects = [];  // Store action refs for enable/disable

for (var i = 0; i < triggerTypeValues.length; i++) {
    (function(name) {
        var actionId = "JSWRTrigger_" + name;
        var action = tiled.registerAction(actionId, function() {
            applyTriggerTemplate(name);
        });
        action.text = "[TRIGGER] " + name;
        action.enabled = false;
        triggerActionObjects.push(action);
    })(triggerTypeValues[i]);
}

/**
 * Enable/disable trigger menu items based on current selection.
 * Items are enabled only when objects on a Special layer are selected.
 */
function updateTriggerActions() {
    var map = tiled.activeAsset;
    var enabled = map && map.isTileMap && hasSpecialLayerSelection(map);
    for (var i = 0; i < triggerActionObjects.length; i++) {
        triggerActionObjects[i].enabled = enabled;
    }
}

// Connect to selection changes
var triggerMapConnection = null;

function connectTriggerSelectionSignal() {
    if (triggerMapConnection) {
        triggerMapConnection.disconnect();
        triggerMapConnection = null;
    }
    var map = tiled.activeAsset;
    if (map && map.isTileMap) {
        triggerMapConnection = map.selectedObjectsChanged.connect(updateTriggerActions);
    }
    updateTriggerActions();
}

tiled.activeAssetChanged.connect(function() {
    connectTriggerSelectionSignal();
});
connectTriggerSelectionSignal();

// =========================================================================
// Menu registration
// =========================================================================

var triggerMenuEntries = [
    { separator: true, before: "MapProperties" },
];
for (var i = 0; i < triggerTypeValues.length; i++) {
    triggerMenuEntries.push({ action: "JSWRTrigger_" + triggerTypeValues[i], before: "MapProperties" });
}
tiled.extendMenu("Map", triggerMenuEntries);
