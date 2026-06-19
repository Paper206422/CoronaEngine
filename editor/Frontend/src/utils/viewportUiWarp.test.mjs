import assert from 'node:assert/strict';

import {
  computeLfdUiWarpPixel,
  computeLfdUiWarpSample,
  normalizeLfdCalibration,
  wrapPhaseCentered,
} from './viewportUiWarp.js';

const assertNear = (actual, expected, epsilon = 1e-9) => {
  assert.ok(Math.abs(actual - expected) <= epsilon, `${actual} ~= ${expected}`);
};

assert.equal(wrapPhaseCentered(0.0), -1.0);
assert.equal(wrapPhaseCentered(0.5), 0.0);
assert.equal(wrapPhaseCentered(-0.75), -0.5);

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
assertNear(green.phaseAccumulator, (32 - 0.25 * 16) / 8 + 0.1);
assertNear(green.phase, 0.2);
assertNear(green.sampleX, 12.2);

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

const shiftedPixel = computeLfdUiWarpPixel({
  pixelX: 7,
  pixelY: 0,
  rect: { x: 0, y: 0, width: 16, height: 16 },
  depth: 1,
  calibration: {
    lenticularPitch: 8,
    slantAngleRadians: 0,
    phaseOffset: 0,
    rgbSubpixelOffsets: [0, 0, 0],
    parallaxScale: 2,
  },
  sampleChannel: (_channel, x) => (x >= 9 ? [1, 1, 1, 1] : [0, 0, 0, 0]),
});

assert.deepEqual(shiftedPixel.color, [1, 1, 1]);
assert.equal(shiftedPixel.alpha, 1);

console.log('viewport UI warp tests passed');
