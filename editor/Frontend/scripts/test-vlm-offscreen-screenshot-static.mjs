import fs from 'node:fs';
import path from 'node:path';

const root = path.resolve(import.meta.dirname, '../../..');
const read = (rel) => fs.readFileSync(path.join(root, rel), 'utf8');
const assert = (condition, message) => {
  if (!condition) {
    throw new Error(message);
  }
};

const apiHeader = read('include/corona/systems/script/corona_engine_api.h');
const apiCpp = read('src/systems/script/python/corona_engine_api.cpp');
const bindings = read('src/systems/script/python/engine_bindings.cpp');
const cameraPy = read('editor/CoronaCore/core/entities/camera.py');
const reviewerPy = read('editor/plugins/AITool/cai_extensions/agent/model_reviewer.py');
const opticsHeader = read('include/corona/systems/optics/optics_system.h');
const opticsCpp = read('src/systems/optics/optics_system.cpp');
const sixViewPy = read('editor/plugins/AITool/cai_extensions/flows/model_retrieval_workflow/six_view_capture_tool.py');
const tempCapturePy = read('editor/plugins/AITool/cai_extensions/flows/model_retrieval_workflow/temp_capture_storage.py');

assert(apiHeader.includes('void set_offscreen_capture_mode(bool enabled);'),
  'Camera API must declare set_offscreen_capture_mode');
assert(apiCpp.includes('Camera::set_offscreen_capture_mode(bool enabled)'),
  'Camera API must implement set_offscreen_capture_mode');
assert(/follows_default_surface\s*=\s*false/.test(apiCpp) &&
  /surface\s*=\s*nullptr/.test(apiCpp) &&
  /view_open\s*=\s*false/.test(apiCpp),
  'offscreen mode must synchronously detach surface, default-following, and viewport state');
assert(bindings.includes('"set_offscreen_capture_mode"'),
  'engine bindings must expose set_offscreen_capture_mode');
assert(cameraPy.includes('def set_offscreen_capture_mode'),
  'Python Camera wrapper must expose set_offscreen_capture_mode');
assert(reviewerPy.indexOf('set_offscreen_capture_mode(True)') >= 0 &&
  reviewerPy.indexOf('set_offscreen_capture_mode(True)') < reviewerPy.indexOf('set_surface(0)'),
  'model_reviewer must enter offscreen mode before legacy set_surface(0)');

assert(opticsHeader.includes('offscreen_screenshot_targets_'),
  'OpticsSystem must keep screenshot render targets separate from surface targets');
assert(opticsCpp.includes('acquire_offscreen_screenshot_target'),
  'OpticsSystem must acquire render targets for no-surface screenshots');
assert(opticsCpp.includes('has_pending_screenshot(cam_handle)'),
  'Native no-surface cameras must render only when a screenshot is pending');
assert(/if\s*\(\s*offscreen_screenshot\s*\)\s*\{[\s\S]*?process_pending_screenshots\(cam_handle,\s*\*presented_target\);[\s\S]*?\}/.test(opticsCpp),
  'offscreen Native path must process pending screenshots after rendering');
assert(/if\s*\(\s*!offscreen_screenshot\s*\)[\s\S]*?OpticsFrameReadyEvent/.test(opticsCpp),
  'offscreen screenshot path must not publish OpticsFrameReadyEvent');
assert(opticsCpp.includes('fail_pending_screenshots(cam_handle)'),
  'unsupported or disabled cameras must fail pending screenshots deterministically');
assert(/event\.completion_promise\)->set_value\(false\)/.test(opticsCpp) ||
  /completion_promise->set_value\(false\)/.test(opticsCpp),
  'invalid screenshot requests must complete their promise with false');
assert(sixViewPy.includes('set_offscreen_capture_mode(True)'),
  'six-view temporary capture camera must use the offscreen capture API');
assert(tempCapturePy.includes('_save_camera_screenshot_with_timeout'),
  'temporary capture storage must wrap screenshot_sync with timeout and file readiness checks');

console.log('[OK] VLM offscreen screenshot static checks passed');
