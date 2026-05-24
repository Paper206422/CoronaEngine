---
name: input-pipeline-refactor
description: 'Refactor CoronaEngine input handling when CEF, SDL, ImGui, V8, and Python responsibilities are mixed. Use for classifying input paths, separating native browser input from editor commands and realtime controls, migrating high-frequency input to V8, and preventing raw DOM or SDL events from leaking into Python.'
argument-hint: 'Describe the input flow or feature to refactor, such as camera drag, keyboard shortcuts, or browser text input.'
user-invocable: true
---

# Input Pipeline Refactor

Use this skill when CoronaEngine input handling has become ambiguous across CEF, SDL, ImGui, V8, and Python.

This skill is for restructuring input so each class of input has exactly one owner and one transport path.

## Goals
- Separate browser-native input from editor command input.
- Move high-frequency realtime input off the synchronous CEF to Python path.
- Stop forwarding raw DOM or SDL events into Python unless there is a clear command boundary.
- Keep CEF text input, IME, focus, and browser shortcuts on the native CEF path.
- Preserve low-frequency editor and tool commands on the existing CEF query or Python command path unless there is a concrete performance reason to migrate them.

## Input Classes
Always classify the feature into one of these three classes before editing code.

### 1. Native Browser Input
Use for:
- text input
- IME composition
- focused browser keyboard input
- browser mouse clicks, hover, wheel, selection
- webpage-local shortcuts

Required path:
- SDL -> ImGui -> CEF Host

In CoronaEngine this usually lives around:
- `src/systems/ui/sdl/`
- `src/systems/ui/imgui/`
- `src/systems/ui/cef/browser_ui.cpp`

Rules:
- Do not route these events through Python.
- Do not introduce DOM event bridges for these behaviors unless the page itself is the intended owner.
- Keep focus and modifier handling in the C++ UI layer.

### 2. Editor Command Input
Use for:
- menu actions
- dock open or close actions
- project save or load
- scene commands
- editor shortcuts that map directly to an application command

Required path:
- Frontend command -> CEF query or explicit bridge -> C++ -> Python command handler

Rules:
- Convert raw key or mouse events into semantic commands before they reach Python.
- Prefer commands like `project.save`, `scene.focus_actor`, or `editor.open_settings` over forwarding `keydown`, `keyup`, or DOM payloads.
- Python should receive command intent, not raw device state.

### 3. Realtime Input
Use for:
- camera drag
- camera orbit
- viewport freelook
- transform gizmo drag
- any continuous input sampled every frame or nearly every frame

Required path:
- Frontend or native input -> V8 or process message -> C++ realtime state

Rules:
- Do not send realtime input through synchronous Python calls.
- Do not wait for Python responses during active drag or movement.
- Python may receive a final synchronization event after interaction ends, but not the full per-frame stream.

## Decision Procedure
1. Identify the user-facing behavior and the actual owner.
2. Find the current path end-to-end.
3. Mark each hop as one of: native browser input, editor command, realtime input.
4. If a path mixes categories, split it at the earliest stable boundary.
5. Define one canonical path for that feature.
6. Migrate the highest-frequency segment first.
7. Add a fallback path only when bootstrapping or compatibility requires it.

## Refactor Procedure

### Step 1. Audit the Existing Path
Map the full chain from source event to final side effect.

Typical anchors in this repo:
- `editor/Frontend/src/components/bridge/InputEventBridge.vue`
- `editor/Frontend/src/views/layout/MainPage.vue`
- `editor/Frontend/src/utils/bridge.js`
- `examples/cef_subprocess/main.cpp`
- `src/systems/ui/cef/cef_client.cpp`
- `src/systems/ui/cef/browser_ui.cpp`
- `src/systems/ui/imgui/imgui_ui.cpp`
- `src/systems/ui/sdl/sdl_utils.cpp`

Questions to answer:
- Where does the event originate?
- Is the event still raw device input, or already a semantic command?
- Which layer currently owns focus?
- Does Python actually need to see this event?
- Is the path synchronous?
- Is the path per-frame or bursty?

### Step 2. Choose the Correct Owner
Use these ownership rules:
- Browser input belongs to CEF.
- Editor command dispatch belongs to frontend command code plus Python command handlers.
- Realtime state belongs to C++.

If two layers are both mutating the same state, remove one of them.

