const assert = require('node:assert/strict');
const test = require('node:test');

const { shouldReloadForInput } = require('../src/window-shortcuts.cjs');

test('reload uses Control+R outside macOS and Command+R on macOS', () => {
  assert.equal(
    shouldReloadForInput(
      { type: 'keyDown', key: 'r', control: true, meta: false, alt: false },
      'linux',
    ),
    true,
  );
  assert.equal(
    shouldReloadForInput(
      { type: 'keyDown', key: 'R', control: false, meta: true, alt: false },
      'darwin',
    ),
    true,
  );
  assert.equal(
    shouldReloadForInput(
      { type: 'keyDown', key: 'r', control: true, meta: false, alt: false },
      'darwin',
    ),
    false,
  );
});

test('F5 reloads without modifiers and unrelated input is ignored', () => {
  assert.equal(
    shouldReloadForInput(
      { type: 'keyDown', key: 'F5', control: false, meta: false, alt: false },
      'win32',
    ),
    true,
  );
  assert.equal(
    shouldReloadForInput(
      { type: 'keyDown', key: 'r', control: false, meta: false, alt: false },
      'linux',
    ),
    false,
  );
  assert.equal(
    shouldReloadForInput(
      { type: 'keyUp', key: 'r', control: true, meta: false, alt: false },
      'linux',
    ),
    false,
  );
});
