/// <reference types="@mapeditor/tiled-api" />

/**
 * JSW:R Tiled Extensions — Trigger Property Helper
 *
 * Adds items to the Map menu that stamp the
 * correct TriggerType, Action, and any type-specific extra properties onto
 * selected objects in a Special layer.
 *
 * Depends on jswr-common.js (loaded alphabetically before this file).
 *
 * Contents:
 *   - TRIGGER_EXTRA_PROPERTIES — per-TriggerType additional property defaults
 *   - TRIGGER_DEFAULT_ACTIONS  — per-TriggerType default Action values
 *   - getTriggerTypeValues()   — reads TriggerType enum from project or falls
 *                                 back to a hardcoded list
 *   - applyTriggerTemplate()   — stamps properties onto selected objects
 *   - Registration of JSWRTrigger_* actions (one per TriggerType value)
 *   - Trigger submenu registration under Map menu
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
 * Apply trigger properties to the selected object(s).
 * Sets TriggerType and Action, plus any extra properties for that type.
 * Only adds properties that are missing — does not overwrite existing values.
 */
function applyTriggerTemplate(triggerTypeName) {
    const map = tiled.activeAsset;
    if (!map || !map.selectedObjects || map.selectedObjects.length === 0) {
        tiled.alert("Select one or more objects in a Special layer first.");
        return;
    }

    const defaultAction = TRIGGER_DEFAULT_ACTIONS[triggerTypeName] || "Complete";
    const extras = TRIGGER_EXTRA_PROPERTIES[triggerTypeName] || {};

    const objects = map.selectedObjects;
    let count = 0;

    for (let i = 0; i < objects.length; i++) {
        const obj = objects[i];
        let added = 0;

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
        for (const propName in extras) {
            if (obj.property(propName) === undefined) {
                obj.setProperty(propName, extras[propName]);
                added++;
            }
        }

        if (added > 0) count++;
    }

    tiled.log("Trigger: applied " + triggerTypeName + " to " + count + " object(s)");
}

// Register an action for each TriggerType (read from project or fallback)
const triggerTypeValues = getTriggerTypeValues();
const triggerActions = {};
for (let i = 0; i < triggerTypeValues.length; i++) {
    (function(name) {
        const actionId = "JSWRTrigger_" + name;
        const action = tiled.registerAction(actionId, function() {
            applyTriggerTemplate(name);
        });
        action.text = name;
        triggerActions[name] = actionId;
    })(triggerTypeValues[i]);
}

// Add trigger actions to Map menu as flat items (Tiled does not support nested submenus)
var triggerMenuEntries = [
    { separator: true, before: "MapProperties" },
];
for (let i = 0; i < triggerTypeValues.length; i++) {
    triggerMenuEntries.push({ action: triggerActions[triggerTypeValues[i]], before: "MapProperties" });
}
tiled.extendMenu("Map", triggerMenuEntries);
