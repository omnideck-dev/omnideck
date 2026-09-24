import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import vm from 'node:vm';

const script = await readFile(new URL('../web/external-links.js', import.meta.url), 'utf8');

function makeWindow(url, topWindow = null) {
  const listeners = new Map();
  const location = new URL(url);
  const window = {
    location,
    addEventListener(type, listener) {
      const entries = listeners.get(type) || [];
      entries.push(listener);
      listeners.set(type, entries);
    },
  };
  window.top = topWindow || window;
  return {
    window,
    dispatch(type, event) {
      for (const listener of listeners.get(type) || []) listener(event);
    },
  };
}

function clickFor(anchor) {
  let prevented = false;
  let stopped = false;
  return {
    event: {
      target: { closest: () => anchor },
      preventDefault: () => { prevented = true; },
      stopImmediatePropagation: () => { stopped = true; },
    },
    result: () => ({ prevented, stopped }),
  };
}

function install(frame) {
  vm.runInNewContext(script, {
    console,
    Promise,
    URL,
    window: frame.window,
  });
}

test('desktop injection opens an external link through the native bridge', () => {
  const frame = makeWindow('http://127.0.0.1:48123/conversations/1');
  const opened = [];
  frame.window.omnideckHost = { openExternal: (url) => opened.push(url) };
  install(frame);

  const click = clickFor({
    href: 'https://example.com/guide',
    hasAttribute: () => false,
  });
  frame.dispatch('click', click.event);

  assert.deepEqual(opened, ['https://example.com/guide']);
  assert.deepEqual(click.result(), { prevented: true, stopped: true });
});

test('same-origin custom-app navigation remains inside the custom app', () => {
  const frame = makeWindow('http://127.0.0.1:48123/api/custom-apps/notes/web/');
  const opened = [];
  frame.window.omnideckHost = { openExternal: (url) => opened.push(url) };
  install(frame);

  for (const href of [
    'http://127.0.0.1:48123/api/custom-apps/notes/web/settings',
    'http://127.0.0.1:48123/api/custom-apps/notes/web/#details',
  ]) {
    const click = clickFor({ href, hasAttribute: () => false });
    frame.dispatch('click', click.event);
    assert.deepEqual(click.result(), { prevented: false, stopped: false });
  }
  assert.deepEqual(opened, []);
});

test('child-frame links are forwarded to the trusted top frame', () => {
  const top = makeWindow('http://127.0.0.1:48123/');
  const child = makeWindow('http://127.0.0.1:48123/home/omnideck/report.html', top.window);
  const opened = [];
  top.window.omnideckHost = { openExternal: (url) => opened.push(url) };
  top.window.postMessage = (data, targetOrigin) => {
    assert.equal(targetOrigin, child.window.location.origin);
    top.dispatch('message', {
      data,
      origin: child.window.location.origin,
      source: child.window,
    });
  };
  install(top);
  install(child);

  const click = clickFor({ href: 'https://example.com/', hasAttribute: () => false });
  child.dispatch('click', click.event);

  assert.deepEqual(opened, ['https://example.com/']);
  assert.deepEqual(click.result(), { prevented: true, stopped: true });
});
