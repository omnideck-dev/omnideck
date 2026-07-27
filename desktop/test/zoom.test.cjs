const assert = require('node:assert/strict');
const test = require('node:test');

const {
  clampZoom,
  nextZoomFactor,
  zoomActionForInput,
} = require('../src/zoom.cjs');

test('zoom shortcuts use Control outside macOS', () => {
  assert.equal(
    zoomActionForInput({ type: 'keyDown', key: '=', control: true, meta: false }, 'linux'),
    'in',
  );
  assert.equal(
    zoomActionForInput({ type: 'keyDown', key: '-', control: true, meta: false }, 'win32'),
    'out',
  );
  assert.equal(
    zoomActionForInput({ type: 'keyDown', key: '0', control: true, meta: false }, 'linux'),
    'reset',
  );
});

test('zoom shortcuts use Command on macOS', () => {
  assert.equal(
    zoomActionForInput({ type: 'keyDown', key: '+', control: false, meta: true }, 'darwin'),
    'in',
  );
  assert.equal(
    zoomActionForInput({ type: 'keyDown', key: '+', control: true, meta: false }, 'darwin'),
    null,
  );
});

test('zoom factor changes in bounded steps and resets', () => {
  assert.equal(nextZoomFactor(1, 'in'), 1.1);
  assert.equal(nextZoomFactor(1.1, 'out'), 1);
  assert.equal(nextZoomFactor(1.8, 'reset'), 1);
  assert.equal(clampZoom(10), 2.5);
  assert.equal(clampZoom(0.1), 0.5);
});
