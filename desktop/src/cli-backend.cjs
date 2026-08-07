const fs = require('node:fs');
const fsp = require('node:fs/promises');
const path = require('node:path');

const RUNTIME_SCHEMA_VERSION = 4;
const CLI_NOT_BUNDLED = 'OMNIDECK_CLI_NOT_BUNDLED';

function cliFilename(platform) {
  return platform === 'win32' ? 'omnideck-cli.exe' : 'omnideck-cli';
}

async function resolveCliPath({
  resourcesPath,
  platform = process.platform,
  env = process.env,
  access = (candidate) => fsp.access(candidate, fs.constants.X_OK),
} = {}) {
  const filename = cliFilename(platform);
  const candidates = [
    env.OMNIDECK_CLI_PATH,
    resourcesPath && path.join(resourcesPath, 'runtime', filename),
    path.join(__dirname, '..', 'build', 'runtime', filename),
  ].filter(Boolean);

  for (const candidate of [...new Set(candidates.map((value) => path.resolve(value)))]) {
    try {
      await access(candidate);
      return candidate;
    } catch {
      // Try the next packaged/development location.
    }
  }
  return null;
}

function parseJSON(value) {
  try {
    return JSON.parse(String(value || '').trim());
  } catch {
    return null;
  }
}

function parseJSONLines(value) {
  return String(value || '')
    .split(/\r?\n/)
    .map(parseJSON)
    .filter(Boolean);
}

function runtimeError(payload, fallback = 'The shared Omnideck runtime command failed.') {
  const detail = payload?.error;
  const error = new Error(detail?.message || fallback);
  if (detail?.code) error.code = detail.code;
  if (detail?.hint) error.hint = detail.hint;
  const failureKinds = {
    RESTART_REQUIRED: 'restart',
    PERMISSION_DENIED: 'permission',
    DOWNLOAD_FAILED: 'downloads',
    UNSUPPORTED: 'support',
    RUNTIME_SETUP_FAILED: 'environment',
    ENGINE_NOT_FOUND: 'environment',
    PORT_IN_USE: 'startup',
    CONTAINER_CONFLICT: 'startup',
  };
  if (failureKinds[detail?.code]) {
    error.diagnostic = failureKinds[detail.code];
    error.failureKind = failureKinds[detail.code];
  }
  return error;
}

function validateInstanceStatus(payload) {
  if (!payload || payload.error) throw runtimeError(payload);
  if (
    typeof payload.container !== 'string'
    || typeof payload.status !== 'string'
    || typeof payload.image !== 'string'
    || typeof payload.webUiPort !== 'string'
  ) {
    throw new Error('The bundled Omnideck CLI returned an invalid environment status.');
  }
  return payload;
}

function resourceMemoryMB(value) {
  const match = /^(\d+(?:\.\d+)?)\s*([kmgt])(?:i?b)?$/i.exec(String(value || '').trim());
  if (!match) return null;
  const multipliers = { k: 1 / 1024, m: 1, g: 1024, t: 1024 * 1024 };
  const memoryMB = Number.parseFloat(match[1]) * multipliers[match[2].toLowerCase()];
  return Number.isFinite(memoryMB) && memoryMB > 0 ? memoryMB : null;
}

function validateRuntimeStatus(payload) {
  if (!payload || payload.error) throw runtimeError(payload);
  if (payload.schemaVersion !== RUNTIME_SCHEMA_VERSION) {
    throw new Error(
      `The bundled Omnideck CLI runtime contract is ${payload.schemaVersion ?? 'unknown'}; expected ${RUNTIME_SCHEMA_VERSION}.`,
    );
  }
  if (payload.runtime !== 'podman' || typeof payload.ready !== 'boolean') {
    throw new Error('The bundled Omnideck CLI returned an invalid runtime status.');
  }
  if (
    typeof payload.resources?.container?.memory !== 'string'
    || typeof payload.resources?.container?.shmSize !== 'string'
    || typeof payload.resources?.machine?.mode !== 'string'
  ) {
    throw new Error('The bundled Omnideck CLI returned invalid resource defaults.');
  }
  const containerMemoryMB = resourceMemoryMB(payload.resources.container.memory);
  const sharedMemoryMB = resourceMemoryMB(payload.resources.container.shmSize);
  if (!containerMemoryMB || !sharedMemoryMB || sharedMemoryMB > containerMemoryMB) {
    throw new Error('The bundled Omnideck CLI returned incompatible container resource defaults.');
  }
  if (payload.resources.machine.mode === 'podman-managed') {
    const machineMemoryMB = payload.resources.machine.memoryMB;
    if (!Number.isFinite(machineMemoryMB) || machineMemoryMB < containerMemoryMB + 2048) {
      throw new Error('The bundled Omnideck CLI returned a macOS machine memory limit that is too small for the container.');
    }
  }
  return payload;
}

class OmnideckCliBackend {
  constructor({ resourcesPath, platform = process.platform, env, run }) {
    if (typeof run !== 'function') throw new TypeError('A process runner is required.');
    this.resourcesPath = resourcesPath;
    this.platform = platform;
    this.env = typeof env === 'function' ? env : () => env || process.env;
    this.run = run;
    this.resolvedPath = undefined;
  }

