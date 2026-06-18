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
