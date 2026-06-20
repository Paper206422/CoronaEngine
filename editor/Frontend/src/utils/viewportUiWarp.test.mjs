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

// Unified green-driven phase: the sample no longer depends on a channel arg.
const green = computeLfdUiWarpSample({
  pixelX: 32,
  pixelY: 16,
  rect: { x: 20, y: 10, width: 80, height: 40 },
  depth: 0.5,
  calibration,
});

assertNear(green.phaseAccumulator, (32 - 0.25 * 16) / 8 + 0.1);
assertNear(green.phase, 0.2);
assertNear(green.sampleX, 12.2);
assertNear(green.sampleY, 6);

const flat = computeLfdUiWarpSample({
  pixelX: 32,
  pixelY: 16,
  rect: { x: 20, y: 10, width: 80, height: 40 },
  depth: 0,
  calibration: { ...calibration, parallaxScale: 0 },
});
assert.equal(flat.sampleX, 12);
assert.equal(flat.sampleY, 6);

// Horizontal 2-tap linear interpolation: absoluteX = 7 + phase(0.75)*2 = 8.5,
// so the pixel blends column 8 (transparent) and column 9 (opaque white) 50/50.
const interpolatedPixel = computeLfdUiWarpPixel({
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
  sampleChannel: (x) => (x >= 9 ? [1, 1, 1, 1] : [0, 0, 0, 0]),
});

assert.deepEqual(interpolatedPixel.color, [0.5, 0.5, 0.5]);
assert.equal(interpolatedPixel.alpha, 0.5);

console.log('viewport UI warp tests passed');
