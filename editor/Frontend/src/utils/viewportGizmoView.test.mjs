import assert from 'node:assert/strict';
import { buildGizmoRenderModel } from './viewportGizmoView.js';

const state = {
  center: { screen: [160, 140] },
  scaleCenter: { screen: [100, 100] },
  axes: {
    x: { screenStart: [160, 140], screenEnd: [190, 140] },
    y: { screenStart: [160, 140], screenEnd: [160, 170] },
    z: { screenStart: [160, 140], screenEnd: [140, 120] },
  },
  scaleAxes: {
    x: { screenStart: [100, 100], screenEnd: [130, 100] },
    y: { screenStart: [100, 100], screenEnd: [100, 130] },
    z: { screenStart: [100, 100], screenEnd: [80, 80] },
  },
  rings: {
    x: { points: [[160, 140], [170, 150], [160, 160]] },
    y: { points: [[160, 140], [150, 150], [160, 160]] },
    z: { points: [[160, 140], [170, 130], [180, 140]] },
  },
};

{
  const model = buildGizmoRenderModel(state, 'move', { x: 100, y: 50 });
  assert.equal(model.visible, true);
  assert.deepEqual(model.center, [60, 90]);
  assert.deepEqual(model.axes.map((axis) => axis.start), [
    [60, 90],
    [60, 90],
    [60, 90],
  ]);
}

{
  const model = buildGizmoRenderModel(state, 'scale', { x: 100, y: 50 });
  assert.equal(model.visible, true);
  assert.deepEqual(model.center, [60, 90]);
  assert.equal(model.showUniformScale, true);
  assert.deepEqual(model.axes.map((axis) => axis.start), [
    [60, 90],
    [60, 90],
    [60, 90],
  ]);
}

{
  const model = buildGizmoRenderModel(state, 'rotate', { x: 100, y: 50 });
  assert.equal(model.visible, true);
  assert.deepEqual(model.center, [60, 90]);
  assert.equal(model.rings.length, 3);
  assert.match(model.rings[0].path, /^M 60 90/);
}

console.log('viewport gizmo view tests passed');
