export const AXIS_COLORS = {
  x: '#e65a50',
  y: '#7cc04b',
  z: '#4a8df6',
};

const AXIS_NAMES = ['x', 'y', 'z'];

const isPoint = (value) =>
  Array.isArray(value) &&
  value.length >= 2 &&
  Number.isFinite(Number(value[0])) &&
  Number.isFinite(Number(value[1]));

const toPoint = (value) => [Number(value[0]), Number(value[1])];

const normalizeMode = (mode) => (mode === 'scale' || mode === 'rotate' ? mode : 'move');

const normalizeOffset = (offset) => ({
  x: Number.isFinite(Number(offset?.x)) ? Number(offset.x) : 0,
  y: Number.isFinite(Number(offset?.y)) ? Number(offset.y) : 0,
});

const toLocalPoint = (value, offset) => {
  const point = toPoint(value);
  return [point[0] - offset.x, point[1] - offset.y];
};

const pointPath = (points, offset, close = false) => {
  const normalized = points.filter(isPoint).map((point) => toLocalPoint(point, offset));
  if (normalized.length < 2) return '';
  const segments = normalized.map((point, index) =>
    `${index === 0 ? 'M' : 'L'} ${point[0]} ${point[1]}`
  );
  return `${segments.join(' ')}${close ? ' Z' : ''}`;
};

const buildAxisItems = (axesSource, handle, offset) => {
  const axes = axesSource || {};
  return AXIS_NAMES
    .map((name) => {
      const axis = axes[name] || {};
      if (!isPoint(axis.screenStart) || !isPoint(axis.screenEnd)) return null;
      const start = toLocalPoint(axis.screenStart, offset);
      const end = toLocalPoint(axis.screenEnd, offset);
      return {
        name,
        color: AXIS_COLORS[name],
        handle,
        start,
        end,
        label: [
          end[0] + (end[0] - start[0]) * 0.16,
          end[1] + (end[1] - start[1]) * 0.16,
        ],
      };
    })
    .filter(Boolean);
};

const buildRingItems = (state, offset) => {
  const rings = state?.rings || {};
  return AXIS_NAMES
    .map((name) => {
      const points = Array.isArray(rings[name]?.points) ? rings[name].points : [];
      const path = pointPath(points, offset, true);
      if (!path) return null;
      return {
        name,
        color: AXIS_COLORS[name],
        path,
      };
    })
    .filter(Boolean);
};

export const buildGizmoRenderModel = (state, mode = 'move', screenOffset = {}) => {
  const normalizedMode = normalizeMode(mode);
  const offset = normalizeOffset(screenOffset);
  const centerSource = isPoint(state?.center?.screen) ? state.center : state?.scaleCenter;
  const center = isPoint(centerSource?.screen) ? toLocalPoint(centerSource.screen, offset) : null;
  if (!center) {
    return {
      visible: false,
      mode: normalizedMode,
      center: null,
      axes: [],
      rings: [],
      showUniformScale: false,
    };
  }

  if (normalizedMode === 'rotate') {
    const rings = buildRingItems(state, offset);
    return {
      visible: rings.length > 0,
      mode: normalizedMode,
      center,
      axes: [],
      rings,
      showUniformScale: false,
    };
  }

  const axesSource = state?.axes || state?.scaleAxes;
  const axes = buildAxisItems(axesSource, normalizedMode === 'scale' ? 'square' : 'arrow', offset);
  return {
    visible: axes.length > 0,
    mode: normalizedMode,
    center,
    axes,
    rings: [],
    showUniformScale: normalizedMode === 'scale',
  };
};
