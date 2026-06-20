const toFiniteNumber = (value, fallback = 0) => {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
};

const normalizeRect = (rect) => {
  if (!rect) return null;
  const left = toFiniteNumber(rect.left);
  const top = toFiniteNumber(rect.top);
  const width = toFiniteNumber(rect.width);
  const height = toFiniteNumber(rect.height);
  return width > 0 && height > 0 ? { left, top, width, height } : null;
};

const containsClientPoint = (rect, clientX, clientY) =>
  rect &&
  clientX >= rect.left &&
  clientY >= rect.top &&
  clientX < rect.left + rect.width &&
  clientY < rect.top + rect.height;

const normalizeViewportPoint = (event, hitRect, renderRect) => {
  const clientX = Number(event?.clientX);
  const clientY = Number(event?.clientY);
  if (!Number.isFinite(clientX) || !Number.isFinite(clientY)) {
    return null;
  }

  const hit = normalizeRect(hitRect);
  if (!containsClientPoint(hit, clientX, clientY)) {
    return null;
  }

  const render = normalizeRect(renderRect);
  if (!render) {
    return null;
  }

  const width = render.width;
  const height = render.height;
  const x = clientX - render.left;
  const y = clientY - render.top;
  if (width <= 0 || height <= 0 || x < 0 || y < 0 || x >= width || y >= height) {
    return null;
  }

  return { x, y, width, height };
};

const normalizeViewportSize = (rect) => {
  const normalized = normalizeRect(rect);
  return normalized ? { width: normalized.width, height: normalized.height } : null;
};

const normalizeTransform = (transform) => ({
  position: Array.isArray(transform?.position) ? transform.position.map(Number) : [0, 0, 0],
  rotation: Array.isArray(transform?.rotation) ? transform.rotation.map(Number) : [0, 0, 0],
  scale: Array.isArray(transform?.scale) ? transform.scale.map(Number) : [1, 1, 1],
});

const isValidDragModeAxis = (mode, axis) => {
  if (mode !== 'move' && mode !== 'scale' && mode !== 'rotate') return false;
  if (axis !== 'x' && axis !== 'y' && axis !== 'z' && axis !== 'uniform') return false;
  if (axis === 'uniform') return mode === 'scale';
  return true;
};

