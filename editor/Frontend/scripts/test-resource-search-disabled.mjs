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

const sceneBar = read('src/views/sidebar/SceneBar.vue');
const bridge = read('src/utils/bridge.js');
const resourceSearch = read('../../editor/plugins/ResourceSearch/main.py');

assertIncludes(
  sceneBar,
  'const RESOURCE_SEARCH_ENABLED = false;',
  'SceneBar must keep resource search disabled'
);
assertIncludes(
  sceneBar,
  'v-if="RESOURCE_SEARCH_ENABLED"',
  'SceneBar must hide the resource search controls'
);
assertIncludes(
  sceneBar,
  'if (RESOURCE_SEARCH_ENABLED) {\n    resourceService.prepareIndex()',
  'SceneBar must not prewarm the resource index while disabled'
);
assertIncludes(
  bridge,
  'const RESOURCE_SEARCH_ENABLED = false;',
  'Bridge resourceService must keep ResourceSearch disabled'
);
assertIncludes(
  bridge,
  'resourceSearchDisabled()',
  'Bridge resourceService must return a local disabled response'
);
assertIncludes(
  bridge,
  "? Bridge.callCEF('ResourceSearch'",
  'Bridge resourceService must gate CEF ResourceSearch calls behind the disabled flag'
);
assertIncludes(
  resourceSearch,
  'RESOURCE_SEARCH_ENABLED = False',
  'Python ResourceSearch plugin must be disabled by default'
);
assertIncludes(
  resourceSearch,
  'return _disabled()',
  'Python ResourceSearch plugin must short-circuit before building indexes'
);

console.log('ResourceSearch disabled constraints OK');
