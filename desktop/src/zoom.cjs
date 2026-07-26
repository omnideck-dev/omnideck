const MIN_ZOOM = 0.5;
const MAX_ZOOM = 2.5;
const ZOOM_STEP = 0.1;

function clampZoom(factor) {
  if (!Number.isFinite(factor)) return 1;
  return Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, Math.round(factor * 100) / 100));
}

function zoomActionForInput(input, platform) {
  if (input.type !== 'keyDown' || input.alt) return null;
  const hasAccelerator = platform === 'darwin' ? input.meta : input.control;
  if (!hasAccelerator) return null;

  const key = input.key.toLowerCase();
  if (key === '+' || key === '=' || key === 'add') return 'in';
  if (key === '-' || key === 'subtract') return 'out';
  if (key === '0') return 'reset';
  return null;
}

function nextZoomFactor(current, action) {
  if (action === 'reset') return 1;
  if (action === 'in') return clampZoom(current + ZOOM_STEP);
  if (action === 'out') return clampZoom(current - ZOOM_STEP);
  return clampZoom(current);
}

module.exports = {
  clampZoom,
  nextZoomFactor,
  zoomActionForInput,
};
