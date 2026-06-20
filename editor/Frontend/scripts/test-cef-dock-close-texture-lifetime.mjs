import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const read = (path) => readFileSync(join(root, path), 'utf8');
const fail = (message) => {
  throw new Error(message);
};
const assertIncludes = (source, needle, message) => {
  if (!source.includes(needle)) fail(message);
};
const assertNotIncludes = (source, needle, message) => {
  if (source.includes(needle)) fail(message);
};
const functionBody = (source, signature) => {
  const start = source.indexOf(signature);
  if (start < 0) fail(`Missing function: ${signature}`);
  const open = source.indexOf('{', start);
  let depth = 0;
  for (let i = open; i < source.length; i += 1) {
    if (source[i] === '{') depth += 1;
    if (source[i] === '}') {
      depth -= 1;
      if (depth === 0) return source.slice(open + 1, i);
    }
  }
  fail(`Unterminated function: ${signature}`);
};

const browserManagerHeader = read('../../src/systems/ui/cef/browser_manager.h');
const browserManagerCpp = read('../../src/systems/ui/cef/browser_manager.cpp');
const browserManagerVulkan = read('../../src/systems/ui/vulk/browser_manager_vulkan.cpp');
const cefRealtimeBridge = read('../../src/systems/ui/cef/cef_realtime_bridge.cpp');

assertIncludes(
  browserManagerHeader,
  'DeferredTextureDestroy',
  'BrowserManager must keep closed dock textures alive in a deferred destroy queue'
);
assertIncludes(
  browserManagerHeader,
  'retire_deferred_tab_textures',
  'BrowserManager must retire deferred dock textures from the main update loop'
);

const destroyTextureBody = functionBody(
  browserManagerVulkan,
  'void BrowserManager::destroy_tab_texture(BrowserTab* tab)'
);
assertIncludes(
  destroyTextureBody,
  'deferred_texture_destroys_.push_back',
  'destroy_tab_texture must defer GPU image destruction instead of releasing immediately'
);
assertNotIncludes(
  destroyTextureBody,
  'owned_images_.erase(it);',
  'destroy_tab_texture must not immediately erase the owned image while ImGui/GPU may still reference it'
);

const updateBody = functionBody(browserManagerCpp, 'void BrowserManager::update()');
assertIncludes(
  updateBody,
  'retire_deferred_tab_textures();',
  'BrowserManager::update must drain deferred texture releases after enough frames'
);

const closeThisIndex = cefRealtimeBridge.indexOf('if (cmd == "closeThisTab")');
const closePanelIndex = cefRealtimeBridge.indexOf('if (cmd == "closePanelTab")');
if (closeThisIndex < 0 || closePanelIndex < 0) {
  fail('CEF dock close commands must exist');
}
const closeCommandRegion = cefRealtimeBridge.slice(closeThisIndex, closePanelIndex + 650);
assertIncludes(
  closeCommandRegion,
  'enqueue_main_thread_task',
  'CEF dock close commands must remove tabs through BrowserManager main-thread tasks'
);
assertNotIncludes(
  closeCommandRegion,
  'bm.remove_tab(tab_id);',
  'CEF dock close commands must not remove tabs synchronously from the CEF callback path'
);

console.log('CEF dock close texture lifetime constraints OK');