  async executable() {
    if (this.resolvedPath !== undefined) return this.resolvedPath;
    this.resolvedPath = await resolveCliPath({
      resourcesPath: this.resourcesPath,
      platform: this.platform,
      env: this.env(),
    });
    return this.resolvedPath;
  }

  async requireExecutable() {
    const executable = await this.executable();
    if (executable) return executable;
    const error = new Error('This copy of omnideck does not include its shared runtime helper.');
    error.code = CLI_NOT_BUNDLED;
    throw error;
  }

  async status() {
    const executable = await this.requireExecutable();
    const result = await this.run(executable, ['--json', 'runtime', 'status'], {
      env: this.env(),
      label: 'shared runtime status',
    });
    const payload = parseJSON(result.stdout);
    return validateRuntimeStatus(payload);
  }

  async ensure({ onEvent = () => {}, onInactivity = () => {} } = {}) {
    const executable = await this.requireExecutable();
    const events = [];
    let finalResult = null;
    let finalError = null;

    const consume = (line) => {
      const payload = parseJSON(line);
      if (!payload) return;
      events.push(payload);
      if (payload.stage) onEvent(payload);
      if (payload.stage === 'complete' && payload.state === 'done') finalResult = payload.result;
      if (payload.state === 'error' && payload.error) finalError = runtimeError(payload);
      if (payload.error && !payload.stage) finalError = runtimeError(payload);
      if (payload.schemaVersion) finalResult = payload;
    };

    let result;
    try {
      result = await this.run(executable, ['--json', 'runtime', 'ensure'], {
        env: this.env(),
        label: 'shared runtime setup',
        onLine: consume,
        inactivityMs: 90_000,
        onInactivity,
      });
    } catch (error) {
      if (events.length === 0) parseJSONLines(error.output).forEach((payload) => consume(JSON.stringify(payload)));
      if (finalError) {
        finalError.output = error.output;
        throw finalError;
      }
      throw error;
    }

    // Production receives lines live through onLine. This fallback also makes
    // the boundary straightforward to exercise with a non-streaming test runner.
    if (events.length === 0) parseJSONLines(result.stdout).forEach((payload) => consume(JSON.stringify(payload)));
    if (finalError) throw finalError;
    if (!finalResult) throw new Error('The shared Omnideck runtime command ended without a result.');
    return validateRuntimeStatus(finalResult);
  }

  async instanceStatus(name) {
    const executable = await this.requireExecutable();
    try {
      const result = await this.run(executable, ['--json', '--name', name, 'status'], {
        env: this.env(),
        label: 'application environment status',
      });
      return validateInstanceStatus(parseJSON(result.stdout));
    } catch (error) {
      const payload = parseJSONLines(error.output).find((line) => line?.error);
      if (payload) throw runtimeError(payload);
      throw error;
    }
  }

  async startInstance(name) {
    const executable = await this.requireExecutable();
    try {
      const result = await this.run(executable, ['--json', '--name', name, 'start'], {
        env: this.env(),
        label: 'start application environment',
      });
      return validateInstanceStatus(parseJSON(result.stdout));
    } catch (error) {
      const payload = parseJSONLines(error.output).find((line) => line?.error);
      if (payload) throw runtimeError(payload);
      throw error;
    }
  }

  async ensureEnvironment({
    name,
    image,
    port,
    memory,
    shmSize,
    homeVolume,
    stateVolume,
    onEvent = () => {},
    onInactivity = () => {},
  }) {
    const executable = await this.requireExecutable();
    const args = [
      '--json', '--name', name,
      'environment', 'ensure',
      '--image', image,
      '--port', String(port),
      '--memory', memory,
      '--shm-size', shmSize,
      '--home-volume', homeVolume,
      '--state-volume', stateVolume,
    ];
    const events = [];
    let finalResult = null;
    let finalError = null;
    const consume = (line) => {
      const payload = parseJSON(line);
      if (!payload) return;
      events.push(payload);
      if (payload.stage) onEvent(payload);
      if (payload.stage === 'complete' && payload.state === 'done') finalResult = payload.result;
      if (payload.state === 'error' && payload.error) finalError = runtimeError(payload);
      if (payload.error && !payload.stage) finalError = runtimeError(payload);
    };

    let result;
    try {
      result = await this.run(executable, args, {
        env: this.env(),
        label: 'reconcile application environment',
        onLine: consume,
        inactivityMs: 90_000,
        onInactivity,
      });
    } catch (error) {
      if (events.length === 0) parseJSONLines(error.output).forEach((payload) => consume(JSON.stringify(payload)));
      if (finalError) {
        finalError.output = error.output;
        throw finalError;
      }
      throw error;
    }
    if (events.length === 0) parseJSONLines(result.stdout).forEach((payload) => consume(JSON.stringify(payload)));
    if (finalError) throw finalError;
    if (!finalResult || typeof finalResult.action !== 'string') {
      throw new Error('The shared Omnideck environment command ended without a result.');
    }
    finalResult.status = validateInstanceStatus(finalResult.status);
    return finalResult;
  }
}

module.exports = {
  CLI_NOT_BUNDLED,
  OmnideckCliBackend,
  RUNTIME_SCHEMA_VERSION,
  cliFilename,
  parseJSONLines,
  resolveCliPath,
  validateRuntimeStatus,
  validateInstanceStatus,
};
