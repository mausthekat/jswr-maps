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
