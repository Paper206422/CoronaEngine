import assert from 'node:assert/strict';

import {
  computeLfdUiWarpSample,
  normalizeLfdCalibration,
  wrapPhaseCentered,
} from './viewportUiWarp.js';

assert.equal(wrapPhaseCentered(0.0), 0.0);
assert.equal(wrapPhaseCentered(0.5), -0.5);
assert.equal(wrapPhaseCentered(-0.75), 0.25);

const calibration = normalizeLfdCalibration({
  lenticularPitch: 8,
  slantAngleRadians: Math.atan(0.25),
  phaseOffset: 0.1,
  rgbSubpixelOffsets: [-0.2, 0, 0.2],
  parallaxScale: 2,
});

const red = computeLfdUiWarpSample({
  pixelX: 32,
  pixelY: 16,
  channel: 0,
  rect: { x: 20, y: 10, width: 80, height: 40 },
  depth: 0.5,
  calibration,
});
const green = computeLfdUiWarpSample({
  pixelX: 32,
  pixelY: 16,
  channel: 1,
  rect: { x: 20, y: 10, width: 80, height: 40 },
  depth: 0.5,
  calibration,
});

assert.notEqual(red.phase, green.phase);
assert.notEqual(red.sampleX, green.sampleX);
assert.equal(red.sampleY, green.sampleY);

const flat = computeLfdUiWarpSample({
  pixelX: 32,
  pixelY: 16,
  channel: 1,
  rect: { x: 20, y: 10, width: 80, height: 40 },
  depth: 0,
  calibration: { ...calibration, parallaxScale: 0 },
});
assert.equal(flat.sampleX, 12);
assert.equal(flat.sampleY, 6);

console.log('viewport UI warp tests passed');
