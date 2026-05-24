# Target Files

This reference lists the current CoronaEngine files involved in input routing and the role each one should play after refactoring.

## Frontend Event Sources

### editor/Frontend/src/components/bridge/InputEventBridge.vue
Current role:
- Captures DOM keyboard and mouse events.
- Forwards raw payloads through `window.appService.send_message_to_main(...)`.

Target role:
- Keep only low-frequency editor command bridging if still needed.
- Do not forward raw per-frame mouse or keyboard streams to Python.
- Convert editor-wide shortcuts into semantic commands.
- Realtime input should use V8 bridge calls instead of JSON or opaque runtime bridges.

### editor/Frontend/src/views/layout/MainPage.vue
Current role:
- Owns camera state in the frontend.
- Handles keyboard movement and right-drag camera rotation.
- Already contains a V8 fast-path for camera drag with fallback.

Target role:
- Continue to own temporary interaction state if needed for UX.
- Send realtime camera updates through V8 only during active interaction.
- Send final synchronization through the command path after interaction ends.
- Avoid mixing camera drag transport with unrelated editor commands.

### editor/Frontend/src/utils/bridge.js
Current role:
- Defines JSON `cefQuery` request helpers.

Target role:
- Remain the home for low-frequency command APIs.
- Do not become the transport for realtime controls.
- Keep command names semantic and business-oriented.

## CEF Realtime Bridge

### examples/cef_subprocess/main.cpp
Current role:
- Injects `cefQuery` in the renderer process.
- Already injects `window.coronaBridge.cameraMove`.

Target role:
- Host all V8 bridge entrypoints for realtime or latency-sensitive input.
- Keep payloads typed and compact.
- Prefer one function per capability rather than one raw event tunnel.

Examples of acceptable V8 APIs:
- `cameraMove(...)`
- `gizmoDrag(...)`
- `viewportPointerDelta(...)`

Examples to avoid:
- `sendRawInputEvent(json)`
- `dispatchDomEvent(type, payload)`

### src/systems/ui/cef/cef_client.cpp
Current role:
- Handles `cefQuery` browser-side dispatch into Python.
- Handles process messages from the renderer process.
- Handles browser lifecycle and rendering callbacks.

Target role:
- Keep query routing and realtime message handling separate by responsibility.
- Prefer small helpers or split implementation files when this file grows further.
- Realtime V8 messages should update C++ state directly.
- Query handlers should remain for low-frequency business commands.

Refactor direction:
- `cef_query_bridge.cpp`
- `cef_realtime_bridge.cpp`
- `cef_browser_client.cpp`

These do not need to be created immediately, but the file should move in that direction.

## Native Browser Input Path

### src/systems/ui/cef/browser_ui.cpp
Current role:
- Converts buffered SDL keyboard and text events into CEF key events.
- Sends mouse events into CEF based on ImGui state.

Target role:
- Remain the owner of browser-native input.
- Continue handling text input, key events, IME, wheel, and focus-sensitive browser shortcuts.
- Do not route these behaviors through Python.

### src/systems/ui/imgui/imgui_ui.cpp
Current role:
- Polls SDL events.
- Passes keyboard and text events into `BrowserInputHandler`.
- Sends the buffered events to the active browser tab.

Target role:
- Remain the frame orchestration point for UI event polling.
- Keep native browser input processing here.
- Avoid adding editor business logic or realtime scene logic into this path.

### src/systems/ui/sdl/sdl_utils.cpp
Current role:
- Processes SDL events.
- Decides whether events should be consumed by ImGui.

Target role:
- Remain the SDL event collection layer.
- Avoid leaking raw SDL events upward for Python business handling unless there is a strong reason.

## Python Command Layer

### editor/CoronaCore/core/corona_editor.py
Current role:
- Dispatches JSON requests from CEF query into registered Python modules.

Target role:
- Receive semantic commands and low-frequency requests.
- Avoid receiving raw DOM or SDL device events for realtime features.

### editor/plugins/
Current role:
- Hosts module entrypoints like `SceneTools`, `MainView`, and others.

Target role:
- Continue to implement editor business logic.
- Operate on command intent, not raw input samples.

## Camera State and Realtime Targets

### editor/CoronaCore/core/entities/camera.py
Current role:
- Python wrapper around engine camera.
- Exposes camera handle in the current refactor branch.

Target role:
- Used for low-frequency sync and serialization.
- Not the per-frame transport path during active drag.

### src/systems/script/python/corona_engine_api.cpp
Current role:
- Writes camera state into `SharedDataHub::camera_storage()`.

Target role:
- Remain authoritative for engine-facing camera state updates from Python.
- Realtime C++ paths may also write to the same storage during active interaction.
- Ownership boundaries must be explicit so Python and realtime paths do not fight over the same state simultaneously.

## Rule of Thumb by File

- `InputEventBridge.vue`: command bridge only, not raw realtime tunnel
- `MainPage.vue`: local interaction orchestration and V8 realtime calls
- `bridge.js`: low-frequency JSON command APIs
- `cef_subprocess/main.cpp`: V8 bridge injection
- `cef_client.cpp`: browser-side receiver and dispatch
- `browser_ui.cpp`: native browser input only
- `imgui_ui.cpp`: UI frame orchestration only
- `sdl_utils.cpp`: SDL collection and filtering only
- `corona_editor.py` and Python plugins: semantic command handling only

## Smells to Watch For

These indicate the pipeline is drifting again:
- a frontend file sends raw keyboard or mouse payloads to Python
- a Python plugin interprets DOM key state directly
- browser-native text input is reimplemented in JS
- CEF query is used inside a per-frame drag loop
- `cef_client.cpp` accumulates unrelated query, V8, rendering, lifecycle, and business logic without separation