export const createViewportGizmoController = ({
  getBridge,
  getCameraBinding,
  getHitRect,
  getRenderRect,
  getViewportRect,
  getSelectedActor,
  onStateChange,
  emitTransformUpdate,
  onTransformCommit,
  makeRequestId,
  makeDragId,
} = {}) => {
  let latestRequestId = '';
  let activeDrag = null;
  let requestSequence = 0;
  let dragSequence = 0;

  const nextRequestId =
    makeRequestId || (() => `gizmo-${Date.now()}-${++requestSequence}`);
  const nextDragId =
    makeDragId || (() => `drag-${Date.now()}-${++dragSequence}`);

  const getContext = () => {
    const bridge = getBridge?.();
    const binding = getCameraBinding?.() || {};
    const actor = getSelectedActor?.() || {};
    const hitRect = getHitRect?.() || getViewportRect?.();
    const renderRect = getRenderRect?.() || hitRect;
    const cameraHandle = Number(binding.cameraHandle || 0);
    const actorHandle = Number(actor.handle || 0);
    const sceneId = binding.sceneId || '';

    if (!bridge || cameraHandle <= 0 || actorHandle <= 0 || !sceneId) {
      return null;
    }

    return { bridge, cameraHandle, sceneId, actorHandle, actor, hitRect, renderRect };
  };

  const isSameDragTarget = (context, drag = activeDrag) => Boolean(
    context &&
    drag &&
    context.actorHandle === drag.actorHandle &&
    context.cameraHandle === drag.cameraHandle &&
    context.sceneId === drag.sceneId
  );

  const sendDragCommand = (drag, phase, point) => {
    const bridge = getBridge?.();
    if (!drag || !point || typeof bridge?.actorGizmoDrag !== 'function') {
      return false;
    }

    try {
      bridge.actorGizmoDrag(
        drag.cameraHandle,
        drag.sceneId,
        drag.actorHandle,
        drag.requestId,
        drag.dragId,
        phase,
        drag.mode,
        drag.axis,
        point.x,
        point.y,
        point.width,
        point.height
      );
    } catch (_) {
      return false;
    }

    return true;
  };

  const cancelActiveDrag = () => {
    if (!activeDrag) return;
    sendDragCommand(activeDrag, 'end', {
      x: activeDrag.startX,
      y: activeDrag.startY,
      width: activeDrag.width,
      height: activeDrag.height,
    });
    activeDrag = null;
  };

  const callDrag = (phase, event) => {
    if (!activeDrag) return false;
    event?.stopPropagation?.();
    event?.preventDefault?.();

    const context = getContext();
    if (!isSameDragTarget(context)) {
      if (phase === 'end') {
        cancelActiveDrag();
      }
      return false;
    }

    const point = normalizeViewportPoint(event, context.hitRect, context.renderRect);
    if (!point) {
      if (phase === 'end') {
        cancelActiveDrag();
      }
      return false;
    }

    return sendDragCommand(activeDrag, phase, point);
  };

  return {
    dispose() {
      cancelActiveDrag();
      latestRequestId = '';
    },

    currentRequestId() {
      return latestRequestId;
    },

    requestState() {
      const context = getContext();
      const viewport = normalizeViewportSize(context?.renderRect);
      if (!context || !viewport || typeof context.bridge.getActorGizmoState !== 'function') {
        onStateChange?.(null);
        return '';
      }

      const requestId = nextRequestId();
      latestRequestId = requestId;
      if (activeDrag && !isSameDragTarget(context)) {
        cancelActiveDrag();
      }

      try {
        context.bridge.getActorGizmoState(
          context.cameraHandle,
          context.sceneId,
          context.actorHandle,
          requestId,
          viewport.width,
          viewport.height
        );
      } catch (_) {
        onStateChange?.(null);
        return '';
      }

      return requestId;
    },

    handleState(payload) {
      const context = getContext();
      if (
        !context ||
        !payload ||
        payload.requestId !== latestRequestId ||
        Number(payload.actorHandle || 0) !== context.actorHandle ||
        (payload.sceneId || context.sceneId) !== context.sceneId
      ) {
        return false;
      }
      if (payload.status !== 'success') {
        onStateChange?.(null);
        return false;
      }

      onStateChange?.({
        ...payload,
        transform: normalizeTransform(payload.transform),
      });
      return true;
    },

    beginDrag({ mode, axis, event }) {
      if (!isValidDragModeAxis(mode, axis)) {
        return false;
      }

      const context = getContext();
      const point = normalizeViewportPoint(event, context?.hitRect, context?.renderRect);
      if (!context || !point || typeof context.bridge.actorGizmoDrag !== 'function') {
        return false;
      }

      activeDrag = {
        requestId: latestRequestId || nextRequestId(),
        dragId: nextDragId(),
        cameraHandle: context.cameraHandle,
        sceneId: context.sceneId,
        actorHandle: context.actorHandle,
        mode,
        axis,
        startX: point.x,
        startY: point.y,
        width: point.width,
        height: point.height,
        commitRequested: false,
      };
      if (!latestRequestId) {
        latestRequestId = activeDrag.requestId;
      }

      const started = callDrag('start', event);
      if (!started) {
        activeDrag = null;
      }
      return started;
    },

    moveDrag(event) {
      return callDrag('move', event);
    },

    endDrag(event) {
      const ended = callDrag('end', event);
      if (ended && activeDrag) {
        activeDrag.commitRequested = true;
      }
      return ended;
    },

    handleTransform(payload) {
      const context = getContext();
      if (
        !context ||
        !activeDrag ||
        !payload ||
        payload.status !== 'success' ||
        payload.requestId !== activeDrag.requestId ||
        payload.dragId !== activeDrag.dragId ||
        Number(payload.actorHandle || 0) !== activeDrag.actorHandle ||
        Number(payload.actorHandle || 0) !== context.actorHandle ||
        (payload.sceneId || context.sceneId) !== activeDrag.sceneId
      ) {
        return false;
      }

      const transform = normalizeTransform(payload.transform);
      onStateChange?.({
        ...payload,
        transform,
      });
      emitTransformUpdate?.(
        payload.sceneId || context.sceneId,
        context.actor.name,
        transform.position,
        transform.rotation,
        transform.scale,
        context.actor.type || 'actor'
      );
      if (activeDrag.commitRequested && payload.phase === 'end') {
        onTransformCommit?.(
          payload.sceneId || context.sceneId,
          context.actor.name,
          context.actor.type || 'actor',
          transform
        );
        activeDrag = null;
      }
      return true;
    },
  };
};