### Step 3. Normalize the Interface
Choose one interface type per class:
- Native browser input: CEF host APIs
- Editor commands: semantic command payloads
- Realtime input: typed V8 or process-message payloads

Avoid these anti-patterns:
- raw DOM keyboard events forwarded to Python for business logic
- raw SDL events forwarded to Python for continuous control
- per-frame JSON request-response loops during drag
- duplicated camera ownership in both Python and C++ during active interaction

### Step 4. Migrate Realtime Paths First
When the feature is realtime:
- inject a V8 API in the CEF render process
- send `CefProcessMessage` with typed numeric payloads
- update C++ realtime state directly
- optionally issue a final low-frequency sync command after drag end

In this repo, the V8 injection surface is typically:
- `examples/cef_subprocess/main.cpp`

The browser-process receiver is typically:
- `src/systems/ui/cef/cef_client.cpp`

### Step 5. Replace Raw Event Bridges with Commands
When the feature is not realtime:
- replace `input_event` style payloads with explicit command calls
- keep command names stable and semantic
- make payloads minimal and business-oriented

Good examples:
- `editor.open_settings`
- `project.save`
- `scene.switch`
- `scene.focus_actor`

Bad examples:
- `input_event` with raw `keydown`
- DOM `keyup` forwarded as-is to Python
- mouse move coordinates sent to Python when only a high-level action is needed

### Step 6. Keep Fallbacks Small and Temporary
If compatibility is needed:
- keep the old CEF query path only as fallback
- prefer fallback only when the V8 bridge is absent or initialization is incomplete
- remove the fallback once the new path is validated and fully adopted

## Repo-Specific Guidance

Load these references when you need concrete repo anchors or rollout guidance:
- [Target Files](./references/target-files.md)
- [Migration Playbook](./references/migration-playbook.md)
- [Ownership Matrix](./references/ownership-matrix.md)
- [Deprecation Checklist](./references/deprecation-checklist.md)

### Native Browser Input Surfaces
- `src/systems/ui/cef/browser_ui.cpp`
- `src/systems/ui/imgui/imgui_ui.cpp`
- `src/systems/ui/sdl/sdl_utils.cpp`

These files should remain the home for browser-focused keyboard, text, IME, and mouse behavior.

### Realtime Bridge Surfaces
- `examples/cef_subprocess/main.cpp`
- `src/systems/ui/cef/cef_client.cpp`

Use these for V8 function injection and browser-process message handling.

### Editor Command Surfaces
- `editor/Frontend/src/utils/bridge.js`
- `editor/Frontend/src/views/**`
- Python plugin entrypoints under `editor/plugins/`

Use these for semantic commands, not raw device streams.

## Expected Deliverables
When applying this skill, produce:
- a classification of the target input flow
- the canonical owner of that flow
- the target transport path
- a list of files to edit
- any compatibility fallback that remains
- explicit notes on what should no longer go through Python

## Validation Checklist
- Browser text input still works.
- IME still works.
- Focused CEF widgets still receive keyboard shortcuts.
- Realtime drag no longer blocks on Python.
- Python no longer receives per-frame raw device events for migrated features.
- Low-frequency commands still work after refactor.
- There is only one active owner for the target state.

## Review Checklist
Flag these as problems during review:
- one feature routed through both V8 and query without a clear primary path
- Python receiving raw key or mouse payloads for a migrated realtime feature
- browser-native input rerouted through command handlers
- duplicated state mutation in frontend and backend without a synchronization contract
- `cef_client.cpp` accumulating unrelated lifecycle, query, and realtime logic without clear separation

## Recommended End State
Use this target architecture:
- Native browser input: `SDL -> ImGui -> CEF Host`
- Editor commands: `Frontend command -> CEF query or bridge -> C++ -> Python`
- Realtime controls: `Frontend or native input -> V8/process message -> C++ state`

If the code does not fit one of these three paths cleanly, keep refactoring until it does.

## Convergence Rules

After a migration starts, the old path must be treated as deprecated.

- Do not leave two primary paths active for the same feature.
- If a fallback remains, it must activate only when the new path is unavailable.
- Remove raw event forwarding once the feature has a semantic command path or realtime V8 path.
- Remove Python from the hot path for migrated realtime interactions.

The migration is not complete until ownership is singular and the old path has been removed or explicitly downgraded to fallback-only behavior.
