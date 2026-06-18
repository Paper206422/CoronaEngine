import assert from 'node:assert/strict';
import { buildGizmoRenderModel } from './viewportGizmoView.js';

const state = {
  center: { screen: [160, 140] },
  axes: {
    x: { screenStart: [160, 140], screenEnd: [190, 140] },
    y: { screenStart: [160, 140], screenEnd: [160, 170] },
    z: { screenStart: [160, 140], screenEnd: [140, 120] },
  },
  rings: {
    x: { points: [[160, 140], [170, 150], [160, 160]] },
    y: { points: [[160, 140], [150, 150], [160, 160]] },
    z: { points: [[160, 140], [170, 130], [180, 140]] },
  },
};

for (const mode of ['move', 'scale', 'rotate']) {
  const model = buildGizmoRenderModel(state, mode, { x: 100, y: 50 });
  assert.equal(model.visible, false);
  assert.equal(model.mode, mode);
  assert.equal(model.center, null);
  assert.deepEqual(model.axes, []);
  assert.deepEqual(model.rings, []);
  assert.equal(model.showUniformScale, false);
}

console.log('viewport native gizmo view tests passed');
