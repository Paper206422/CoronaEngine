import assert from 'node:assert/strict';

import { buildDragRegions, dragRegionsSignature } from './cameraDragRegions.js';

const regions = buildDragRegions({
  toolbarRect: { left: 0, top: 0, right: 300, bottom: 34, width: 300, height: 34 },
  noDragRects: [
    { left: 24, right: 120, top: 4, bottom: 28 },
    { left: 200, right: 250, top: 4, bottom: 28 },
  ],
  padding: 2,
});

assert.deepEqual(regions, [
  { x: 0, y: 0, w: 22, h: 34 },
  { x: 122, y: 0, w: 76, h: 34 },
  { x: 252, y: 0, w: 48, h: 34 },
]);

assert.deepEqual(buildDragRegions({
  toolbarRect: { left: 0, top: 0, right: 100, bottom: 34, width: 100, height: 34 },
  noDragRects: [{ left: -10, right: 110, top: 0, bottom: 34 }],
}), [{ x: 0, y: 0, w: 0, h: 0 }]);

assert.equal(
  dragRegionsSignature([
    { x: 0.2, y: 0, w: 22.4, h: 34 },
    { x: 122, y: 0, w: 75.8, h: 34 },
  ]),
  dragRegionsSignature([
    { x: 0, y: 0, w: 22, h: 34 },
    { x: 122, y: 0, w: 76, h: 34 },
  ]),
);

console.log('camera drag region tests passed');
