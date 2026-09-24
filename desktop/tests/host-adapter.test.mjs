import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import vm from 'node:vm';

const adapter = await readFile(new URL('../web/host-adapter.js', import.meta.url), 'utf8');

async function harness({ bootstrapResult, bootstrapError } = {}) {
  const listeners = new Map();
  const invocations = [];
  const actionError = { hidden: true, textContent: '' };
  let channels = 0;

  class Channel {
    constructor() {
      channels += 1;
    }
  }

  const window = {
    __TAURI__: {
      core: {
        Channel,
        invoke: async (command) => {
          invocations.push(command);
          if (command === 'bootstrap') {
            if (bootstrapError) throw bootstrapError;
            return bootstrapResult;
          }
          return undefined;
        },
      },
    },
    addEventListener(type, callback) {
      listeners.set(type, callback);
    },
  };
  const context = vm.createContext({
    document: {
      getElementById(id) {
        return id === 'action-error' ? actionError : null;
      },
    },
    setTimeout(callback) {
      queueMicrotask(callback);
    },
    window,
  });
  vm.runInContext(adapter, context);

  listeners.get('DOMContentLoaded')();
  await new Promise((resolve) => setImmediate(resolve));
  return { actionError, channels, invocations, window };
}

test('welcome bootstrap does not start setup', async () => {
  const result = await harness({ bootstrapResult: { action: 'welcome', reason: 'first-run' } });
  assert.deepEqual(result.invocations, ['bootstrap']);
});

test('resume bootstrap starts setup exactly once', async () => {
  const result = await harness({ bootstrapResult: { action: 'setup', reason: 'resume' } });
  assert.deepEqual(result.invocations, ['bootstrap', 'begin_setup']);
});

test('duplicate initial events do not duplicate setup', async () => {
  const listeners = new Map();
  const invocations = [];
  let resolveSetup;
  class Channel {}
  const window = {
    __TAURI__: {
      core: {
        Channel,
        invoke: async (command) => {
          invocations.push(command);
          if (command === 'bootstrap') return { action: 'setup', reason: 'resume' };
          await new Promise((resolve) => { resolveSetup = resolve; });
          return undefined;
        },
      },
    },
    addEventListener(type, callback) {
      listeners.set(type, callback);
    },
  };
  const context = vm.createContext({ document: { getElementById: () => null }, setTimeout: queueMicrotask, window });
  vm.runInContext(adapter, context);
  const initial = listeners.get('DOMContentLoaded');
  initial();
  initial();
  await new Promise((resolve) => setImmediate(resolve));
  assert.deepEqual(invocations, ['bootstrap', 'begin_setup']);
  resolveSetup();
  await new Promise((resolve) => setImmediate(resolve));
  assert.deepEqual(invocations, ['bootstrap', 'begin_setup']);
});

test('rejected bootstrap is visible and releases the bridge', async () => {
  const result = await harness({ bootstrapError: new Error('bridge unavailable') });
  assert.deepEqual(result.invocations, ['bootstrap']);
  assert.equal(result.actionError.hidden, false);
  assert.equal(result.actionError.textContent, 'bridge unavailable');

  await result.window.omnideckHost.beginSetup();
  assert.deepEqual(result.invocations, ['bootstrap', 'begin_setup']);
});
