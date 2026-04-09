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
