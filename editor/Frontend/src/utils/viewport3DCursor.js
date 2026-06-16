const toFiniteNumber = (value, fallback = 0) => {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
};

const isEditableTarget = (target) => {
  const tag = String(target?.tagName || '').toLowerCase();
  return tag === 'input' || tag === 'textarea' || tag === 'select' || target?.isContentEditable;
};

const isToggleKey = (event) =>
  String(event?.code || '') === 'KeyC' || String(event?.key || '').toLowerCase() === 'c';

const isEscapeKey = (event) =>
  String(event?.code || '') === 'Escape' || String(event?.key || '') === 'Escape';

export const createViewport3DCursorController = ({
  getBridge,
  ensureCursorActor,
  getCameraBinding,
  getViewportRect,
  getViewportSize,
  getInitialCursorPoint,
  isInputSuppressed,
  onModeChange,
} = {}) => {
  let enabled = false;
  let cursorActorHandle = 0;
  let busy = false;

  const getContext = async () => {
    const binding = getCameraBinding?.() || {};
    const viewport = getViewportRect?.() || getViewportSize?.() || {};
    const cameraHandle = toFiniteNumber(binding.cameraHandle);
    const sceneId = binding.sceneId || '';
    const viewportX = toFiniteNumber(viewport.x ?? viewport.left);
    const viewportY = toFiniteNumber(viewport.y ?? viewport.top);
    const width = toFiniteNumber(viewport.width);
    const height = toFiniteNumber(viewport.height);
    const initialPoint = getInitialCursorPoint?.() || {};
    let startX = toFiniteNumber(initialPoint.x, Number.NaN);
    let startY = toFiniteNumber(initialPoint.y, Number.NaN);
    if (!Number.isFinite(startX)) startX = width * 0.5;
    if (!Number.isFinite(startY)) startY = height * 0.5;
    startX = Math.max(0, Math.min(width, startX));
    startY = Math.max(0, Math.min(height, startY));
    const bridge = getBridge?.();

    if (!bridge || typeof bridge.set3DCursorMode !== 'function' ||
        cameraHandle <= 0 || !sceneId || width <= 0 || height <= 0) {
      return null;
    }

    if (cursorActorHandle <= 0) {
      const actor = await ensureCursorActor?.(sceneId);
      cursorActorHandle = toFiniteNumber(actor?.actorHandle ?? actor?.handle);
    }

    if (cursorActorHandle <= 0) {
      return null;
    }

    return {
      bridge,
      cameraHandle,
      sceneId,
      cursorActorHandle,
      viewportX,
      viewportY,
      width,
      height,
      startX,
      startY,
    };
  };

  const setEnabled = async (nextEnabled) => {
    if (busy) return false;
    busy = true;
    try {
      const context = await getContext();
      if (!context) return false;
      context.bridge.set3DCursorMode(
        context.cameraHandle,
        context.sceneId,
        context.cursorActorHandle,
        Boolean(nextEnabled),
        context.viewportX,
        context.viewportY,
        context.width,
        context.height,
        context.startX,
        context.startY
      );
      enabled = Boolean(nextEnabled);
      onModeChange?.(enabled);
      return true;
    } catch (_) {
      return false;
    } finally {
      busy = false;
    }
  };

  return {
    isEnabled() {
      return enabled;
    },

    async enable() {
      return setEnabled(true);
    },

    async disable() {
      if (!enabled && cursorActorHandle <= 0) return false;
      return setEnabled(false);
    },

    async toggle() {
      return setEnabled(!enabled);
    },

    async handleKeyDown(event) {
      if (isEscapeKey(event)) {
        if (!enabled) return false;
        event?.preventDefault?.();
        return setEnabled(false);
      }

      if (!isToggleKey(event) || event?.repeat || isEditableTarget(event?.target) || isInputSuppressed?.()) {
        return false;
      }

      event?.preventDefault?.();
      return setEnabled(!enabled);
    },

    async release() {
      if (!enabled) return false;
      return setEnabled(false);
    },
  };
};
