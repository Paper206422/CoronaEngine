import assert from 'node:assert/strict';

import {
  createViewportPickController,
  indexActorsByHandle,
} from './viewportPick.js';

const actorIndex = indexActorsByHandle([
  { name: 'Box', type: 'model', handle: 101 },
  { name: 'Ignored', type: 'actor', handle: 0 },
]);

const makeController = ({ hitRect, renderRect } = {}) => {
  const calls = [];
  const emitted = [];
  const pickStarts = [];
  const timers = [];

  const controller = createViewportPickController({
    retryDelayMs: 60,
    getBridge: () => ({
      pickActor: (...args) => {
        calls.push(args);
        return true;
      },
    }),
    getCameraBinding: () => ({
      cameraHandle: 77,
      sceneId: 'demo.scene',
    }),
    getHitRect: () => hitRect,
    getRenderRect: () => renderRect,
    getActorIndex: () => actorIndex,
    onPickStart: (...args) => {
      pickStarts.push(args);
    },
    emitActorChange: (...args) => {
      emitted.push(args);
    },
    setTimeoutFn: (fn, delay) => {
      timers.push({ fn, delay });
      return timers.length;
    },
    clearTimeoutFn: () => {},
    makeRequestId: (() => {
      let next = 10;
      return () => `pick-${next++}`;
    })(),
  });

  return { controller, calls, emitted, pickStarts, timers };
};

{
  const { controller, calls, emitted, pickStarts, timers } = makeController({
    hitRect: { left: 100, top: 50, width: 640, height: 360 },
    renderRect: { left: 0, top: 0, width: 1280, height: 720 },
  });

  const requestId = controller.pickAt({ clientX: 112, clientY: 84 });

  assert.equal(requestId, 'pick-10');
  assert.deepEqual(pickStarts, [['pick-10']]);
  assert.deepEqual(calls, [[77, 'demo.scene', 'pick-10', 112, 84, 1280, 720]]);
  assert.equal(timers.length, 1);
  assert.equal(timers[0].delay, 60);

  timers[0].fn();
  assert.deepEqual(calls[1], [77, 'demo.scene', 'pick-10', 112, 84, 1280, 720]);

  assert.deepEqual(controller.handlePickResult({
    status: 'success',
    sceneId: 'demo.scene',
    requestId: 'stale',
    actorHandle: 101,
  }), {
    status: 'stale',
    payload: {
      status: 'success',
      sceneId: 'demo.scene',
      requestId: 'stale',
      actorHandle: 101,
    },
  });
  assert.deepEqual(emitted, []);

  assert.deepEqual(controller.handlePickResult({
    status: 'success',
    sceneId: 'demo.scene',
    requestId: 'pick-10',
    actorHandle: 101,
  }), {
    status: 'selected',
    payload: {
      status: 'success',
      sceneId: 'demo.scene',
      requestId: 'pick-10',
      actorHandle: 101,
    },
    actor: {
      handle: 101,
      name: 'Box',
      type: 'model',
    },
  });
  assert.deepEqual(emitted, [['model', 'demo.scene', 'Box']]);

  assert.deepEqual(controller.handlePickResult({
    status: 'success',
    sceneId: 'demo.scene',
    requestId: 'pick-10',
    actorHandle: 404,
  }), {
    status: 'unknown',
    payload: {
      status: 'success',
      sceneId: 'demo.scene',
      requestId: 'pick-10',
      actorHandle: 404,
    },
  });
  assert.deepEqual(emitted, [['model', 'demo.scene', 'Box']]);

  assert.deepEqual(controller.handlePickResult({
    status: 'success',
    sceneId: 'demo.scene',
    requestId: 'pick-10',
    actorHandle: 404,
    actorName: 'Runtime Chair',
    actorType: 'model',
  }), {
    status: 'selected',
    payload: {
      status: 'success',
      sceneId: 'demo.scene',
      requestId: 'pick-10',
      actorHandle: 404,
      actorName: 'Runtime Chair',
      actorType: 'model',
    },
    actor: {
      handle: 404,
      name: 'Runtime Chair',
      type: 'model',
    },
  });
  assert.deepEqual(emitted, [
    ['model', 'demo.scene', 'Box'],
    ['model', 'demo.scene', 'Runtime Chair'],
  ]);

  assert.deepEqual(controller.handlePickResult({
    status: 'miss',
    sceneId: 'demo.scene',
    requestId: 'pick-10',
    actorHandle: 0,
  }), {
    status: 'miss',
    payload: {
      status: 'miss',
      sceneId: 'demo.scene',
      requestId: 'pick-10',
      actorHandle: 0,
    },
  });
  assert.deepEqual(emitted, [
    ['model', 'demo.scene', 'Box'],
    ['model', 'demo.scene', 'Runtime Chair'],
  ]);

  assert.deepEqual(controller.handlePickResult({
    status: 'error',
    sceneId: 'demo.scene',
    requestId: 'pick-10',
    actorHandle: 0,
  }), {
    status: 'error',
    payload: {
      status: 'error',
      sceneId: 'demo.scene',
      requestId: 'pick-10',
      actorHandle: 0,
    },
  });

  assert.deepEqual(controller.handlePickResult({
    status: 'pending',
    sceneId: 'demo.scene',
    requestId: 'pick-10',
    actorHandle: 0,
  }), {
    status: 'pending',
    payload: {
      status: 'pending',
      sceneId: 'demo.scene',
      requestId: 'pick-10',
      actorHandle: 0,
    },
  });

  assert.equal(controller.pickAt({ clientX: 1, clientY: 2 }, {
    bridge: { pickActor: () => { throw new Error('must not fallback'); } },
  }), false);
}

{
  const { controller, calls, timers } = makeController({
    hitRect: { left: 100, top: 50, width: 640, height: 360 },
    renderRect: { left: 0, top: 0, width: 1280, height: 720 },
  });

  assert.equal(controller.pickAt({ clientX: 99, clientY: 84 }), false);
  assert.equal(controller.pickAt({ clientX: 112, clientY: 49 }), false);
  assert.equal(controller.pickAt({ clientX: 740, clientY: 84 }), false);
  assert.equal(controller.pickAt({ clientX: 112, clientY: 410 }), false);
  assert.deepEqual(calls, []);
  assert.deepEqual(timers, []);
}

console.log('viewport pick tests passed');
