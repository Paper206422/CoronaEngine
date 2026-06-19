const toRect = (rect) => ({
  left: Number(rect?.left ?? rect?.x ?? 0),
  top: Number(rect?.top ?? rect?.y ?? 0),
  right: Number(rect?.right ?? ((rect?.left ?? rect?.x ?? 0) + (rect?.width ?? 0))),
  bottom: Number(rect?.bottom ?? ((rect?.top ?? rect?.y ?? 0) + (rect?.height ?? 0))),
  width: Number(rect?.width ?? 0),
  height: Number(rect?.height ?? 0),
});

export const buildDragRegions = ({ toolbarRect, noDragRects = [], padding = 0 } = {}) => {
  const toolbar = toRect(toolbarRect);
  const width = Math.max(0, Math.round(toolbar.width || (toolbar.right - toolbar.left)));
  const height = Math.max(0, Math.round(toolbar.height || (toolbar.bottom - toolbar.top)));
  if (width <= 0 || height <= 0) {
    return [{ x: 0, y: 0, w: 0, h: 0 }];
  }

  const blockers = noDragRects
    .map(toRect)
    .map((rect) => ({
      left: Math.max(0, Math.floor(rect.left - toolbar.left - padding)),
      right: Math.min(width, Math.ceil(rect.right - toolbar.left + padding)),
    }))
    .filter((rect) => rect.right > rect.left)
    .sort((a, b) => a.left - b.left);

  const regions = [];
  let cursor = 0;
  for (const blocker of blockers) {
    if (blocker.left > cursor) {
      regions.push({ x: cursor, y: 0, w: blocker.left - cursor, h: height });
    }
    cursor = Math.max(cursor, blocker.right);
  }
  if (cursor < width) {
    regions.push({ x: cursor, y: 0, w: width - cursor, h: height });
  }
  return regions.length > 0 ? regions : [{ x: 0, y: 0, w: 0, h: 0 }];
};

export const dragRegionsSignature = (regions = []) => (
  Array.isArray(regions) ? regions : []
).map((region) => [
  Math.round(Number(region?.x ?? 0)),
  Math.round(Number(region?.y ?? 0)),
  Math.round(Number(region?.w ?? 0)),
  Math.round(Number(region?.h ?? 0)),
].join(',')).join('|');
