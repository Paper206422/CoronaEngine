import assert from 'node:assert/strict';
import { createViewportGizmoController } from './viewportGizmo.js';

const calls = [];
const bridge = {
  getActorGizmoState: (...args) => calls.push(['state', args]),
  actorGizmoDrag: (...args) => calls.push(['drag', args]),
};
const hitRect = { left: 10, top: 20, width: 300, height: 200 };
const renderRect = { left: 0, top: 0, width: 1280, height: 720 };

const controller = createViewportGizmoController({
  getBridge: () => bridge,
  getCameraBinding: () => ({ cameraHandle: 11, sceneId: 'scene-a' }),
  getSelectedActor: () => ({ handle: 22 }),
  getHitRect: () => hitRect,
  getRenderRect: () => renderRect,
  makeRequestId: () => 'request-1',
  makeDragId: () => 'drag-1',
});

{
  const requestId = controller.requestState();
  assert.equal(requestId, 'request-1');
  assert.deepEqual(calls.shift(), ['state', [11, 'scene-a', 22, 'request-1', 1280, 720]]);
}

{
  const event = {
    clientX: 40,
    clientY: 70,
    stopPropagation() {},
    preventDefault() {},
  };
  assert.equal(controller.beginDrag({ mode: 'move', axis: 'x', event }), true);
  assert.deepEqual(calls.shift(), [
    'drag',
    [11, 'scene-a', 22, 'request-1', 'drag-1', 'start', 'move', 'x', 40, 70, 1280, 720],
  ]);
}

{
  const outsideController = createViewportGizmoController({
    getBridge: () => bridge,
    getCameraBinding: () => ({ cameraHandle: 11, sceneId: 'scene-a' }),
    getSelectedActor: () => ({ handle: 22 }),
    getHitRect: () => hitRect,
    getRenderRect: () => renderRect,
  });
  assert.equal(outsideController.beginDrag({
    mode: 'move',
    axis: 'x',
    event: {
      clientX: 5,
      clientY: 70,
      stopPropagation() {},
      preventDefault() {},
    },
  }), false);
}

{
  const payload = {
    status: 'success',
    requestId: 'request-1',
    sceneId: 'scene-a',
    actorHandle: 22,
    dragId: 'drag-1',
    phase: 'move',
    mode: 'move',
    axis: 'x',
    transform: {
      position: [1, 2, 3],
      rotation: [0, 0, 0],
      scale: [1, 1, 1],
    },
  };
  let emitted = null;
  let committed = null;
  const transformController = createViewportGizmoController({
    getBridge: () => bridge,
    getCameraBinding: () => ({ cameraHandle: 11, sceneId: 'scene-a' }),
    getSelectedActor: () => ({ handle: 22, name: 'cube', type: 'model' }),
    getHitRect: () => hitRect,
    getRenderRect: () => renderRect,
    makeRequestId: () => 'request-1',
    makeDragId: () => 'drag-1',
    emitTransformUpdate: (...args) => {
      emitted = args;
    },
    onTransformCommit: (...args) => {
      committed = args;
    },
  });
  transformController.requestState();
  calls.shift();
  transformController.beginDrag({
    mode: 'move',
    axis: 'x',
    event: {
      clientX: 40,
      clientY: 70,
      stopPropagation() {},
      preventDefault() {},
    },
  });
  calls.shift();
  assert.equal(transformController.handleTransform(payload), true);
  assert.deepEqual(emitted, ['scene-a', 'cube', [1, 2, 3], [0, 0, 0], [1, 1, 1], 'model']);
  assert.equal(committed, null);

  assert.equal(transformController.endDrag({
    clientX: 50,
    clientY: 80,
    stopPropagation() {},
    preventDefault() {},
  }), true);
  assert.deepEqual(calls.shift(), [
    'drag',
    [11, 'scene-a', 22, 'request-1', 'drag-1', 'end', 'move', 'x', 50, 80, 1280, 720],
  ]);
  assert.equal(transformController.handleTransform(payload), true);
  assert.equal(committed, null);
  assert.equal(transformController.handleTransform({ ...payload, phase: 'end' }), true);
  assert.deepEqual(committed, [
    'scene-a',
    'cube',
    'model',
    {
      position: [1, 2, 3],
      rotation: [0, 0, 0],
      scale: [1, 1, 1],
    },
  ]);
}

console.log('viewport gizmo tests passed');
