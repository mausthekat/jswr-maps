# Route Configuration Details

This document describes the route options and configurations supported by the JSWR format for guardian movement paths.

---

## Overview

Routes define how guardians (enemies) and lifts move within a room. Each guardian can have an associated route that specifies:
- **Path geometry** (polyline defining the patrol area)
- **Traversal pattern** (how the guardian behaves at path endpoints)
- **Speed** (movement speed multiplier)
- **Direction** (initial facing/movement direction)

---

## TMX Route Format

Routes are defined as objects in the "Routes" layer of TMX files.

### Basic Structure

```xml
<objectgroup id="6" name="Routes" color="#00ffff">
  <object id="2" type="Route" x="88" y="48">
    <properties>
      <property name="Direction" type="int" propertytype="Direction" value="1"/>
      <property name="Guardian" type="object" value="1"/>
      <property name="Speed" type="int" propertytype="Speed" value="1"/>
      <property name="Traversal" type="int" propertytype="Traversal" value="0"/>
    </properties>
    <polyline points="0,0 0,72"/>
  </object>
</objectgroup>
```

### Properties

| Property | Type | Description |
|----------|------|-------------|
| `Guardian` | object | Reference to the guardian object this route controls |
| `Direction` | int (Direction) | Initial facing direction (see Direction Values) |
| `Speed` | int (Speed) | Movement speed multiplier (see Speed Values) |
| `Traversal` | int (Traversal) | Movement pattern at endpoints (see Traversal Patterns) |
| `ResetDelay` | int | Ticks to pause before reset (One-Way Reset only, default: 0) |

### Polyline Format

The `<polyline points="..."/>` element defines the patrol path:
- Points are **relative** to the object's (x, y) position
- Format: `"x1,y1 x2,y2 x3,y3 ..."`
- Currently only single-segment paths (2 points) are fully supported
- Multi-segment paths are reserved for future use

**Examples:**
- Vertical path: `points="0,0 0,72"` (72 pixels tall)
- Horizontal path: `points="0,0 88,0"` (88 pixels wide)

---

## Direction Values

The Direction property specifies the initial facing/movement direction.

| Value | Name | Movement Direction |
|-------|------|-------------------|
| 0 | Up | Negative Y (upward) |
| 1 | Down | Positive Y (downward) |
| 2 | Left | Negative X (leftward) |
| 3 | Right | Positive X (rightward) |

**Note:** The direction determines both the sprite facing and the initial movement direction along the patrol path.

---

## Speed Values

The Speed property controls the guardian's movement speed.

| Value | Multiplier | Description |
|-------|------------|-------------|
| 0 | 0.0x | Stationary (no movement) |
| 1 | 1.0x | Normal speed (default) |
| 2 | 1.25x | Slightly faster |
| 3 | 1.5x | Faster |
| 4 | 1.75x | Fast |
| 5 | 2.0x | Double speed |
| 6 | 2.25x | Very fast |
| 7 | 2.5x | Maximum speed |
| 8 | 0.25x | Very slow (special value) |

**Base speeds:**
- Guardians: 1.0 pixels per tick
- Lifts: 0.5 pixels per tick

---

## Reset Delay

The `ResetDelay` property specifies how many game ticks the guardian pauses at the endpoint before teleporting to the opposite end of the route. This property only applies to **One-Way Reset (1)** traversal.

| Value | Behavior |
|-------|----------|
| 0 | Instant reset (no delay) |
| 1-255 | Pause for N ticks before reset |

**Timing reference:** The game runs at 20 ticks per second, so:
- `ResetDelay="20"` = 1 second pause
- `ResetDelay="40"` = 2 second pause
- `ResetDelay="10"` = 0.5 second pause

---

## Traversal Patterns

The Traversal property defines how the guardian behaves when reaching the end of its patrol path.

| Value | Name | Behavior |
|-------|------|----------|
| 0 | Ping-Pong | Reverses direction at each endpoint, oscillating back and forth |
| 1 | One-Way Reset | Moves to endpoint, then teleports to opposite end of route |
| 2 | One-Way Stop | Moves to endpoint, then stops permanently |
| 3 | Loop | For multi-segment paths: continues to next segment, loops at end |

### Ping-Pong (0) - Default

The guardian moves back and forth between the start and end points indefinitely.

```
Start -----> End
      <-----
      ----->
      <-----
      (repeats forever)
```

**Use cases:** Standard patrolling enemies, lifts

### One-Way Reset (1)

The guardian moves to the endpoint, pauses for a configurable delay, then teleports to the opposite end of the route and repeats.

```
End1 -----> End2 (pause)
  ^           |
  |___________|  (teleport to End1)
```

The delay is controlled by the `ResetDelay` property (see below). The guardian always teleports to the opposite route boundary from where it arrived, regardless of spawn position.

**Use cases:** Conveyor-like movement, enemies that "respawn" at a location, timed hazards

### One-Way Stop (2)

