// Driving the command line tool, which is what actually manages the container.
//
// Everything crosses this boundary as JSON. Two shapes come back: one object
// for a question, and a line per step for work that takes a while. What
// separates success from failure is whether the object carries an `error`, not
// the exit status — asking for the status of something that is not running is
// a perfectly good answer and still exits non-zero.
const path = require('node:path');
const { spawn } = require('node:child_process');

// The tool's own vocabulary for what went wrong, mapped onto the screens this
// application shows. Anything unlisted is left unclassified rather than guessed
// at, because a wrong guess sends someone to fix the wrong thing.
const FAILURE_FOR_CODE = Object.freeze({
  ENGINE_NOT_FOUND: 'components',
  CONTAINER_NOT_FOUND: 'startup',
  NOT_INSTALLED: 'startup',
  AMBIGUOUS_INSTANCE: 'startup',
  CANCELLED: 'permission',
});

// The steps it reports while creating an installation, against the phases this
// application shows. Steps that are over before they register are not worth a
// phase of their own.
const PHASE_FOR_STAGE = Object.freeze({
  check_availability: 'download',
  create_home_volume: 'download',
  create_state_volume: 'download',
  pull_image: 'download',
  run_container: 'startup',
  save_config: 'startup',
});

class CommandLineError extends Error {
  constructor(code, message) {
    super(message || 'The omnideck command line tool reported a problem.');
    this.code = code;
    this.diagnostic = FAILURE_FOR_CODE[code] || null;
  }
}

// Bundled beside the application, with an override for running from a checkout
// against a tool built locally.
function executablePath(resourcesPath, platform = process.platform, env = process.env) {
  if (env.OMNIDECK_CLI_PATH) return env.OMNIDECK_CLI_PATH;
  return path.join(resourcesPath, 'cli', platform === 'win32' ? 'omnideck.exe' : 'omnideck');
}

function parseLines(text) {
  return text
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      try {
        return JSON.parse(line);
      } catch {
        return null;
      }
    })
    .filter(Boolean);
}

class CommandLine {
  constructor({ executable, configDirectory, instanceName, appendLog = async () => {} }) {
    this.executable = executable;
    this.configDirectory = configDirectory;
    this.instanceName = instanceName;
    this.appendLog = appendLog;
  }

  // Its configuration directory is passed explicitly so this drives the same
  // installation whatever the environment around it says.
  environment() {
    return { ...process.env, OMNIDECK_CONFIG_DIR: this.configDirectory, NO_COLOR: '1' };
  }

  spawn(args, onLine) {
    return new Promise((resolve, reject) => {
      const child = spawn(this.executable, [...args, '--json'], {
        env: this.environment(),
        windowsHide: true,
        shell: false,
      });
      let stdout = '';
      let stderr = '';
      let pending = '';
      child.stdout.on('data', (chunk) => {
        stdout += chunk;
        if (!onLine) return;
        pending += chunk;
        const lines = pending.split('\n');
        pending = lines.pop();
        for (const line of lines) {
          const [parsed] = parseLines(line);
          if (parsed) onLine(parsed);
        }
      });
      child.stderr.on('data', (chunk) => { stderr += chunk; });
      child.on('error', reject);
      child.on('close', (code) => resolve({ code, stdout, stderr }));
    });
  }

  // A question with one answer. Throws when the answer is an error, so callers
  // read a value rather than a result.
  async ask(args) {
    const result = await this.spawn(args);
    await this.appendLog(`$ omnideck ${args.join(' ')} (${result.code})`);
    if (result.stderr.trim()) await this.appendLog(`[omnideck] ${result.stderr.trim()}`);
    const [payload] = parseLines(result.stdout);
    if (!payload) {
      throw new CommandLineError(
        'INTERNAL_ERROR',
        result.stderr.trim() || 'The omnideck command line tool said nothing.',
      );
    }
    if (payload.error) throw new CommandLineError(payload.error.code, payload.error.message);
    return payload;
  }

  // The same, for a question whose negative answer is not a failure: not being
  // installed is a state, not a problem. A container that is missing is not one
  // of these — that comes back as a status of its own, saying so.
  async askOrNull(args, codes = ['NOT_INSTALLED']) {
    try {
      return await this.ask(args);
    } catch (error) {
      if (error instanceof CommandLineError && codes.includes(error.code)) return null;
      throw error;
    }
  }

  // Work reported step by step. onStep is told the phase this application shows
  // for each step, and the last line carries the result.
  async work(args, onStep = () => {}) {
    let failure = null;
    let result = null;
    const outcome = await this.spawn(args, (event) => {
      if (event.state === 'error' && event.error) {
        failure = new CommandLineError(event.error.code, event.error.message);
        return;
      }
      if (event.stage === 'complete') {
        result = event.result || {};
        return;
      }
      onStep({
        phase: PHASE_FOR_STAGE[event.stage] || null,
        stage: event.stage,
        state: event.state,
        detail: event.detail || '',
      });
    });
    await this.appendLog(`$ omnideck ${args.join(' ')} (${outcome.code})`);
    if (outcome.stderr.trim()) await this.appendLog(`[omnideck] ${outcome.stderr.trim()}`);
    if (failure) throw failure;
    if (outcome.code !== 0) {
      const [payload] = parseLines(outcome.stdout).filter((line) => line.error);
      throw new CommandLineError(
        payload?.error?.code || 'INTERNAL_ERROR',
        payload?.error?.message || outcome.stderr.trim(),
      );
    }
    return result;
  }

  status() {
    return this.askOrNull(['status', '--name', this.instanceName]);
  }

  start() {
    return this.ask(['start', '--name', this.instanceName]);
  }

  stop() {
    return this.ask(['stop', '--name', this.instanceName]);
  }

  // The name and browser port it would give a new installation, chosen to
  // avoid every installation it already knows about — including this one.
  suggestedDefaults() {
    return this.ask(['setup', '--suggest-defaults']);
  }

  create({ image, port }, onStep) {
    return this.work([
      'setup', '--plain',
      '--name', this.instanceName,
      '--image', image,
      '--port', String(port),
      '--runtime', 'podman',
    ], onStep);
  }
}

module.exports = {
  CommandLine,
  CommandLineError,
  FAILURE_FOR_CODE,
  PHASE_FOR_STAGE,
  executablePath,
  parseLines,
};
