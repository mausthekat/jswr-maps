# Map Triggers

Map triggers are data-driven events defined in TMX Special layers.  Each trigger has a
**condition** (when it fires) and an **action** (what it does).  Triggers can be chained
via dependencies to create multi-step sequences.

Triggers are one-shot by default: they fire once, execute their action, and complete.
Two authorable re-arm properties make a trigger repeatable - `RearmTicks` (return to
pending N ticks after completing) and `RearmOnRoomExit` (return to pending when the
player leaves the trigger's room); `TeleportRoomBeam` re-arms implicitly after its
beam sequence so the teleporter pad is reusable (see [Actions](#actions) and
[Re-arm](#re-arm-repeatable-triggers)).  Reactive
elements like team doors and barriers remain separate (see [Special Objects](#special-objects-team-doorsbarriers)
at the end of this document).

---

## Quick Start

1. Open the map's `.tiled-project` in Tiled.
2. Add objects to a `Special` layer.
3. Set `TriggerType` and `Action` on each object.
4. Optionally chain triggers with `Name` and `DependsOnCompletion`.
5. Build the pack - the converter validates and embeds trigger data.

---

## Property Reference

Every trigger object in the Special layer uses these properties:

| Property | Tiled Type | Required | Description |
|----------|-----------|----------|-------------|
| `TriggerType` | `TriggerType` enum | **Yes** | The condition that activates this trigger. See [Trigger Types](#trigger-types). |
| `Action` | `Action` enum | **Yes** | The effect when the trigger fires. See [Actions](#actions). |
| `Name` | string | Optional | A unique name for this trigger. Required if other triggers reference it via `DependsOnCompletion`. Must be unique across all rooms in the map. |
| `DependsOnCompletion` | string | Optional | The `Name` of a prerequisite trigger. This trigger's condition is not evaluated until the prerequisite completes. Multiple triggers can depend on the same prerequisite. Cross-room references are supported. |
| `Target` | object ref or string | Per action | What the action applies to. Object references point to guardians or spawn points. Strings are used for filenames (`DoReplay`), sound names (`PlaySound`), and destination tile coords (`TeleportRoom`, `"tx,ty"`). See each action for details. |
| `Threshold` | int | Per trigger/action | Numeric parameter. Meaning depends on context: item count for `ScoreThreshold`, percentage for `ScorePctThreshold`, room ID for `RoomEntered` and `TeleportRoom`, seconds for `Delay`, item count for `ItemCollectedInRoom`. |
| `GameModes` | `GameModes` enum (flags) | Optional | Restrict to specific game modes. If absent or 0, fires in all modes. |
| `SessionType` | `SessionType` enum (flags) | Optional | Restrict to single player (1), multiplayer (2), or both (3). If absent or 0, fires in all session types. |
| `Visibility` | `Visibility` enum | Optional | Who sees the effect: `AllPlayers` (default) or `TriggeringPlayer`. |
| `TriggerMode` | `TriggerMode` enum | Optional | Whether multiple players can trigger independently: `Unique` (default) or `PerPlayer`. |
| `RearmTicks` | int | Optional | Re-arm timer: the trigger returns to pending N physics ticks after completing, so it can fire again. 0/absent = one-shot. (`TeleportRoomBeam` has an implicit 150-tick default.) See [Re-arm](#re-arm-repeatable-triggers). |
| `RearmOnRoomExit` | bool | Optional | Re-arms the trigger when the player leaves the trigger's room, and when the room is reset (single-player death respawn re-runs the set piece). Ignored by the headless server. Pair it with a room-gated condition (e.g. a whole-room `CollisionWith` zone) so the re-armed trigger cannot refire while the player is elsewhere. |

### Object Geometry

The trigger object's position and size in Tiled are significant:

- **Position (x, y):** For `CollisionWith` (self), defines the top-left corner of the
  collision zone. For `ShowTile`/`ShowEntity`/`ReplaceGuardian`, defines where the
  graphic is placed.
- **Size (width, height):** For `CollisionWith` (self), defines the collision zone
  dimensions.
- **Tile (GID):** For `ShowTile`, `ShowEntity`, and `ReplaceGuardian`, the Tiled tile
  graphic is embedded in the pack as PNG data and rendered at runtime.

---

## Trigger Types

Each trigger object has exactly one `TriggerType`.  The trigger activates when its
condition becomes true.  If `DependsOnCompletion` is also set, the condition is only
evaluated after the dependency has completed (AND logic).

| TriggerType | Parameters | Fires when... |
|-------------|------------|---------------|
| `GameStart` | - | Immediately when the game begins (or when its dependency completes). |
| `ScoreThreshold` | `Threshold` (int) | Player has collected >= N items globally. |
| `ScorePctThreshold` | `Threshold` (int, percentage 0–100) | Player has collected >= N% of the map's total items. |
| `RoomAllCollected` | - | All collectible items in this trigger's room have been picked up. |
| `ItemCollectedInRoom` | `Threshold` (int) | N or more items in this trigger's room have been collected. |
| `CollisionWith` | - | Player's bounding box overlaps this object's rectangle in the same room. |
| `RoomEntered` | `Threshold` (int, room ID) | Player enters the specified room. |
| `ExternalEvent` | - | Never fires from condition evaluation. Only fired explicitly by game code (e.g., MM exit FLAG_CAPTURED handler). Used as an entry point for trigger chains driven by game events. |
| `Never` | - | Never fires. Reserved for future use. |

### Filters

Filters restrict when a trigger can fire.  If a filter doesn't match, the trigger
stays pending regardless of its condition.

| Filter | Values | Default |
|--------|--------|---------|
| `GameModes` | Bitmask of game modes | 0 (all modes) |
| `SessionType` | 1=SP, 2=MP, 3=both | 0 (all) |

### Visibility and TriggerMode (Multiplayer)

These properties control multiplayer behavior:

| Property | Values | Default | Effect |
|----------|--------|---------|--------|
| `Visibility` | `AllPlayers`, `TriggeringPlayer` | `AllPlayers` | `AllPlayers`: server broadcasts TRIGGER_FIRED to all clients. `TriggeringPlayer`: server sends only to the player who caused the trigger. |
| `TriggerMode` | `Unique`, `PerPlayer` | `Unique` | `Unique`: one-shot, first player triggers it, done forever. `PerPlayer`: each player can trigger independently. |

These are orthogonal - all four combinations are valid:

| Mode | Visibility | Example |
|------|-----------|---------|
| Unique + AllPlayers | Everyone sees | Default. One player triggers, all clients apply. |
| Unique + TriggeringPlayer | Private one-shot | Swordfish graphic: first player to complete sees it, others don't. |
| PerPlayer + AllPlayers | Everyone sees each | Each player can collect a key; when they do, everyone sees a message. |
| PerPlayer + TriggeringPlayer | Private per-player | Each player triggers independently, only they see their own effect. |

### DependsOnCompletion

Any trigger can depend on another trigger by setting `DependsOnCompletion` to the
other trigger's `Name`.  The dependency must complete before this trigger's condition
is evaluated.

All three conditions must be satisfied before the action fires:

1. The `DependsOnCompletion` prerequisite has completed.
2. All filters (`GameModes`, `SessionType`) match the current game state.
3. The primary `TriggerType` condition is true.

Dependencies can span rooms.  The converter validates the graph is acyclic at build time.

---

## Actions

Each trigger object has exactly one `Action`.  The action executes when the trigger fires.

### Instant Actions

These complete immediately.

| Action | Parameters | Effect |
|--------|------------|--------|
| `Complete` | - | No visible effect. Immediately marks this trigger as complete. Useful as a dependency gate. |
| `HideGuardian` | `Target` (object ref to guardian) | Hides the guardian. It stops rendering and is no longer collidable. |
| `ShowGuardian` | `Target` (object ref to guardian) | Un-hides a previously hidden guardian. |
| `ReplaceGuardian` | `Target` (object ref to guardian) | Replaces the guardian's sprite with this object's tile graphic (GID). |
| `ShowTile` | - | Places this object's tile graphic at its position as a tile overlay. |
| `HideTile` | - | Restores the original tile at this object's position, removing a `ShowTile` overlay. |
| `ShowEntity` | - | Shows this object's tile graphic as a sprite overlay at its position. Used for celebration graphics (e.g., swordfish). The object must have a GID (tile reference). |
| `HideEntity` | `Target` (optional, object ref to guardian) | Without Target: hides MM exit entities in this trigger's room (used during celebrations so the ShowEntity graphic is visible). With Target: hides the referenced guardian (same effect as `HideGuardian`). |
| `TeleportPlayerTo` | `Target` (object ref to spawn point) | Moves the player to the target object's position. Clears all movement keys. |
| `RemovePlayer` | - | Hides the player sprite. Physics continue but the sprite is not rendered. |
| `DisablePlayerInput` | - | Suppresses movement keys (left, right, jump). Chat and menu keys still work. |
| `EnablePlayerInput` | - | Re-enables movement keys. Reverses `DisablePlayerInput`. |
| `EndGame` | - | Ends the game. SP: returns to title screen. MP: server declares the winner (player_id propagated through the trigger dependency chain) and transitions to the victory room. |
| `PlaySound` | `Target` (string, sound name) | Plays a built-in sound effect: `pickup`, `death`, `arrow`, `tick`, or `mm_air`. Room-gated: only players currently in this trigger's room hear it. Never replayed to late joiners. Unknown names are silent (build warning). On the Spectrum Next only `pickup`/`death`/`arrow` exist; `tick`/`mm_air` are PC-only (build warning). |
| `TeleportRoom` | `Threshold` (int, dest room id), `Target` (string, `"tx,ty"`) | Teleports the player to a DIFFERENT room. `Threshold` is the destination room id; `Target` is the destination in TILE coordinates (`tx` 0-31, `ty` 0-15) - note this differs from `TeleportPlayerTo`, which works in pixels. Grants the standard 1.5s post-teleport immunity, and updates the death-respawn point to the destination. Player-specific in MP: only the player who caused the trigger teleports; never applied to late joiners. Spectrum Next: destination room ids must be 1-255 (build warning otherwise). |
| `TeleportRoomBeam` | `Threshold` (int, dest room id), `Target` (string, `"tx,ty"`) | JSW2-style delayed teleport with dematerialize/materialize effects. Same fields as `TeleportRoom`, but instead of an instant switch the world freezes for 150 physics ticks: 75 ticks of dematerialize effect in the source room, room switch, 75 ticks of materialize at the destination (input dead and the player invulnerable throughout - the ROM handler hijacks the whole frame). RE-ARMABLE by default: the trigger returns to pending 150 ticks after firing so the pad can be reused (JSW2 teleporters are two-way navigation pairs). Player-specific in MP (recommended authoring: `Visibility = TriggeringPlayer`); never applied to late joiners. |
| `ScrollRegion` | region + scroll properties (see [ScrollRegion](#scrollregion-jsw2-region-scroll-set-piece)) | JSW2 region-scroll set piece (the yacht sail and the Deserted Isle sink). A cell-aligned region of the room's tile grid shifts by `CellsPerTick` cells each tick with empty infill while the world is frozen (the teleport-beam freeze), optionally preceded by a forced auto-walk phase (`ForceWalk`/`WalkTicks`) and optionally followed by a chained room teleport (`DestRoom`/`DestTile`). Room reset (re-entry) restores the authored tiles. Player-specific in MP; never applied to late joiners. Spectrum Next: unported - the JSWN build transcodes it to `Complete` (state-only) with a warning, so dependents still unblock. |

### Duration Actions

These take time to complete.  Downstream dependencies wait until the action finishes.

| Action | Parameters | Effect |
|--------|------------|--------|
| `Delay` | `Threshold` (int, seconds) | Does nothing for N seconds, then completes. |
| `DoReplay` | `Target` (string, filename) | Plays a replay file from the map's `replay/` subdirectory. Movement keys are disabled during playback. Completes when the replay finishes. |

---

## Examples

### Every TriggerType

#### GameStart - Multiplayer-only platform overlays

Extra platforms that appear only in multiplayer sessions.

```
TriggerType  = GameStart
Action       = ShowTile
SessionType  = 2          (MP only)
```

No `Name` or `DependsOnCompletion` needed - standalone immediate trigger.

#### ScoreThreshold - Hide guardian after collecting N items

Hide Maria when the player has collected 82 items.

```
TriggerType  = ScoreThreshold
Threshold    = 82
Action       = HideGuardian
Target       = (object ref to Maria guardian)
Name         = "score_gate"
SessionType  = 1          (SP only)
```

#### ScorePctThreshold - Show graphic at 50% completion

Show a congratulations tile when the player has collected half the items.

```
TriggerType  = ScorePctThreshold
Threshold    = 50
Action       = ShowTile
```

Note: `Threshold` is a percentage (0–100) when used with `ScorePctThreshold`.

#### RoomAllCollected - Gate on room completion

Mark a room's items as fully collected.

```
TriggerType  = RoomAllCollected
Action       = Complete
Name         = "room_clear"
```

#### ItemCollectedInRoom - Gate on partial room collection

Fire after collecting 3 items in this room.

```
TriggerType  = ItemCollectedInRoom
Threshold    = 3
Action       = ShowGuardian
Target       = (object ref to guardian)
```

#### CollisionWith - Player walks into a zone

Trigger a replay when the player walks onto the bed (using this object's rectangle):

```
TriggerType          = CollisionWith
DependsOnCompletion  = "score_gate"
Action               = DoReplay
Target               = "rec69bf-4e2e.jsr"
Name                 = "replay"
```

Or use another object's rectangle as the collision zone:

```
TriggerType          = CollisionWith
Target               = (object ref to zone object)
Action               = TeleportPlayerTo
```

If `Target` is an object reference, the referenced object's bounds define the collision
zone.  Otherwise, this object's own rectangle is used.  Player must be in the same room.

#### RoomEntered - Trigger on entering a room

Fire when the player enters room 5.

```
TriggerType  = RoomEntered
Threshold    = 5
Action       = HideGuardian
Target       = (object ref to guardian)
```

#### ExternalEvent - Fired by game code

Used as an entry point for trigger chains driven by game events.  The MM exit handler
fires this when the player reaches the final exit.

```
TriggerType  = ExternalEvent
Action       = Complete
Name         = "items_done"
```

This trigger never fires from the engine's condition evaluation - it is only fired
by `fire_trigger_by_id("items_done")` from game code.

#### Never - Placeholder

Reserved.  Never fires automatically.

```
TriggerType  = Never
Action       = Complete
```

### Every Action

#### Complete - Dependency gate

```
TriggerType  = ScoreThreshold
Threshold    = 10
Action       = Complete
Name         = "ten_items"
```

Other triggers can use `DependsOnCompletion = "ten_items"` to fire after this.

#### HideGuardian / ShowGuardian - Toggle guardian visibility

```
TriggerType  = ScoreThreshold
Threshold    = 50
Action       = HideGuardian
Target       = (object ref to guardian)
Name         = "hidden"

TriggerType          = ScoreThreshold
Threshold            = 80
DependsOnCompletion  = "hidden"
Action               = ShowGuardian
Target               = (same guardian ref)
```

#### ReplaceGuardian - Swap guardian sprite

The trigger object must be a tile object (have a GID).  The tile graphic replaces the
guardian's sprite.

```
TriggerType          = GameStart
DependsOnCompletion  = "replay"
Action               = ReplaceGuardian
Target               = (object ref to guardian)
Name                 = "replaced"
```

#### ShowTile / HideTile - Tile overlays

The trigger object must be a tile object (have a GID) for ShowTile.

```
TriggerType  = GameStart
Action       = ShowTile
SessionType  = 2
```

#### ShowEntity - Sprite overlay (e.g., swordfish)

The trigger object must be a tile object (have a GID).  The tile graphic renders as a
sprite at the object's position.

```
TriggerType          = GameStart
DependsOnCompletion  = "celebration"
Action               = ShowEntity
Name                 = "swordfish"
Visibility           = TriggeringPlayer
```

#### HideEntity - Hide entities

Without Target - hides MM exit sprites so the ShowEntity graphic is visible:

```
TriggerType          = GameStart
DependsOnCompletion  = "celebration"
Action               = HideEntity
Visibility           = TriggeringPlayer
```

With Target - hides a specific guardian:

```
TriggerType          = ScoreThreshold
Threshold            = 50
Action               = HideEntity
Target               = (object ref to guardian)
```

#### TeleportPlayerTo - Move player to a position

The `Target` must be an object reference to a spawn point or any object with a position.

```
TriggerType          = CollisionWith
DependsOnCompletion  = "items_done"
Action               = TeleportPlayerTo
Target               = (object ref to spawn point)
Name                 = "celebration"
```

#### TeleportRoom - Move player to a DIFFERENT room

`Threshold` is the destination room id; `Target` is a literal `"tx,ty"` string
in TILE coordinates (0-31, 0-15) - unlike `TeleportPlayerTo`, which is
pixel-based and same-room only. Object refs cannot cross rooms in Tiled, so
the destination is always written literally. The player gets the standard
1.5-second post-teleport immunity, and dying afterwards respawns them at the
destination (it becomes the room-entry point).

A "cartography room" (one teleport pad per destination):

```
TriggerType  = CollisionWith          # pad zone 1
Action       = TeleportRoom
Threshold    = 12                     # room 12: The Beach
Target       = "4,13"                 # arrive at tile (4,13)
Visibility   = TriggeringPlayer
TriggerMode  = PerPlayer              # every player can use the pad

TriggerType  = CollisionWith          # pad zone 2
Action       = TeleportRoom
Threshold    = 47                     # room 47: The Moon
Target       = "16,8"
Visibility   = TriggeringPlayer
TriggerMode  = PerPlayer
```

#### TeleportRoomBeam - JSW2 teleporter pad

Same `Threshold`/`Target` convention as `TeleportRoom`, but with the JSW2
transporter sequence: standing on the pad freezes the world, dissolves Willy
over 75 ticks (sparkling static + YELLOW/WHITE ink alternation in original
graphics styles; flicker -> contract -> beam in enhanced), switches rooms, and
re-materializes him over 75 more. A transporter buzz plays throughout. The
pad re-arms 150 ticks after firing, so teleporters can be authored as
two-way pairs. The trigger rect should be the CELL Willy stands on (the JSW2
ROM matches WILLYX to cell precision at a standing head-y).

```
TriggerType  = CollisionWith          # the pad cell (8x8)
Action       = TeleportRoomBeam
Threshold    = 121                    # destination room id
Target       = "3,1"                  # arrive at tile (3,1)
Visibility   = TriggeringPlayer
```

The four JSW2 map teleporters are authored by
`analysis/jsw2zx/add_jsw2_teleporters.py` and verified by
`analysis/jsw2zx/probe_teleporters.py`.  The Deserted Isle pad is an SP/MP
pair: the SP pad `DependsOnCompletion = "isle_sink"` (dead until the island
collapse completes, matching the JSW2 ROM), plus an always-active
`SessionType = 2` twin for multiplayer.

#### ScrollRegion - JSW2 region-scroll set piece

Recreates the JSW2 back-buffer region scrolls (the yacht voyage and the
Deserted Isle sink, `analysis/jsw2zx/YACHT_CHAIN_MECHANICS.md`): a
cell-aligned region of the room's tile grid shifts each tick with empty
infill while the world is frozen via the teleport-beam freeze (input dead,
guardians paused, player invulnerable).  Runtime: `src/scroll_region.py` +
the `GameInstance` scroll-region machine.

Scroll parameters live either on the trigger object itself (its own rect =
the region) or - when the trigger's own rect is a `CollisionWith` zone - on
a separate plain rect object referenced via `Target` (object ref):

| Property | Type | Default | Meaning |
|----------|------|---------|---------|
| `Direction` | `Direction` enum | required | Which way the region content moves (`Left`/`Right`/`Up`/`Down`); empty cells fill in from the opposite edge. |
| `CellsPerTick` | int | 1 | Cells shifted per physics tick (0 = freeze only, no shifting). |
| `DurationTicks` | int | required | Length of the shift phase, in physics ticks. |
| `ForceWalk` | `Direction` enum | none | Optional forced auto-walk (`Left`/`Right` only) BEFORE the shift phase: the player physics run with that key held (immune) while the rest of the world stays frozen - the ROM isle sink's forced LEFT walk. |
| `WalkTicks` | int | 0 | Length of the forced-walk phase. |
| `DestRoom` | int | 0 (none) | Optional chained teleport when the sequence ends (the ROM yacht warps to the isle) - same semantics as `TeleportRoom`. |
| `DestTile` | string | - | `"tx,ty"` TILE destination for `DestRoom`. |

Rects must be cell-aligned (8px).  The shifted tiles persist for the rest of
the room visit; leaving/re-entering the room restores the authored grid (the
same reset hook collapsible tiles and moving floors use).  The pack encodes
everything as `Threshold` = `DurationTicks` plus an 11-field CSV in `target`
(`"cx,cy,cw,ch,dir,cpt,walk_ticks,walk_dir,dest_room,dtx,dty"`, cell
coordinates - `src/scroll_region.ScrollRegionSpec.parse`).

```
(rect object, id 954)                  # the region
Direction     = Left
CellsPerTick  = 1
DurationTicks = 150
DestRoom      = 81
DestTile      = "10,10"

TriggerType  = CollisionWith           # the deck spot (8x8 cell)
Action       = ScrollRegion
Target       = (object ref to 954)
RearmTicks   = 150                     # re-fires on a later revisit
SessionType  = 1                       # SP set piece
```

### Re-arm (repeatable triggers)

A completed trigger normally stays complete forever.  Two orthogonal
properties (generalized from the `TeleportRoomBeam` pad re-arm,
`src/triggers/engine.py:tick_rearm` / `rearm_ticks_for`) return it to
pending:

- **`RearmTicks`** - a countdown armed at completion time; the trigger
  re-arms exactly N ticks later.  `TeleportRoomBeam` defaults to 150 (its
  beam length) with no authoring; an authored value overrides.  Suited to
  triggers whose condition needs a fresh player action (e.g. a
  `CollisionWith` pad/spot that must be re-touched).
- **`RearmOnRoomExit`** - re-arms when the player leaves the trigger's
  room, AND whenever the room itself is reset - which in single-player
  includes dying and respawning in the room (`GameInstance.reset_room` ->
  `TriggerEngine.rearm_room`).  So a set piece re-runs both on re-entry
  and on death, matching the ROM (die on the JSW2 isle and the room
  resets and the collapse countdown restarts).  A completed OR in-flight
  (`Delay` part-elapsed) set-piece trigger is returned to a clean pending
  on reset, so the timer restarts from the top rather than resuming.
  Single-player only (the server has no player-room context).  The
  trigger's own condition must be false outside the room (use `CollisionWith`
  - a whole-room rect works as "player is in this room") or the re-armed
  trigger would refire remotely.

  Dependents re-gate themselves: `_should_fire` re-reads a dependency's
  live state, so a trigger with `DependsOnCompletion` on a re-armed
  set-piece (the isle teleport pad depends on `isle_sink`) goes inert
  again the instant its dependency re-arms - no explicit reset needed.

Beware level-triggered conditions: a trigger whose condition stays true
(`GameStart`, a satisfied `RoomAllCollected`) refires IMMEDIATELY after
re-arming.  The JSW2 isle chain pairs `RearmOnRoomExit` with whole-room
`CollisionWith` zones for exactly this reason.

#### PlaySound - Play a built-in sound

```
TriggerType  = CollisionWith
Action       = PlaySound
Target       = "pickup"               # pickup / death / arrow / tick / mm_air
```

Only players in the trigger's room hear it, and it is never replayed to a
late joiner. Chain it with `Delay` + `TeleportRoom` for vehicle set-pieces
(board -> sound -> delay -> arrive).

#### RemovePlayer - Hide player sprite

```
TriggerType          = GameStart
DependsOnCompletion  = "replay"
Action               = RemovePlayer
```

#### DisablePlayerInput / EnablePlayerInput

```
TriggerType  = ScoreThreshold
Threshold    = 10
Action       = DisablePlayerInput
Name         = "frozen"

TriggerType          = GameStart
DependsOnCompletion  = "frozen"
Action               = Delay
Threshold            = 3
Name                 = "pause"

TriggerType          = GameStart
DependsOnCompletion  = "pause"
Action               = EnablePlayerInput
```

#### EndGame - End the game

```
TriggerType          = GameStart
DependsOnCompletion  = "wait"
Action               = EndGame
```

In multiplayer, the winner's player_id is propagated through the trigger dependency
chain from the original event (e.g., FLAG_CAPTURED).

#### Delay - Timed pause

```
TriggerType          = GameStart
DependsOnCompletion  = "celebration"
Action               = Delay
Threshold            = 10
Name                 = "wait"
```

`Threshold` is in seconds.  The delay starts when the trigger fires (after all
dependencies are satisfied).

#### DoReplay - Play a replay file

```
TriggerType          = CollisionWith
DependsOnCompletion  = "score_gate"
Action               = DoReplay
Target               = "rec69bf-4e2e.jsr"
Name                 = "replay"
```

The replay file must exist in `replay/` within the map's TMX folder.  Movement keys
are disabled during playback.

---

## Worked Examples

### Manic Miner - Final Celebration (manic/020.tmx)

When the player reaches the MM exit in the final room, a celebration sequence plays:
teleport to a position, show the swordfish graphic, hide the exit, wait 10 seconds,
end the game.

```
Room 20 (The Final Barrier):

  items_done:
    TriggerType  = ExternalEvent       ← Fired by MM exit game code
    Action       = Complete
    Name         = "items_done"

  celebration:
    TriggerType          = CollisionWith    ← Player must be in the exit zone
    DependsOnCompletion  = "items_done"
    Action               = TeleportPlayerTo
    Target               = (spawn point at celebration position)
    Name                 = "celebration"

  swordfish:
    TriggerType          = GameStart        ← Fires immediately when celebration completes
    DependsOnCompletion  = "celebration"
    Action               = ShowEntity       ← Tile object with swordfish GID
    Name                 = "swordfish"
    Visibility           = TriggeringPlayer ← Only winning player sees it

  hide_exit:
    TriggerType          = GameStart
    DependsOnCompletion  = "celebration"
    Action               = HideEntity       ← Hides MM exit so swordfish is visible
    Visibility           = TriggeringPlayer

  wait:
    TriggerType          = GameStart
    DependsOnCompletion  = "celebration"
    Action               = Delay
    Threshold            = 10               ← 10 seconds
    Name                 = "wait"

  end:
    TriggerType          = GameStart
    DependsOnCompletion  = "wait"
    Action               = EndGame
```

**Multiplayer flow:** The server fires `items_done` and `celebration` explicitly when
it receives the FLAG_CAPTURED event (the CollisionWith can't be evaluated server-side).
The trigger chain then drives everything: teleport, celebration effects, timing, and
game end.  The winner's player_id propagates through the chain for Visibility targeting
and winner declaration.

### Jet Set Willy - Endgame Sequence (jsw-gorgeous/034.tmx + 032.tmx)

When the player collects enough items, Maria disappears.  The player walks to the bed,
triggering a replay.  After the replay, the player vanishes and the toilet guardian is
replaced.

```
Room 34 (Master Bedroom):

  score_gate:
    TriggerType  = ScoreThreshold
    Threshold    = 82
    Action       = HideGuardian
    Target       = (Maria guardian)
    Name         = "score_gate"
    SessionType  = 1                   ← SP only

  replay:
    TriggerType          = CollisionWith    ← Player walks to the bed
    DependsOnCompletion  = "score_gate"
    Action               = DoReplay
    Target               = "rec69bf-4e2e.jsr"
    Name                 = "replay"
    SessionType          = 1

Room 32 (The Bathroom):

  remove:
    TriggerType          = GameStart
    DependsOnCompletion  = "replay"         ← Cross-room dependency
    Action               = RemovePlayer
    SessionType          = 1

  replace:
    TriggerType          = GameStart
    DependsOnCompletion  = "replay"
    Action               = ReplaceGuardian
    Target               = (toilet guardian)
    Name                 = "replaced"
    SessionType          = 1

  wait:
    TriggerType          = GameStart
    DependsOnCompletion  = "replaced"
    Action               = Delay
    Threshold            = 10
    Name                 = "wait"
    SessionType          = 1

  end:
    TriggerType          = GameStart
    DependsOnCompletion  = "wait"
    Action               = EndGame
    SessionType          = 1
```

### Multiplayer-Only Obstacles (manic/003.tmx, 007.tmx, 017.tmx)

Extra platform tiles that only appear in multiplayer sessions.

```
  (tile object with platform GID, one per position):
    TriggerType  = GameStart
    Action       = ShowTile
    SessionType  = 2                   ← MP only
```

No `Name` or `DependsOnCompletion` - standalone immediate triggers.

### JSW2 - Trip Switch / Yacht / Deserted Isle chain (jsw2 map)

The ROM-verified chain (`analysis/jsw2zx/YACHT_CHAIN_MECHANICS.md`),
authored by `analysis/jsw2zx/add_jsw2_yacht_chain.py` +
`analysis/jsw2zx/add_jsw2_teleporters.py` and verified by
`analysis/jsw2zx/probe_yacht_chain.py`.  All SessionType = 1 (SP).

```
Room 072 (Trip Switch):
  trip_switch:        CollisionWith (16,8) 16x8    ← Willy's head touches
                      Action = PlaySound "tick"      the lever cell (1,3)
  trip_switch_tile:   GameStart, dep trip_switch
                      Action = ShowTile (gid 10501)← lever art flips

Room 056 (The Bow):
  bow_clear:          RoomAllCollected, dep trip_switch, Action = Complete

Room 057 (The Yacht):
  yacht_clear:        RoomAllCollected, dep bow_clear, Action = Complete
  yacht_sail:         CollisionWith (64,96) 8x8    ← the exact deck spot
                      dep yacht_clear
                      Action = ScrollRegion        ← band rows 5-14 cols
                      RearmTicks = 150               0-20 scrolls LEFT for
                                                     150 ticks, then warp
                                                     to 081 tile (10,10)

Room 081 (Deserted Isle):
  isle_clear:         RoomAllCollected, Action = Complete
  isle_countdown:     CollisionWith (whole room), dep isle_clear
                      Action = Delay 56s, RearmOnRoomExit
  isle_sink:          CollisionWith (whole room), dep isle_countdown
                      Action = ScrollRegion, RearmOnRoomExit
                      (39-tick forced LEFT walk, then the island band
                       rows 3-11 cols 9-20 sinks DOWN for 85 ticks)
  teleporter_081:     CollisionWith pad, dep isle_sink ← dead until the
                      Action = TeleportRoomBeam         collapse completes
  teleporter_081_mp:  same pad, SessionType = 2, no dep (MP twin)
```

The chain is order-independent (state conditions re-evaluate while
pending): the switch and the two items can be done in any order; the deck
spot is the final gate.  `RearmOnRoomExit` on countdown + sink makes a
re-entry rerun the whole collapse with the pad dead again, matching the
ROM's per-visit scratch state.

---

## Replay Files

Replay files (`.jsr`) used by `DoReplay` are stored in `replay/` within the map's TMX
folder:

```
tmx/content/jsw-gorgeous/
  ├── 032.tmx
  ├── 034.tmx
  └── replay/
      └── rec69bf-4e2e.jsr
```

At build time, the converter embeds the replay file contents in the pack.

During replay playback:
- Movement keys are disabled; chat/menu keys remain active.
- Room transitions within the replay are handled by the replay engine.
- The action completes when the replay finishes.
- Trigger-driven replays cannot be interrupted (unlike chat-command replays).

---

## Trigger Lifecycle

Each trigger progresses through three states:

```
PENDING  ──→  ACTIVE  ──→  COMPLETE
```

- **Pending:** Waiting for conditions - dependencies, filters, and the primary condition.
- **Active:** Action is executing.  Only duration actions (`Delay`, `DoReplay`) use this
  state.  Instant actions skip directly from Pending to Complete.
- **Complete:** Action finished.  Downstream `DependsOnCompletion` triggers can now fire.

The engine evaluates all pending triggers every physics tick (20 Hz).  Triggers are
evaluated in deterministic order: sorted by room_id, then by object order within the room.

---

## Multiplayer Networking

In multiplayer, the **server is authoritative** over trigger state.

### Protocol

| Packet | Code | Direction | Format | Purpose |
|--------|------|-----------|--------|---------|
| `TRIGGER_REQ` | 0x59 | C→H | `player_id(1) + trigger_index(1)` | Client requests trigger activation |
| `TRIGGER_FIRED` | 0x5A | H→All | `trigger_index(1) + player_id(1)` | Server confirms trigger fired |
| `TRIGGER_SYNC` | 0x5B | H→C | `count(1) + bitset(N)` | Late-join snapshot of all fired triggers |

Triggers are identified by **index** (position in the deterministic flattened list),
not by `Name` string.

### Authority Model

**Single player:** Client runs `TriggerEngine` locally.  No networking.

**Multiplayer:**

1. **Server evaluates** non-collision conditions (ScoreThreshold, GameStart, etc.)
   authoritatively via its own `TriggerEngine` in server mode.
2. **Client detects** CollisionWith triggers locally and sends `TRIGGER_REQ`.
3. **Server arbitrates** simultaneous requests: earliest tick wins; ties broken by
   `tick % len(candidates)`.
4. **Server broadcasts** `TRIGGER_FIRED` to all clients (or targeted send for
   `Visibility=TriggeringPlayer`).
5. **Clients apply** the action:
   - World actions (HideGuardian, ShowTile, EndGame, etc.): all clients execute.
     `PlaySound` is world-state but room-gated (only clients in the trigger's
     room play it).
   - Player-specific actions (TeleportPlayerTo, TeleportRoom, DisablePlayerInput,
     EnablePlayerInput, RemovePlayer): only the targeted player executes.
6. **Late joiners** receive `TRIGGER_SYNC` with a bitset of all completed triggers.
   World effects are re-applied EXCEPT player-specific actions and `PlaySound`
   (stale sounds are not replayed on join).

### EndGame in Multiplayer

When the trigger chain reaches `EndGame`, the server detects `is_game_ending()` and
declares the winner.  The winner's player_id is propagated through the trigger
dependency chain - no separate tracking is needed.

### DoReplay in Multiplayer

Replay playback is client-local.  The server runs a fixed-duration timer as a fallback
(30 seconds).  Other players see the replaying player's movement via normal UDP position
sync.

---

## Special Objects (Team Doors/Barriers)

Team doors and team barriers are **reactive** - they toggle dynamically and are NOT
part of the trigger system.

| TMX Property | Effect |
|-------------|--------|
| `Team` (int) | **Team Door:** tile overlay shown when team is NOT active. |
| `RequiredTeam` (int) | **Team Barrier:** tile overlay shown when team is unavailable or below `MinPlayerCount`. |
| `MinPlayerCount` (int) | Minimum players for a `RequiredTeam` barrier to open. |

These objects do NOT have `TriggerType` or `Action` properties.

---

## Build-Time Processing

The converter identifies trigger objects by the presence of a `TriggerType` property.
For each trigger object, the converter:

1. Extracts all trigger properties (`TriggerType`, `Action`, `Name`, etc.).
2. Resolves object references (`Target type="object"`) to guardian indices or positions.
3. For tile objects: extracts the tile image as PNG bytes (payload).
4. For `DoReplay`: reads the replay file from `replay/<Target>` and embeds it.
5. Validates the dependency graph is acyclic and all references resolve.
6. Serializes into `custom_data["trigger_objects"]` in the JSWP pack.

### Build Warnings

- Unknown `TriggerType` or `Action` values.
- `DependsOnCompletion` referencing a non-existent `Name`.
- Circular dependency chains.
- `DoReplay` with a missing replay file.
- Unresolvable `Target` object references.
- `TeleportRoom` whose `Threshold` room id does not exist in the map, or whose
  `Target` is not a valid `"tx,ty"` tile coordinate (0-31, 0-15). The JSWN
  (Spectrum Next) build additionally warns when the destination room id is
  outside 1-255 (unreachable on the Next).
- `PlaySound` whose `Target` is not a built-in sound name
  (`pickup`/`death`/`arrow`/`tick`/`mm_air`); the JSWN build additionally warns
  for `tick`/`mm_air` (PC-only, silent on the Next).
- `ScrollRegion` whose region is not cell-aligned or falls outside the 32x16
  grid, whose direction/walk fields are invalid, whose total duration
  (`DurationTicks` + `WalkTicks`) is zero, whose `DestRoom` does not exist in
  the map, or whose `Target` object reference cannot be resolved. The JSWN
  build additionally warns that `ScrollRegion` transcodes to `Complete`
  (unported on the Next).

---

## Adding New Types

1. Add the value to the `TriggerType` or `Action` enum in
   `tmx/project-template/archetype.tiled-project`.
2. Run `python tmx/scripts/tmx_project.py refresh` to propagate.
3. For a new **TriggerType**: add a condition in `engine._condition_met()`.
4. For a new **Action**: add a handler and register in `_ACTION_DISPATCH`
   (and `_DURATION_DISPATCH` if it has duration).
5. Update this document.

---

## Code References

| File | Purpose |
|------|---------|
| `build_scripts/tmx/tmx_to_jsw.py` | TMX parsing, validation, serialization |
| `src/triggers/engine.py` | `TriggerEngine` - evaluation, dispatch, state tracking |
| `src/triggers/types.py` | Enums, `TriggerDef`, `TriggerRuntime`, `TriggerInstance` |
| `src/triggers/context.py` | `TriggerContext` protocol + `GameInstanceContext` adapter |
| `src/triggers/actions.py` | Standalone action functions |
| `src/scroll_region.py` | `ScrollRegionSpec`/`ScrollRegionFx` - ScrollRegion grid math + restore |
| `src/server/trigger_service.py` | Server-authoritative engine + arbitration + broadcast |
| `src/network/protocol.py` | TRIGGER_REQ/FIRED/SYNC packet format |
| `src/map_registry.py` | Pack deserialization |
| `src/game_instance.py` | Client integration (SP engine tick, MP collision zones) |
| `src/rendering/entity_renderer.py` | Trigger graphic rendering |
| `tests/test_trigger_engine.py` | 74 unit tests |
| `tests/test_mp_trigger_celebration.py` | 19 MP trigger tests |
| `tests/test_teleport_beam.py` | TeleportRoomBeam machine/effects/re-arm tests |
| `tests/test_yacht_chain.py` | ScrollRegion + generalized re-arm + JSW2 chain tests |
