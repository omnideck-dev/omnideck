/**
 * The packaged application removes Electron's menu, which also removes the
 * default Reload accelerator. Preserve a keyboard-only recovery path for a
 * stale renderer without exposing another application control.
 */
function shouldReloadForInput(input, platform) {
  if (input.type !== 'keyDown' || input.alt) return false;

  const key = input.key.toLowerCase();
  if (key === 'f5') return !input.control && !input.meta;

  const hasAccelerator = platform === 'darwin' ? input.meta : input.control;
  return hasAccelerator && key === 'r';
}

module.exports = { shouldReloadForInput };
