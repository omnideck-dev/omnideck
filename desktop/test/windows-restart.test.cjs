const assert = require('node:assert/strict');
const { EventEmitter } = require('node:events');
const test = require('node:test');

const {
  cancelWindowsSetupResume,
  restartWindows,
  scheduleWindowsSetupResume,
} = require('../src/windows-restart.cjs');

test('Windows restart uses the system shutdown command without forcing applications closed', async () => {
  const calls = [];
  let unrefCalled = false;
  const child = new EventEmitter();
  child.unref = () => { unrefCalled = true; };

  const restarting = restartWindows({
    platform: 'win32',
    systemRoot: String.raw`D:\Windows`,
    spawnProcess: (executable, args, options) => {
      calls.push({ executable, args, options });
      queueMicrotask(() => child.emit('spawn'));
      return child;
    },
  });

  await restarting;

  assert.deepEqual(calls, [{
    executable: String.raw`D:\Windows\System32\shutdown.exe`,
    args: ['/r', '/t', '0'],
    options: { detached: true, stdio: 'ignore', windowsHide: true },
  }]);
  assert.equal(unrefCalled, true);
});

test('computer restart is refused on other platforms', () => {
  assert.throws(
    () => restartWindows({ platform: 'darwin' }),
    /only supported on Windows/,
  );
});

test('setup resume is registered once for the installed executable', async () => {
  const calls = [];
  const child = new EventEmitter();
  const scheduled = scheduleWindowsSetupResume({
    platform: 'win32',
    systemRoot: String.raw`D:\Windows`,
    executable: String.raw`D:\Apps\OmniDeck\omnideck.exe`,
    spawnProcess: (executable, args, options) => {
      calls.push({ executable, args, options });
      queueMicrotask(() => child.emit('close', 0));
      return child;
    },
  });

  await scheduled;

  assert.deepEqual(calls, [{
    executable: String.raw`D:\Windows\System32\reg.exe`,
    args: [
      'add', String.raw`HKCU\Software\Microsoft\Windows\CurrentVersion\RunOnce`,
      '/v', 'omnideckSetupResume',
      '/t', 'REG_SZ',
      '/d', String.raw`"D:\Apps\OmniDeck\omnideck.exe"`,
      '/f',
    ],
    options: { stdio: 'ignore', windowsHide: true },
  }]);
});

test('a failed restart can remove the one-time resume entry', async () => {
  const calls = [];
  const child = new EventEmitter();
  const cancelling = cancelWindowsSetupResume({
    platform: 'win32',
    systemRoot: String.raw`D:\Windows`,
    spawnProcess: (executable, args, options) => {
      calls.push({ executable, args, options });
      queueMicrotask(() => child.emit('close', 0));
      return child;
    },
  });

  await cancelling;

  assert.deepEqual(calls[0].args, [
    'delete', String.raw`HKCU\Software\Microsoft\Windows\CurrentVersion\RunOnce`,
    '/v', 'omnideckSetupResume', '/f',
  ]);
});