The guardian moves from start to end, then stops moving permanently.

```
Start -----> End (stopped)
```

**Use cases:** One-time events, triggered hazards, puzzle elements

### Loop (3)

For multi-segment paths, the guardian moves through each segment in order, then loops back to the first segment.

```
Segment 1 --> Segment 2 --> Segment 3
    ^                          |
    |__________________________|
```

**Note:** Loop behavior with single-segment paths is equivalent to Ping-Pong.

**Use cases:** Complex patrol routes, lifts with multiple stops

---

## JSWR Binary Format

Routes are encoded in the guardian's Movement/Path bitfield (1 byte).

### Movement/Path Bitfield

| Bit | Name | Description |
|-----|------|-------------|
| 0 | Axis | 0=horizontal, 1=vertical |
| 1-2 | Pattern | Traversal pattern (see below) |
| 3 | Diagonal | 0=axis-only, 1=diagonal allowed |
| 4-7 | Reserved | Reserved for future use |

### Pattern Bits

| Bits 1-2 | Value | Pattern |
|----------|-------|---------|
| 00 | 0 | Ping-Pong |
| 01 | 1 | One-Way Reset |
| 10 | 2 | One-Way Stop |
| 11 | 3 | Loop |

### Reset Delay Encoding

The ResetDelay value is stored in the guardian's reserved byte (offset 19 in the base record).

| Offset | Size | Field | Description |
|--------|------|-------|-------------|
| 19 | 1 | ResetDelay | Ticks to pause before reset (0-255) |

**Note:** This byte was previously marked as "Reserved" and is now used for ResetDelay when Traversal pattern is One-Way Reset (1). For other patterns, this byte should be 0.

---

## Multi-Waypoint Paths (Future)

The JSWR format supports multi-waypoint paths for complex routes. This feature is not yet fully implemented in the game engine.

### Extended Path Format

For guardians with `Waypoint Count > 1`, additional 20-byte segments follow the base guardian data:

| Offset | Size | Field | Description |
|--------|------|-------|-------------|
| 0 | 1 | Type | Entity type for this segment |
| 1-2 | 2 | From X | Segment start X (uint16 LE) |
| 3-4 | 2 | From Y | Segment start Y (uint16 LE) |
| 5-6 | 2 | To X | Segment end X (uint16 LE) |
| 7-8 | 2 | To Y | Segment end Y (uint16 LE) |
| 9 | 1 | Facing | Direction for this segment |
| 10 | 1 | Speed | Speed for this segment |
| 11-12 | 2 | Color | Color for this segment (9-bit RGB) |
| 13 | 1 | Movement/Path | Movement flags for this segment |
| 14-17 | 4 | Flags | Flags for this segment |
| 18-19 | 2 | Reserved | Reserved for future use |

### Future Capabilities

- **Diagonal movement:** Guardians moving at 45-degree angles
- **Per-segment properties:** Different speeds/colors at each waypoint
- **Complex patrol routes:** L-shaped, U-shaped, or arbitrary paths
- **Lift stops:** Multi-floor lifts with intermediate stops

---

## Implementation Status

| Feature | TMX Support | JSWR Support | Game Support |
|---------|-------------|--------------|--------------|
| Ping-Pong (0) | Yes | Yes | Yes |
| One-Way Reset (1) | Yes | Yes | Yes |
| One-Way Stop (2) | Yes | Yes | Yes |
| Loop (3) | Yes | Yes | Partial* |
| ResetDelay | Yes | Yes | Yes |
| Diagonal movement | No | Yes | No |
| Multi-waypoint paths | No | Yes | No |
| Per-segment properties | No | Yes | No |

*Loop behaves as Ping-Pong for single-segment paths.

---

## Examples

### Vertical Patrolling Guard

```xml
<object id="2" type="Route" x="88" y="48">
  <properties>
    <property name="Direction" type="int" propertytype="Direction" value="1"/>
    <property name="Guardian" type="object" value="1"/>
    <property name="Speed" type="int" propertytype="Speed" value="1"/>
    <property name="Traversal" type="int" propertytype="Traversal" value="0"/>
  </properties>
  <polyline points="0,0 0,72"/>
</object>
```

### Fast Horizontal One-Way Reset (Instant)

```xml
<object id="5" type="Route" x="0" y="104">
  <properties>
    <property name="Direction" type="int" propertytype="Direction" value="2"/>
    <property name="Guardian" type="object" value="4"/>
    <property name="Speed" type="int" propertytype="Speed" value="5"/>
    <property name="Traversal" type="int" propertytype="Traversal" value="1"/>
  </properties>
  <polyline points="0,0 256,0"/>
</object>
```

### One-Way Reset with 1 Second Delay

```xml
<object id="6" type="Route" x="0" y="80">
  <properties>
    <property name="Direction" type="int" propertytype="Direction" value="3"/>
    <property name="Guardian" type="object" value="5"/>
    <property name="Speed" type="int" propertytype="Speed" value="2"/>
    <property name="Traversal" type="int" propertytype="Traversal" value="1"/>
    <property name="ResetDelay" type="int" value="50"/>
  </properties>
  <polyline points="0,0 128,0"/>
</object>
```

