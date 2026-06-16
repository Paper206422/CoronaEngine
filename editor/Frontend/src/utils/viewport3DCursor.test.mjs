import assert from 'node:assert/strict';

import { createViewport3DCursorController } from './viewport3DCursor.js';

const makeEvent = (overrides = {}) => {
  let prevented = false;
  return {
    key: '',
    code: '',
    target: null,
    repeat: false,
    preventDefault() {
      prevented = true;
    },
    get prevented() {
      return prevented;
    },
    ...overrides,
  };
};

{
  const calls = [];
  const controller = createViewport3DCursorController({
    getBridge: () => ({
      set3DCursorMode: (...args) => calls.push(args),
    }),
    ensureCursorActor: async () => ({ status: 'success', actorHandle: 42 }),
    getCameraBinding: () => ({ cameraHandle: 7, sceneId: 'scene-a' }),
    getViewportRect: () => ({ x: 12, y: 34, width: 1280, height: 720 }),
    getInitialCursorPoint: () => ({ x: 512, y: 256 }),
  });

  const event = makeEvent({ key: 'c', code: 'KeyC' });
  assert.equal(await controller.handleKeyDown(event), true);
  assert.equal(event.prevented, true);
  assert.equal(controller.isEnabled(), true);
  assert.deepEqual(calls, [[7, 'scene-a', 42, true, 12, 34, 1280, 720, 512, 256]]);

  const esc = makeEvent({ key: 'Escape', code: 'Escape' });
  assert.equal(await controller.handleKeyDown(esc), true);
  assert.equal(controller.isEnabled(), false);
  assert.deepEqual(calls[1], [7, 'scene-a', 42, false, 12, 34, 1280, 720, 512, 256]);
}

{
  const calls = [];
  const controller = createViewport3DCursorController({
    getBridge: () => ({
      set3DCursorMode: (...args) => calls.push(args),
    }),
    ensureCursorActor: async () => ({ status: 'success', actorHandle: 21 }),
    getCameraBinding: () => ({ cameraHandle: 3, sceneId: 'scene-center' }),
    getViewportRect: () => ({ x: 20, y: 30, width: 800, height: 600 }),
    getInitialCursorPoint: () => null,
  });

  assert.equal(await controller.enable(), true);
  assert.deepEqual(calls, [[3, 'scene-center', 21, true, 20, 30, 800, 600, 400, 300]]);
}

{
  const calls = [];
  const controller = createViewport3DCursorController({
    getBridge: () => ({
      set3DCursorMode: (...args) => calls.push(args),
    }),
    ensureCursorActor: async () => ({ status: 'success', actorHandle: 9 }),
    getCameraBinding: () => ({ cameraHandle: 1, sceneId: 'scene-b' }),
    getViewportSize: () => ({ width: 640, height: 360 }),
    isInputSuppressed: () => true,
  });

  assert.equal(await controller.handleKeyDown(makeEvent({ key: 'c', code: 'KeyC' })), false);
  assert.equal(controller.isEnabled(), false);
  assert.deepEqual(calls, []);
}

{
  const calls = [];
  const input = { tagName: 'INPUT' };
  const controller = createViewport3DCursorController({
    getBridge: () => ({
      set3DCursorMode: (...args) => calls.push(args),
    }),
    ensureCursorActor: async () => ({ status: 'success', actorHandle: 9 }),
    getCameraBinding: () => ({ cameraHandle: 1, sceneId: 'scene-b' }),
    getViewportSize: () => ({ width: 640, height: 360 }),
  });

  assert.equal(await controller.handleKeyDown(makeEvent({ key: 'c', code: 'KeyC', target: input })), false);
  assert.deepEqual(calls, []);
}

console.log('viewport 3D cursor tests passed');
