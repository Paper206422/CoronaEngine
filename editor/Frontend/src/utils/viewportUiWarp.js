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

export const computeLfdUiWarpSample = ({
  pixelX,
  pixelY,
  channel = 1,
  rect,
  depth = 0,
  calibration,
}) => {
  const cal = normalizeLfdCalibration(calibration);
  const clampedChannel = Math.max(0, Math.min(2, Math.trunc(channel)));
  const slope = Math.tan(cal.slantAngleRadians);
  const phaseAccumulator =
    (Number(pixelX) + cal.rgbSubpixelOffsets[clampedChannel] - slope * Number(pixelY)) /
      cal.lenticularPitch +
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

export const computeLfdUiWarpPixel = ({
  pixelX,
  pixelY,
  rect,
  depth = 0,
  calibration,
  sampleChannel,
}) => {
  const samples = [0, 1, 2].map((channel) => {
    const warp = computeLfdUiWarpSample({
      pixelX,
      pixelY,
      channel,
      rect,
      depth,
      calibration,
    });
    const rgba = sampleChannel?.(
      channel,
      Math.round(Number(rect?.x || 0) + warp.sampleX),
      Math.round(Number(rect?.y || 0) + warp.sampleY),
    ) ?? [0, 0, 0, 0];
    return {
      warp,
      rgba,
    };
  });
  return {
    samples,
    color: [samples[0].rgba[0] || 0, samples[1].rgba[1] || 0, samples[2].rgba[2] || 0],
    alpha: Math.max(samples[0].rgba[3] || 0, samples[1].rgba[3] || 0, samples[2].rgba[3] || 0),
  };
};
