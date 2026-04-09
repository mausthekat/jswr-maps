JSW:R Tiled Extension — Project Template
========================================

This directory contains the archetype files for JSW:R Tiled map projects.

Extensions
----------

Tiled does not support ES module imports or cross-file scope sharing in
its JavaScript extension system.  Each .js file in .extensions/ runs in
its own isolated scope.

To work around this, the extension source is split into multiple files in
extensions-src/ for maintainability, then BUNDLED into a single
.extensions/jswr.js at deploy time.

Source files (extensions-src/):
  jswr-common.js     - Shared constants and utility functions
  jswr-guardians.js  - Guardian/route property fixing, validation
  jswr-rooms.js      - Room creation, exit navigation
  jswr-triggers.js   - Trigger property helper

The bundled output (.extensions/jswr.js) is generated automatically by:
  python tmx/scripts/tmx_project.py refresh

DO NOT edit .extensions/jswr.js directly — your changes will be
overwritten on the next refresh.  Edit the source files in
extensions-src/ instead.

The refresh script:
  1. Concatenates all extensions-src/*.js files (alphabetically) into
     a single .extensions/jswr.js with a generated header
  2. Copies .extensions/jswr.js to all map project .extensions/ folders
  3. Updates .tiled-project files with archetype property types

Other Files
-----------
  archetype.tiled-project  - Property type definitions (enums, classes)
  archetype.tmx            - Room template
  archetype.world          - World file template
  templates/               - Object templates (spawn points, etc.)
