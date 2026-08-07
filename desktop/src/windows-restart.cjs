const path = require('node:path');
const { spawn } = require('node:child_process');

const RUN_ONCE_KEY = String.raw`HKCU\Software\Microsoft\Windows\CurrentVersion\RunOnce`;
const RUN_ONCE_VALUE = 'omnideckSetupResume';

function windowsTool(name, options) {
  const systemRoot = options.systemRoot
    || process.env.SystemRoot
    || process.env.WINDIR
    || 'C:\\Windows';
  return path.win32.join(systemRoot, 'System32', name);
}

function assertWindows(platform) {
  if (platform !== 'win32') {
    throw new Error('Restarting the computer from omnideck is only supported on Windows.');
  }
}

function runAndWait(spawnProcess, executable, args) {
  return new Promise((resolve, reject) => {
    const child = spawnProcess(executable, args, {
      stdio: 'ignore',
      windowsHide: true,
    });
    child.once('error', reject);
    child.once('close', (code) => {
      if (code === 0) resolve();
      else reject(new Error(`${path.win32.basename(executable)} exited with code ${code}`));
    });
  });
}

function scheduleWindowsSetupResume(options = {}) {
  const platform = options.platform || process.platform;
  assertWindows(platform);
  const executable = options.executable || process.execPath;
  const spawnProcess = options.spawnProcess || spawn;
  return runAndWait(
    spawnProcess,
    windowsTool('reg.exe', options),
    [
      'add', RUN_ONCE_KEY,
      '/v', RUN_ONCE_VALUE,
      '/t', 'REG_SZ',
      '/d', `"${executable}"`,
      '/f',
    ],
  );
}

function cancelWindowsSetupResume(options = {}) {
  const platform = options.platform || process.platform;
  assertWindows(platform);
  const spawnProcess = options.spawnProcess || spawn;
  return runAndWait(
    spawnProcess,
    windowsTool('reg.exe', options),
    ['delete', RUN_ONCE_KEY, '/v', RUN_ONCE_VALUE, '/f'],
  );
}

function restartWindows(options = {}) {
  const platform = options.platform || process.platform;
  assertWindows(platform);
  const spawnProcess = options.spawnProcess || spawn;
  const executable = windowsTool('shutdown.exe', options);

  return new Promise((resolve, reject) => {
    const child = spawnProcess(executable, ['/r', '/t', '0'], {
      detached: true,
      stdio: 'ignore',
      windowsHide: true,
    });
    child.once('error', reject);
    child.once('spawn', () => {
      child.unref();
      resolve();
    });
  });
}

module.exports = {
  cancelWindowsSetupResume,
  restartWindows,
  scheduleWindowsSetupResume,
};
