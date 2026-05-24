# Deprecation Checklist

Use this checklist when converging the pipeline after a migration. The goal is not only to add the new path, but to remove the old ambiguous path.

## Principle

A migration is incomplete if the old path still behaves like a second primary route.

Temporary fallbacks are acceptable only when:
- initialization order requires them
- deployment compatibility requires them
- they are guarded and clearly documented

## Candidates for Removal

## Raw DOM Event Tunnels to Python
Deprecate when:
- the feature has been converted to semantic commands
- or the feature has moved to V8 realtime transport

Typical signs:
- payloads named `input_event`
- `keydown` or `keyup` forwarded as raw JSON
- mousemove samples sent through Python

Replacement:
- semantic command APIs for low-frequency behavior
- V8 typed functions for realtime behavior

## Per-frame JSON Query Loops
Deprecate when:
- a realtime interaction has a V8 or native path

Typical signs:
- per-frame `cefQuery`
- request-response in an active drag loop
- stale response suppression logic trying to compensate for transport delay

Replacement:
- browser-process direct state writes through V8 messages
- one final sync command after interaction end if needed

## Duplicate Native and JS Browser Input
Deprecate when:
- the browser-native path already delivers correct input to CEF widgets

Typical signs:
- text or key input handled both by SDL/native path and JS page bridge
- duplicate shortcut handling for page-local actions

Replacement:
- keep only SDL -> ImGui -> CEF Host for browser-native behavior

## Python-side Raw Device Parsing
Deprecate when:
- the feature has a command contract or realtime native path

Typical signs:
- Python modules inspecting `key`, `code`, `ctrlKey`, `movementX`, or similar device fields
- editor logic driven by DOM device payloads instead of commands

Replacement:
- command names and minimal business arguments

## Convergence Procedure

1. Identify the new primary path.
2. Enumerate every old path that still reaches the same behavior.
3. Mark each old path as one of:
   - remove now
   - guard as fallback
   - keep because it serves a different class of input
4. Add explicit comments or naming if a fallback remains.
5. Remove dead helpers, transport functions, and stale payload fields.

## What to Delete After Realtime Migration

After migrating a realtime feature, review and remove:
- stale request sequence suppression that only existed for query lag
- old JSON payload construction for per-frame updates
- Python-side handlers for per-frame updates
- duplicate frontend listeners that were only feeding the old path

## What to Keep After Realtime Migration

Keep only if still necessary:
- one final low-frequency sync command after interaction end
- capability detection for whether the V8 bridge is available
- temporary fallback to query during bootstrap or compatibility windows

## Review Questions

- Is there still any path sending raw device samples for this feature?
- Does the fallback activate only when the primary path is unavailable?
- Can a future reader tell which path is canonical?
- Are there old payload fields that no consumer now needs?
- Are we keeping compatibility code longer than necessary?

## Repo-Specific Cleanup Targets

During convergence, pay special attention to:
- `editor/Frontend/src/components/bridge/InputEventBridge.vue`
- `editor/Frontend/src/views/layout/MainPage.vue`
- `editor/Frontend/src/utils/bridge.js`
- `src/systems/ui/cef/cef_client.cpp`
- `examples/cef_subprocess/main.cpp`

These are the most likely places for mixed old and new paths to coexist.

## Done Definition

Deprecation is complete when:
- the migrated feature has one documented primary path
- old raw-event forwarding is removed or clearly fallback-only
- Python no longer sees raw per-frame input for that feature
- native browser input is not duplicated in JS
