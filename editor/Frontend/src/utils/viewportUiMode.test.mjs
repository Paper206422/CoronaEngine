import assert from 'node:assert/strict';

import {
  createViewportUiCursorController,
  createViewportUiModeStore,
  normalizeViewportUiMode,
} from './viewportUiMode.js';

const storage = new Map();
const store = createViewportUiModeStore({
  storage: {
    getItem: (key) => storage.get(key) ?? null,
    setItem: (key, value) => storage.set(key, value),
  },
});

assert.equal(normalizeViewportUiMode('stereo3d'), 'stereo3d');
assert.equal(normalizeViewportUiMode('unknown'), 'flat2d');

const mainKey = store.keyFor({ scope: 'main', sceneId: 'demo', cameraHandle: 101 });
const cameraKey = store.keyFor({ scope: 'camera', sceneId: 'demo', cameraId: 'shotA' });
assert.notEqual(mainKey, cameraKey);

assert.equal(store.get({ scope: 'main', sceneId: 'demo', cameraHandle: 101 }), 'flat2d');
store.set({ scope: 'main', sceneId: 'demo', cameraHandle: 101 }, 'stereo3d');
store.set({ scope: 'camera', sceneId: 'demo', cameraId: 'shotA' }, 'flat2d');
assert.equal(store.get({ scope: 'main', sceneId: 'demo', cameraHandle: 101 }), 'stereo3d');
assert.equal(store.get({ scope: 'camera', sceneId: 'demo', cameraId: 'shotA' }), 'flat2d');

const bridgeCalls = [];
store.applyToBridge({
  bridge: { setViewportUiMode: (...args) => bridgeCalls.push(args) },
  cameraHandle: 101,
  mode: 'stereo3d',
});
assert.deepEqual(bridgeCalls, [[101, 'stereo3d']]);

const bodyStyle = { cursor: 'default' };
const cursor = createViewportUiCursorController({
  getTarget: () => ({ style: bodyStyle }),
});
cursor.set('grab');
assert.equal(bodyStyle.cursor, 'grab');
cursor.set('grabbing');
assert.equal(bodyStyle.cursor, 'grabbing');
cursor.restore();
assert.equal(bodyStyle.cursor, 'default');
cursor.set('crosshair');
cursor.cancel();
assert.equal(bodyStyle.cursor, 'default');

console.log('viewport UI mode tests passed');
