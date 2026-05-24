# Current Inventory

This inventory applies the input-pipeline-refactor skill to the current CoronaEngine repository state.

## Executive Summary

Current status by input class:

| Input class | Current canonical path | Status | Decision |
|---|---|---|---|
| Native browser input | SDL -> ImGui -> CEF Host | healthy | keep |
| Editor command input | Frontend semantic command -> CEF query -> C++ -> Python | mostly healthy | keep and narrow |
| Realtime camera input | MainPage gesture -> V8/process message -> C++ realtime state | healthy but not fully converged | keep as primary |
| Legacy raw DOM event bridge | removed from source tree | cleaned | keep removed |

Main conclusion:

- The repo already has the correct native browser path.
- The repo already has the correct primary realtime path for camera drag.
- The previously mounted raw DOM bridge has been removed from the source tree.
- The main remaining architecture problem is now responsibility mixing inside `cef_client.cpp`.

## 1. Native Browser Input

Classification:
- Native Browser Input

Observed path:
- `SDL_Event` collection in `sdl_utils.cpp`
- frame orchestration in `imgui_ui.cpp`
- translation to CEF key and mouse events in `browser_ui.cpp`

Evidence:
- `BrowserInputHandler::process_sdl_key_event` and `send_key_events_to_browser` in `src/systems/ui/cef/browser_ui.cpp`
- `UiFrameRunner::run_frame` in `src/systems/ui/imgui/imgui_ui.cpp`
- keycode and mouse helpers in `src/systems/ui/sdl/sdl_utils.cpp`

Assessment:
- This path matches the skill.
- Text input, IME, focus-sensitive browser input, and browser widget keyboard handling belong here.
- No Python hop is required in this path.

Decision:
- Keep.

Notes:
- Do not re-implement browser text or focused widget keyboard behavior in JS.

## 2. Editor Command Input

Classification:
- Editor Command Input

Observed path:
- frontend semantic APIs in `bridge.js`
- `cefQuery` request/response transport
- browser-side dispatch in `cef_client.cpp`
- Python business handlers behind the query bridge

Evidence:
- `Bridge.callCEF` and service objects in `editor/Frontend/src/utils/bridge.js`
- `BrowserSideJSHandler::OnQuery` in `src/systems/ui/cef/cef_client.cpp`

Assessment:
- The semantic command surface is in good shape.
- The `bridge.js` API is mostly command-oriented and business-oriented.
- This is the right place for project, scene, dock, screenshot, and tool commands.

Decision:
- Keep.

Follow-up:
- Continue moving remaining low-frequency behaviors toward explicit command names instead of raw event payloads.

## 3. Realtime Camera Input

Classification:
- Realtime Input

Observed primary path:
- right-drag gesture and temporary interaction state in `MainPage.vue`
- V8 bridge call through `window.coronaBridge.cameraMove(...)`
- `CameraMoveFast` process message from renderer subprocess
- direct C++ mutation of `SharedDataHub::camera_storage()` in browser process

Observed sync path:
- one final `sceneService.cameraMove(...)` query call after drag end

Evidence:
- `scheduleCameraUpdate`, `sendCameraUpdateFast`, and `onMouseUp` in `editor/Frontend/src/views/layout/MainPage.vue`
- `cameraMove` V8 injection in `examples/cef_subprocess/main.cpp`
- `CameraMoveFast` handling in `src/systems/ui/cef/cef_client.cpp`

Assessment:
- This path matches the skill and should remain the primary path for active camera drag.
- The final low-frequency sync on mouse release is acceptable.
- This area is substantially improved compared with the original synchronous per-frame Python path.

Decision:
- Keep as canonical realtime path.

Convergence note:
- The final sync query is acceptable.
- Do not add per-frame query fallback back into the drag loop.

## 4. Removed Raw DOM Event Bridge

Previous classification:
- Mixed and ambiguous

Previous path:
- `App.vue` mounted `InputEventBridge` globally
- `InputEventBridge.vue` listened to document-level keyboard events
- raw event payloads were forwarded as `input_event`
- transport was `window.appService.send_message_to_main(commandName, JSON.stringify(payload))`

Cleanup result:
- `InputEventBridge.vue` was removed from `Frontend/src/components/bridge/`
- `App.vue` no longer mounts the bridge
- the only preserved behavior is a direct semantic Escape shortcut that calls `appService.addDockWidget('/SetUp')`

Runtime finding before cleanup:
- `window.appService` and `send_message_to_main` were `undefined` in the live CEF page
- `window.cefQuery` and `window.coronaBridge` existed

Assessment:
- The bridge was dead or unreachable in the current CEF runtime and has now been removed.
- This eliminates the clearest ownership violation in the frontend input path.

Decision:
- Keep removed.
- Do not reintroduce any raw DOM tunnel to Python.

Priority:
- completed

## 5. Responsibility Mixing in cef_client.cpp

Classification:
- Structural debt rather than wrong transport

Observed responsibilities in one file:
- browser lifecycle
- query bridge to Python
- offscreen rendering hooks
- renderer process message handling
- realtime camera bridge handling

Evidence:
- `src/systems/ui/cef/cef_client.cpp`

Assessment:
- The current realtime bridge behavior is correct.
- The file boundary is not.
- This does not block correctness today, but it raises future refactor cost and review ambiguity.

Decision:
- Keep behavior.
- Split implementation responsibilities when the next input migration happens.

Suggested future split:
- `cef_query_bridge.cpp`
- `cef_realtime_bridge.cpp`
- `cef_browser_client.cpp`

## 6. Inventory by File

### Keep
- `src/systems/ui/sdl/sdl_utils.cpp`
- `src/systems/ui/imgui/imgui_ui.cpp`
- `src/systems/ui/cef/browser_ui.cpp`
- `editor/Frontend/src/utils/bridge.js`
- `editor/Frontend/src/views/layout/MainPage.vue`
- `examples/cef_subprocess/main.cpp`
- `src/systems/ui/cef/cef_client.cpp` as current runtime bridge host

### Narrow or Refactor
- `src/systems/ui/cef/cef_client.cpp`

### Recently Cleaned
- `editor/Frontend/src/App.vue`
- removed `editor/Frontend/src/components/bridge/InputEventBridge.vue`

## 7. Recommended Next Actions

1. Keep camera drag on the V8 path and prohibit per-frame query reintroduction.
2. On the next bridge-related change, split `cef_client.cpp` by responsibility.
3. Do not add any new frontend path that depends on `window.appService.send_message_to_main`.

## 8. Practical Verdict

The current repository is not generally “input pipeline chaotic” anymore.

The actual remaining problem is narrower:
- one good native browser path exists
- one good realtime camera path exists
- the legacy raw DOM bridge has been removed

The next cleanup target is now structural separation inside `cef_client.cpp`.