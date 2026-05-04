# Ownership Matrix

Use this matrix to decide which layer is allowed to own state, interpret input, and mutate engine-visible data.

## Core Rule

Each input-driven feature must have:
- one primary state owner
- one primary transport path
- one final authority for engine-visible state

If two layers both interpret the same raw input or both mutate the same target state during the same interaction, the design is drifting.

## Layer Responsibilities

| Layer | May Own | Must Not Own | Typical Examples |
|---|---|---|---|
| Frontend page | temporary interaction state, local UI affordances, semantic command selection | authoritative engine realtime state, browser-native text dispatch | drag start position, hover state, active gizmo axis, shortcut mapping |
| SDL + ImGui | native event collection, focus, routing into browser host | editor business policy, Python command semantics | key events, text input, wheel, pointer focus |
| CEF page JS | page-local UX logic, semantic command creation, V8 bridge calls | long-running engine authority, raw browser-native duplication | toolbar buttons, command dispatch, realtime V8 calls |
| Browser-process C++ | realtime engine-facing state mutation, bridge dispatch, lifecycle glue | business policy that belongs in Python | camera storage updates, process-message handling |
| Python editor/plugins | business rules, tool orchestration, project and scene commands | per-frame device interpretation for migrated paths | save project, focus actor, open dock, import assets |
| Engine shared state | final data used by systems | frontend-only UX or command parsing | camera storage, scene state, render-facing values |

## Ownership by Input Class

## Native Browser Input

Primary owner:
- SDL + ImGui + CEF host

Final authority:
- CEF/browser widget state

Allowed frontend role:
- none unless the page itself intentionally owns the interaction

Python involvement:
- none

Examples:
- text field editing
- IME composition
- browser copy and paste
- page-local wheel scrolling

## Editor Command Input

Primary owner:
- frontend command layer

Final authority:
- Python business handler or editor command backend

Allowed frontend role:
- detect shortcut and map to command
- collect minimal command parameters

Python involvement:
- yes, as command consumer

Examples:
- save project
- open settings
- create scene
- run project

## Realtime Input

Primary owner:
- frontend interaction layer during gesture
- browser-process C++ for engine-visible realtime state

Final authority:
- C++ realtime state storage

Allowed frontend role:
- local math, smoothing, gesture state
- sending typed deltas or sampled state through V8

Python involvement:
- only after interaction end, if final sync is needed

Examples:
- camera orbit
- freelook
- transform gizmo drag
- viewport panning

## State Ownership Patterns

## Pattern A: Temporary Frontend, Authoritative C++
Use when interaction needs local responsiveness but engine state must update every frame.

Frontend owns:
- drag active flag
- previous cursor position
- temporary computed deltas

C++ owns:
- authoritative camera or transform state used by render systems

Python owns:
- optional post-interaction persistence or command follow-up

## Pattern B: Frontend Command, Python Authority
Use when the action is discrete and business-oriented.

Frontend owns:
- command trigger
- small argument payload

Python owns:
- policy and effect

C++ owns:
- transport only

## Pattern C: Native Browser Authority
Use when browser widgets or page-native editing semantics are involved.

SDL/ImGui/CEF own:
- key dispatch
- IME
- pointer routing
- focus

Frontend JS owns:
- page logic only after browser input has already been correctly delivered

Python owns:
- nothing in the input path

## Forbidden Shared Ownership

These combinations should be treated as bugs or architecture debt:

- Frontend and Python both interpreting raw keydown for the same shortcut.
- Frontend and C++ both authoritatively applying per-frame camera state.
- SDL native keyboard path and JS DOM keyboard bridge both active for the same browser text field.
- Python and browser-process C++ both mutating realtime camera state during active drag without a synchronization contract.

## Authority Questions

Ask these before changing code:

1. Who decides what this input means?
2. Who owns the final state used by engine systems?
3. Does any other layer also think it owns the same decision or state?
4. Can one of those owners be demoted to a temporary or compatibility role?

If the answers name more than one primary owner, refactor before adding features.

## Repo-Specific Defaults

Use these defaults unless there is a strong reason not to:

- Browser text and IME: `browser_ui.cpp` path owns it
- Camera drag: frontend gesture state plus C++ realtime storage own it
- Scene and project shortcuts: frontend command mapping plus Python command handler own it
- Dock and tool management: Python command layer owns it

## Exit Criteria

Ownership is considered clean when:
- one layer interprets the input
- one layer owns final state
- other layers only transport, display, or synchronize
- there is no duplicate raw-event parsing for the same feature
