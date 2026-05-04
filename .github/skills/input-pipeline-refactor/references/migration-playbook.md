# Migration Playbook

Use this playbook when refactoring an existing mixed input path into the target architecture.

## Strategy

Do not migrate everything at once.

Refactor in this order:
1. Realtime input
2. Editor commands
3. Cleanup and deletion of raw event tunnels

This order gives the biggest latency improvement first while keeping compatibility risk contained.

## Phase 1: Realtime Input Migration

Use this for:
- camera orbit
- freelook
- viewport drag
- gizmo manipulation
- any continuous interaction with visible frame-to-frame feedback

### Procedure
1. Identify the active interaction state owner in the frontend.
2. Keep temporary interaction math in the frontend only if needed for responsiveness.
3. Add a typed V8 bridge function in the renderer process.
4. Deliver the message to the browser process with `CefProcessMessage`.
5. Update C++ realtime state directly.
6. On interaction end, optionally send one low-frequency sync command through the normal command path.

### Requirements
- no synchronous Python call in the hot path
- no per-frame JSON round-trip
- no application of stale responses during active drag

### Validation
- interaction remains smooth under sustained drag
- Python command path still works after drag end
- state converges after final sync

## Phase 2: Editor Command Migration

Use this for:
- shortcuts like save, open settings, focus actor, run project
- toolbar actions
- menu actions
- dock actions

### Procedure
1. Find where raw input is currently forwarded.
2. Replace raw event payloads with a semantic command.
3. Keep transport on `cefQuery` unless there is a measured reason to migrate.
4. Route command to the Python module that owns the behavior.
5. Remove Python-side parsing of raw device state.

### Good command payloads
- `{ command: "project.save" }`
- `{ command: "editor.open_settings" }`
- `{ command: "scene.focus_actor", actor_name: "Cube" }`

### Bad command payloads
- `{ kind: "keyboard", type: "keydown", key: "s", ctrlKey: true }`
- `{ kind: "mouse", type: "mousemove", clientX: 100, clientY: 200 }`

## Phase 3: Native Browser Input Cleanup

Use this for:
- browser text fields
- text editing widgets inside CEF pages
- IME composition
- page-local shortcuts
- wheel and pointer behavior inside the browser content area

### Procedure
1. Confirm the path already reaches `BrowserInputHandler` and CEF host events.
2. Delete duplicate JS bridges for the same behavior.
3. Keep focus-sensitive behavior in the native path.
4. Verify that page interaction still works without Python involvement.

## Compatibility Pattern

When replacing a mixed path, use this temporary compatibility model:
- Primary path: new owner and transport
- Fallback path: old route only when initialization is incomplete or the new bridge is unavailable
- Exit criterion: remove fallback after validation and soak time

Do not keep dual-primary paths.

## Ownership Matrix

### Frontend
Owns:
- temporary interaction state
- local UX smoothing
- conversion from user action to semantic command

Does not own:
- authoritative engine realtime state
- browser-native text input dispatch

### C++ UI Layer
Owns:
- SDL collection
- ImGui integration
- native browser event injection
- realtime state updates from V8

Does not own:
- editor business policy
- high-level project logic

### Python Layer
Owns:
- editor business logic
- tool logic
- project and scene commands
- non-realtime orchestration

Does not own:
- per-frame control loops
- raw device event interpretation for migrated paths

## Refactor Templates

### Template A: Raw input_event to command
Before:
- JS emits raw keydown payload
- CEF query forwards JSON
- Python interprets device state

After:
- JS detects shortcut locally
- JS sends semantic command through existing command bridge
- Python receives command intent only

### Template B: Per-frame camera move to V8
Before:
- frontend computes camera state
- sends JSON camera updates every frame
- C++ calls Python synchronously
- Python writes camera state back into engine

After:
- frontend computes temporary state
- V8 sends typed payload to C++ every frame
- C++ writes camera state directly
- optional final sync runs through command bridge after drag end

### Template C: Browser input duplication removal
Before:
- SDL forwards native input to CEF
- JS also forwards DOM input to Python for the same interaction

After:
- native browser interaction stays on SDL -> ImGui -> CEF
- JS bridge is removed for that behavior

## Review Questions
- Is this feature browser-native, command-like, or realtime?
- Does the chosen owner match that class?
- Can Python be removed from the hot path?
- Is there exactly one primary transport?
- Can this payload be made semantic instead of raw?
- Is there any per-frame query-response loop left?

## Completion Criteria
A migration is complete when:
- the target feature fits exactly one class
- there is one primary path and at most one temporary fallback
- Python is not on the hot path for realtime behavior
- browser-native input does not depend on Python
- command handlers receive intent, not raw device samples
