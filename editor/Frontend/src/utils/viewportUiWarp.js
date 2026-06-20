const DEFAULT_CALIBRATION = Object.freeze({
  lenticularPitch: 19.1849,
  slantAngleRadians: 0.2333,
  phaseOffset: 10,
  rgbSubpixelOffsets: [0, 1 / 3, 2 / 3],
  parallaxScale: 19.1849,
});

export const wrapPhaseCentered = (phase) => {
  const wrapped = phase - Math.floor(phase);
  return 2 * wrapped - 1;
};

export const normalizeLfdCalibration = (calibration = {}) => {
  const pitch = Number(calibration.lenticularPitch);
  const offsets = Array.isArray(calibration.rgbSubpixelOffsets)
    ? calibration.rgbSubpixelOffsets
    : DEFAULT_CALIBRATION.rgbSubpixelOffsets;
  return {
    lenticularPitch: Number.isFinite(pitch) && Math.abs(pitch) > 1e-6
      ? pitch
      : DEFAULT_CALIBRATION.lenticularPitch,
    slantAngleRadians: Number(calibration.slantAngleRadians) || 0,
    phaseOffset: Number(calibration.phaseOffset) || 0,
    rgbSubpixelOffsets: [0, 1, 2].map((index) => Number(offsets[index]) || 0),
    parallaxScale: Number(calibration.parallaxScale) || 0,
  };
};

// Mirror of optics_ui_warp.comp.glsl. The warp uses a single unified phase
// driven by the central (green) sub-pixel offset — NOT per-channel shifts.
// Independent R/G/B shifts cause color fringing at sharp UI edges, so we derive
// one phase and one sample coordinate per pixel.
export const computeLfdUiWarpSample = ({
  pixelX,
  pixelY,
  rect,
  depth = 1,
  calibration,
}) => {
  const cal = normalizeLfdCalibration(calibration);
  const slope = Math.tan(cal.slantAngleRadians);
  const greenOffset = cal.rgbSubpixelOffsets[1];
  const phaseAccumulator =
    (Number(pixelX) + greenOffset - slope * Number(pixelY)) / cal.lenticularPitch +
    cal.phaseOffset;
  const phase = wrapPhaseCentered(phaseAccumulator);
  const horizontalOffset = phase * Number(depth) * cal.parallaxScale;
  const sampleX = Number(pixelX) - Number(rect?.x || 0) + horizontalOffset;
  const sampleY = Number(pixelY) - Number(rect?.y || 0);
  return {
    phaseAccumulator,
    phase,
    horizontalOffset,
    sampleX,
    sampleY,
  };
};

// Horizontal-only 2-tap linear interpolation between the neighboring columns,
// matching the shader's sampleBilinearX. sampleChannel(x, y) returns an RGBA
// tuple for the source overlay at integer (x, y).
export const computeLfdUiWarpPixel = ({
  pixelX,
  pixelY,
  rect,
  depth = 1,
  calibration,
  sampleChannel,
}) => {
  const warp = computeLfdUiWarpSample({ pixelX, pixelY, rect, depth, calibration });
  const originX = Number(rect?.x || 0);
  const originY = Number(rect?.y || 0);
  const absoluteX = originX + warp.sampleX;
  const sampleY = Math.round(originY + warp.sampleY);

  const x0 = Math.floor(absoluteX);
  const x1 = x0 + 1;
  const w = absoluteX - x0;
  const fetch = (x) => sampleChannel?.(x, sampleY) ?? [0, 0, 0, 0];
  const c0 = fetch(x0);
  const c1 = fetch(x1);
  const lerp = (a, b) => (a || 0) * (1 - w) + (b || 0) * w;
  const rgba = [0, 1, 2, 3].map((i) => lerp(c0[i], c1[i]));

  return {
    warp,
    samples: [{ warp, rgba }],
    color: [rgba[0], rgba[1], rgba[2]],
    alpha: rgba[3],
  };
};