### Slow Lift

```xml
<object id="3" type="Route" x="120" y="16">
  <properties>
    <property name="Direction" type="int" propertytype="Direction" value="1"/>
    <property name="Guardian" type="object" value="2"/>
    <property name="Speed" type="int" propertytype="Speed" value="8"/>
    <property name="Traversal" type="int" propertytype="Traversal" value="0"/>
  </properties>
  <polyline points="0,0 0,96"/>
</object>
```
---

## Switch-Selected Alternate Routes (JSW2 Crypt)

A guardian can carry a second patrol that applies **while a named
ToggleSwitch is ON** (see `MAP_TRIGGERS.md` for ToggleSwitch authoring).
The alternate route is an ordinary route object - rectangle or 2-point
polyline, same geometry rules as above - placed in a **Special** layer
with two properties:

| Property | Type | Description |
|----------|------|-------------|
| `Guardian` | object | The guardian this alternate route applies to |
| `Switch` | string | The ToggleSwitch latch `Name` that activates it |

While the switch is ON the guardian patrols the alternate bounds; thrown
OFF, it reverts to its authored route. On each swap the guardian keeps
its position and direction, clamped into the newly active bounds (a
parked One-Way-Stop guardian gets moving again if the new bounds put it
off its boundary). Speed, pattern, and direction stay those of the
authored route - the alternate supplies geometry only.

Switch state is per-player on each client (ToggleSwitch is not
network-synced), so treat this as a single-player / co-op-lenient
mechanic for now.

```xml
<!-- In a Special layer: the Crypt guardian sweeps further while the
     switch is on, opening the passage it normally blocks -->
<object id="31" x="64" y="88" width="112" height="16">
  <properties>
    <property name="Guardian" type="object" value="12"/>
    <property name="Switch" value="crypt_switch"/>
  </properties>
</object>
```

---

## Guardian Trails (JSW2 Foot leg / Belfry rope)

A guardian can draw a strip of a chosen 8x8 tile along its movement axis
- authored as properties **on the guardian object** (Enemies layer):

| Property | Type | Description |
|----------|------|-------------|
| `Trail` | string | `smear` or `tether` (anything else = no trail) |
| `TrailTile` | string (`tileset:local`, GID, CSV, or `leg`) | The tile repeated along the strip (required). **Preferred form is `tileset_name:local`** (e.g. `tiles_platform:91`) - it names the tileset and the tile's local index, so a Tiled re-save that recompacts tileset firstgids can never invalidate it. A raw GID still works but is map-file specific and **breaks silently if Tiled renumbers firstgids on save** - avoid it. A comma-separated list (of either form) draws N parallel strips across the guardian from its leading edge, one tile per 8px column; a single tile draws one strip at the sprite's centre column. The special token `leg` renders the strip with the final-death foot-crush **leg segment** sprite (16x8, per graphics style - works in enhanced and original modes without map tile art); it spans the guardian's full width from its left edge. Map-tile trails need the art present in BOTH tileset styles (`tiles_*.png` and `tiles_*_e.png`). |
| `TrailDeadly` | bool | The strip kills on touch, pixel-tested like the guardian's own sprite (default `false`) |
| `TrailAnchor` | string `"col,row"` | Anchor cell override (optional, see defaults below) |
| `TrailOffset` | int (signed px) | Nudge the strip along its **cross axis** from the auto-centred position, in pixels (`+` = right/down). Default `0`. The auto-centre assumes art symmetric about the guardian's centre; a guardian whose sprite is lopsided, or whose attach point is off-centre (a rope from an off-centre hand), authors a small `TrailOffset` to line the strip up. Applies on top of `TrailAnchor` too. |

Two modes:

- **`tether`** - a live strip from the anchor to the guardian's trailing
  edge; it extends and retracts as the guardian moves. Default anchor:
  the top of the room at the sprite's centre column (the Belfry bell
  rope, the Galactic Invasion threads).
- **`smear`** - a persistent strip from the guardian's spawn to the
  furthest point it has reached (its high-water mark); it never
  retracts, and clears only when the room resets. Default anchor: the
  spawn position (the Foot's leg descending over the exit).

Trails apply to single-axis (horizontal or vertical) movers only;
diagonal and bounce guardians ignore the properties (build note).
The strip renders beneath the guardian sprite and is derived entirely
from the guardian's synced state - late joiners see the same trail.

**The Foot Room recipe** (all-items-collected releases a descending
smear guardian): a vertical `START_FROZEN` guardian with `Trail=smear`,
`TrailDeadly=true`, a One-Way-Stop route running down over the exit, and
a trigger `RoomAllCollected -> StartGuardian` with
`RearmOnRoomExit=true` so the foot re-descends on every visit once the
room has been emptied.
