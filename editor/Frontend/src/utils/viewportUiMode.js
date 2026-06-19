export const VIEWPORT_UI_MODES = Object.freeze(['flat2d', 'stereo3d']);

export const normalizeViewportUiMode = (mode) => (
  mode === 'stereo3d' ? 'stereo3d' : 'flat2d'
);

const safeStorage = () => {
  try {
    return globalThis.localStorage ?? null;
  } catch (_) {
    return null;
  }
};

const sanitizePart = (value, fallback) => {
  const text = String(value ?? '').trim();
  return text || fallback;
};

export const createViewportUiModeStore = ({ storage = safeStorage() } = {}) => {
  const keyFor = ({
    scope = 'main',
    sceneId = 'scene',
    cameraId = '',
    cameraHandle = '',
  } = {}) => {
    const viewId = cameraHandle || cameraId || 'default';
    return [
      'corona',
      'viewportUiMode',
      sanitizePart(scope, 'main'),
      sanitizePart(sceneId, 'scene'),
      sanitizePart(viewId, 'default'),
    ].join('.');
  };

  const get = (descriptor) => {
    const raw = storage?.getItem?.(keyFor(descriptor));
    return normalizeViewportUiMode(raw);
  };

  const set = (descriptor, mode) => {
    const normalized = normalizeViewportUiMode(mode);
    storage?.setItem?.(keyFor(descriptor), normalized);
    return normalized;
  };

  const applyToBridge = ({ bridge, cameraHandle, mode }) => {
    if (!cameraHandle || typeof bridge?.setViewportUiMode !== 'function') return false;
    bridge.setViewportUiMode(Number(cameraHandle), normalizeViewportUiMode(mode));
    return true;
  };

  return { keyFor, get, set, applyToBridge };
};

// 光场 3D UI 标定：UI 面板与传输层统一使用 Vision 光场语义 (pe/angle/offset)。
// pe/angle/offset 对应 vision::LenticularParams；parallaxScale 是 UI 专有的视差增益，
// 无 Vision 对应。子像素→warp(ViewportUiCalibration) 的换算在 C++ 边界统一完成。
export const DEFAULT_LIGHT_FIELD_CALIBRATION = Object.freeze({
  pe: 19.1813,
  angle: 0.2305,
  offset: 14.1171,
  parallaxScale: 19.1849,
});

export const normalizeLightFieldCalibration = (raw) => {
  const src = raw && typeof raw === 'object' ? raw : {};
  const num = (value, fallback) => {
    const n = Number(value);
    return Number.isFinite(n) ? n : fallback;
  };
  return {
    pe: num(src.pe, DEFAULT_LIGHT_FIELD_CALIBRATION.pe),
    angle: num(src.angle, DEFAULT_LIGHT_FIELD_CALIBRATION.angle),
    offset: num(src.offset, DEFAULT_LIGHT_FIELD_CALIBRATION.offset),
    parallaxScale: num(src.parallaxScale, DEFAULT_LIGHT_FIELD_CALIBRATION.parallaxScale),
  };
};

export const createViewportUiCalibrationStore = ({ storage = safeStorage() } = {}) => {
  const keyFor = ({
    scope = 'main',
    sceneId = 'scene',
    cameraId = '',
    cameraHandle = '',
  } = {}) => {
    const viewId = cameraHandle || cameraId || 'default';
    return [
      'corona',
      'viewportUiCalibration',
      sanitizePart(scope, 'main'),
      sanitizePart(sceneId, 'scene'),
      sanitizePart(viewId, 'default'),
    ].join('.');
  };

  const get = (descriptor) => {
    let raw = null;
    try {
      raw = JSON.parse(storage?.getItem?.(keyFor(descriptor)) ?? 'null');
    } catch (_) {
      raw = null;
    }
    return normalizeLightFieldCalibration(raw);
  };

  const set = (descriptor, calibration) => {
    const normalized = normalizeLightFieldCalibration(calibration);
    try {
      storage?.setItem?.(keyFor(descriptor), JSON.stringify(normalized));
    } catch (_) {
      // ignore storage failures
    }
    return normalized;
  };

  const applyToBridge = ({ bridge, cameraHandle, calibration }) => {
    if (!cameraHandle || typeof bridge?.setViewportUiCalibration !== 'function') return false;
    const c = normalizeLightFieldCalibration(calibration);
    bridge.setViewportUiCalibration(Number(cameraHandle), c.pe, c.angle, c.offset, c.parallaxScale);
    return true;
  };

  return { keyFor, get, set, applyToBridge };
};

export const createViewportUiCursorController = ({ getTarget } = {}) => {
  let restoreCursor = null;
  const targetFor = () => getTarget?.() ?? globalThis.document?.body ?? null;

  const restore = () => {
    const target = targetFor();
    if (target?.style && restoreCursor !== null) {
      target.style.cursor = restoreCursor;
    }
    restoreCursor = null;
  };

  const set = (cursor) => {
    const target = targetFor();
    if (!target?.style) return false;
    if (restoreCursor === null) {
      restoreCursor = target.style.cursor || '';
    }
    target.style.cursor = cursor || restoreCursor;
    return true;
  };

  return {
    set,
    restore,
    cancel: restore,
  };
};
