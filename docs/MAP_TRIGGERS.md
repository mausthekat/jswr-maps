# Map Triggers

Map triggers are data-driven events defined in TMX Special layers.  Each trigger has a
**condition** (when it fires) and an **action** (what it does).  Triggers can be chained
via dependencies to create multi-step sequences.

Triggers are one-shot: they fire once, execute their action, and complete.  Reactive
elements like team doors and barriers remain separate (see [Special Objects](#special-objects-team-doorsbarriers)
at the end of this document).

---

## Quick Start

1. Open the map's `.tiled-project` in Tiled.
2. Add objects to a `Special` layer.
3. Set `TriggerType` and `Action` on each object.
4. Optionally chain triggers with `Name` and `DependsOnCompletion`.
5. Build the pack — the converter validates and embeds trigger data.

---

## Property Reference

Every trigger object in the Special layer uses these properties:

| Property | Tiled Type | Required | Description |
|----------|-----------|----------|-------------|
| `TriggerType` | `TriggerType` enum | **Yes** | The condition that activates this trigger. See [Trigger Types](#trigger-types). |
| `Action` | `Action` enum | **Yes** | The effect when the trigger fires. See [Actions](#actions). |
| `Name` | string | Optional | A unique name for this trigger. Required if other triggers reference it via `DependsOnCompletion`. Must be unique across all rooms in the map. |
| `DependsOnCompletion` | string | Optional | The `Name` of a prerequisite trigger. This trigger's condition is not evaluated until the prerequisite completes. Multiple triggers can depend on the same prerequisite. Cross-room references are supported. |
| `Target` | object ref or string | Per action | What the action applies to. Object references point to guardians or spawn points. Strings are used for filenames (`DoReplay`) and sound names (`PlaySound`). See each action for details. |
| `Threshold` | int | Per trigger/action | Numeric parameter. Meaning depends on context: item count for `ScoreThreshold`, percentage for `ScorePctThreshold`, room ID for `RoomEntered`, seconds for `Delay`, item count for `ItemCollectedInRoom`. |
| `GameModes` | `GameModes` enum (flags) | Optional | Restrict to specific game modes. If absent or 0, fires in all modes. |
| `SessionType` | `SessionType` enum (flags) | Optional | Restrict to single player (1), multiplayer (2), or both (3). If absent or 0, fires in all session types. |
| `Visibility` | `Visibility` enum | Optional | Who sees the effect: `AllPlayers` (default) or `TriggeringPlayer`. |
| `TriggerMode` | `TriggerMode` enum | Optional | Whether multiple players can trigger independently: `Unique` (default) or `PerPlayer`. |

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
| `GameStart` | — | Immediately when the game begins (or when its dependency completes). |
| `ScoreThreshold` | `Threshold` (int) | Player has collected >= N items globally. |
| `ScorePctThreshold` | `Threshold` (int, percentage 0–100) | Player has collected >= N% of the map's total items. |
| `RoomAllCollected` | — | All collectible items in this trigger's room have been picked up. |
| `ItemCollectedInRoom` | `Threshold` (int) | N or more items in this trigger's room have been collected. |
| `CollisionWith` | — | Player's bounding box overlaps this object's rectangle in the same room. |
| `RoomEntered` | `Threshold` (int, room ID) | Player enters the specified room. |
| `ExternalEvent` | — | Never fires from condition evaluation. Only fired explicitly by game code (e.g., MM exit FLAG_CAPTURED handler). Used as an entry point for trigger chains driven by game events. |
| `Never` | — | Never fires. Reserved for future use. |

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

These are orthogonal — all four combinations are valid:

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
| `Complete` | — | No visible effect. Immediately marks this trigger as complete. Useful as a dependency gate. |
| `HideGuardian` | `Target` (object ref to guardian) | Hides the guardian. It stops rendering and is no longer collidable. |
| `ShowGuardian` | `Target` (object ref to guardian) | Un-hides a previously hidden guardian. |
| `ReplaceGuardian` | `Target` (object ref to guardian) | Replaces the guardian's sprite with this object's tile graphic (GID). |
| `ShowTile` | — | Places this object's tile graphic at its position as a tile overlay. |
| `HideTile` | — | Restores the original tile at this object's position, removing a `ShowTile` overlay. |
| `ShowEntity` | — | Shows this object's tile graphic as a sprite overlay at its position. Used for celebration graphics (e.g., swordfish). The object must have a GID (tile reference). |
| `HideEntity` | `Target` (optional, object ref to guardian) | Without Target: hides MM exit entities in this trigger's room (used during celebrations so the ShowEntity graphic is visible). With Target: hides the referenced guardian (same effect as `HideGuardian`). |
| `TeleportPlayerTo` | `Target` (object ref to spawn point) | Moves the player to the target object's position. Clears all movement keys. |
| `RemovePlayer` | — | Hides the player sprite. Physics continue but the sprite is not rendered. |
| `DisablePlayerInput` | — | Suppresses movement keys (left, right, jump). Chat and menu keys still work. |
| `EnablePlayerInput` | — | Re-enables movement keys. Reverses `DisablePlayerInput`. |
| `EndGame` | — | Ends the game. SP: returns to title screen. MP: server declares the winner (player_id propagated through the trigger dependency chain) and transitions to the victory room. |
| `PlaySound` | `Target` (string, sound name) | Plays a sound effect. *(Not yet implemented.)* |

### Duration Actions

These take time to complete.  Downstream dependencies wait until the action finishes.

| Action | Parameters | Effect |
|--------|------------|--------|
| `Delay` | `Threshold` (int, seconds) | Does nothing for N seconds, then completes. |
| `DoReplay` | `Target` (string, filename) | Plays a replay file from the map's `replay/` subdirectory. Movement keys are disabled during playback. Completes when the replay finishes. |

---

## Examples

### Every TriggerType

#### GameStart — Multiplayer-only platform overlays

Extra platforms that appear only in multiplayer sessions.

```
TriggerType  = GameStart
Action       = ShowTile
SessionType  = 2          (MP only)
```

No `Name` or `DependsOnCompletion` needed — standalone immediate trigger.

#### ScoreThreshold — Hide guardian after collecting N items

Hide Maria when the player has collected 82 items.

```
TriggerType  = ScoreThreshold
Threshold    = 82
Action       = HideGuardian
Target       = (object ref to Maria guardian)
Name         = "score_gate"
SessionType  = 1          (SP only)
```

#### ScorePctThreshold — Show graphic at 50% completion

Show a congratulations tile when the player has collected half the items.

```
TriggerType  = ScorePctThreshold
Threshold    = 50
Action       = ShowTile
```

Note: `Threshold` is a percentage (0–100) when used with `ScorePctThreshold`.

#### RoomAllCollected — Gate on room completion

Mark a room's items as fully collected.

```
TriggerType  = RoomAllCollected
Action       = Complete
Name         = "room_clear"
```

#### ItemCollectedInRoom — Gate on partial room collection

Fire after collecting 3 items in this room.

```
TriggerType  = ItemCollectedInRoom
Threshold    = 3
Action       = ShowGuardian
Target       = (object ref to guardian)
```

#### CollisionWith — Player walks into a zone

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

#### RoomEntered — Trigger on entering a room

Fire when the player enters room 5.

```
TriggerType  = RoomEntered
Threshold    = 5
Action       = HideGuardian
Target       = (object ref to guardian)
```

#### ExternalEvent — Fired by game code

Used as an entry point for trigger chains driven by game events.  The MM exit handler
fires this when the player reaches the final exit.

```
TriggerType  = ExternalEvent
Action       = Complete
Name         = "items_done"
```

This trigger never fires from the engine's condition evaluation — it is only fired
by `fire_trigger_by_id("items_done")` from game code.

#### Never — Placeholder

Reserved.  Never fires automatically.

```
TriggerType  = Never
Action       = Complete
```

### Every Action

#### Complete — Dependency gate

```
TriggerType  = ScoreThreshold
Threshold    = 10
Action       = Complete
Name         = "ten_items"
```

Other triggers can use `DependsOnCompletion = "ten_items"` to fire after this.

#### HideGuardian / ShowGuardian — Toggle guardian visibility

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

#### ReplaceGuardian — Swap guardian sprite

The trigger object must be a tile object (have a GID).  The tile graphic replaces the
guardian's sprite.

```
TriggerType          = GameStart
DependsOnCompletion  = "replay"
Action               = ReplaceGuardian
Target               = (object ref to guardian)
Name                 = "replaced"
```

#### ShowTile / HideTile — Tile overlays

The trigger object must be a tile object (have a GID) for ShowTile.

```
TriggerType  = GameStart
Action       = ShowTile
SessionType  = 2
```

#### ShowEntity — Sprite overlay (e.g., swordfish)

The trigger object must be a tile object (have a GID).  The tile graphic renders as a
sprite at the object's position.

```
TriggerType          = GameStart
DependsOnCompletion  = "celebration"
Action               = ShowEntity
Name                 = "swordfish"
Visibility           = TriggeringPlayer
```

#### HideEntity — Hide entities

Without Target — hides MM exit sprites so the ShowEntity graphic is visible:

```
TriggerType          = GameStart
DependsOnCompletion  = "celebration"
Action               = HideEntity
Visibility           = TriggeringPlayer
```

With Target — hides a specific guardian:

```
TriggerType          = ScoreThreshold
Threshold            = 50
Action               = HideEntity
Target               = (object ref to guardian)
```

#### TeleportPlayerTo — Move player to a position

The `Target` must be an object reference to a spawn point or any object with a position.

```
TriggerType          = CollisionWith
DependsOnCompletion  = "items_done"
Action               = TeleportPlayerTo
Target               = (object ref to spawn point)
Name                 = "celebration"
```

#### RemovePlayer — Hide player sprite

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

#### EndGame — End the game

```
TriggerType          = GameStart
DependsOnCompletion  = "wait"
Action               = EndGame
```

In multiplayer, the winner's player_id is propagated through the trigger dependency
chain from the original event (e.g., FLAG_CAPTURED).

#### Delay — Timed pause

```
TriggerType          = GameStart
DependsOnCompletion  = "celebration"
Action               = Delay
Threshold            = 10
Name                 = "wait"
```

`Threshold` is in seconds.  The delay starts when the trigger fires (after all
dependencies are satisfied).

#### DoReplay — Play a replay file

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

### Manic Miner — Final Celebration (manic/020.tmx)

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

### Jet Set Willy — Endgame Sequence (jsw-gorgeous/034.tmx + 032.tmx)

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

No `Name` or `DependsOnCompletion` — standalone immediate triggers.

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

- **Pending:** Waiting for conditions — dependencies, filters, and the primary condition.
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
   - Player-specific actions (TeleportPlayerTo, DisablePlayerInput, RemovePlayer):
     only the targeted player executes.
6. **Late joiners** receive `TRIGGER_SYNC` with a bitset of all completed triggers.

### EndGame in Multiplayer

When the trigger chain reaches `EndGame`, the server detects `is_game_ending()` and
declares the winner.  The winner's player_id is propagated through the trigger
dependency chain — no separate tracking is needed.

### DoReplay in Multiplayer

Replay playback is client-local.  The server runs a fixed-duration timer as a fallback
(30 seconds).  Other players see the replaying player's movement via normal UDP position
sync.

---

## Special Objects (Team Doors/Barriers)

Team doors and team barriers are **reactive** — they toggle dynamically and are NOT
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
| `src/triggers/engine.py` | `TriggerEngine` — evaluation, dispatch, state tracking |
| `src/triggers/types.py` | Enums, `TriggerDef`, `TriggerRuntime`, `TriggerInstance` |
| `src/triggers/context.py` | `TriggerContext` protocol + `GameInstanceContext` adapter |
| `src/triggers/actions.py` | Standalone action functions |
| `src/server/trigger_service.py` | Server-authoritative engine + arbitration + broadcast |
| `src/network/protocol.py` | TRIGGER_REQ/FIRED/SYNC packet format |
| `src/map_registry.py` | Pack deserialization |
| `src/game_instance.py` | Client integration (SP engine tick, MP collision zones) |
| `src/rendering/entity_renderer.py` | Trigger graphic rendering |
| `tests/test_trigger_engine.py` | 74 unit tests |
| `tests/test_mp_trigger_celebration.py` | 19 MP trigger tests |
