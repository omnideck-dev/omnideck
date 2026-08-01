const crypto = require('node:crypto');
const fs = require('node:fs');
const fsp = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const { spawn } = require('node:child_process');
const net = require('node:net');
const { pipeline } = require('node:stream/promises');
const { Readable, Transform } = require('node:stream');
const { version: APP_VERSION } = require('../package.json');
const {
  SETUP_REASONS,
  hasLegacySetupFootprint,
  readSetupState,
  writeSetupState,
} = require('./setup-state.cjs');

const DEFAULT_APP_PORT = 2337;
const CONTAINER_NAME = 'omnideck-desktop';
const HOME_VOLUME = 'omnideck-desktop-home';
const STATE_VOLUME = 'omnideck-desktop-state';
const IMAGE = `localhost/omnideck/runtime:${APP_VERSION}`;
const DEVELOPMENT_IMAGE = 'ghcr.io/omnideck-dev/omnideck:main';
const IMAGE_LABEL = 'dev.omnideck.version';
const IMAGE_REF_LABEL = 'dev.omnideck.image-ref';
const IMAGE_MANIFEST = 'image-manifest.json';
const MACHINE_NAME = 'omnideck-runtime';
const PODMAN_VERSION = 'v6.0.2';
const MAX_CAPTURED_OUTPUT = 1_000_000;
// Per-chunk progress callbacks fire thousands of times for a large download or
// hash. Each emit crosses the process boundary and re-renders the setup screen,
// so they are rate limited to something a person can actually perceive.
const PROGRESS_INTERVAL_MS = 100;

const INSTALLERS = {
  'darwin-arm64': {
    filename: 'podman-installer-macos-arm64.pkg',
    sha256: '5a1d97f98f626cdb82dbd9932cf43102d1e9b6621627085fec2dcadf59743930',
  },
  'win32-x64': {
    filename: 'podman-installer-windows-amd64.msi',
    sha256: 'c094059880f033656092f5fb4306457e42aa068ee32137162299817c5f79396f',
  },
  'win32-arm64': {
    filename: 'podman-installer-windows-arm64.msi',
    sha256: '9f6bb7fb83acbfb13cbf67a40f407f098b2f3181a294e3264da260c49437437a',
  },
};

const SETUP_COPY = Object.freeze({
  welcome: Object.freeze({
    title: 'Welcome to omnideck',
    detail: 'A one-time setup will prepare everything omnideck needs on this computer.',
  }),
  preparing: Object.freeze({
    title: 'Preparing your environment',
    detail: 'Setting omnideck up on this computer. This usually takes a few minutes.',
  }),
  // The two screens below name what is being installed. Everywhere else the
  // copy stays in plain language, but this is the moment the user is asked to
  // approve an administrator prompt, and consent needs specifics.
  permission: Object.freeze({
    title: 'Waiting for your permission',
    detail: 'Your computer will ask you to approve installing Podman — the software omnideck uses to run in an isolated space. omnideck never sees or stores your password.',
  }),
  permissionWindows: Object.freeze({
    title: 'Waiting for your permission',
    detail: 'Your computer will ask you to approve turning on Windows Subsystem for Linux, which omnideck needs to run in an isolated space. omnideck never sees or stores your password.',
  }),
  updating: Object.freeze({
    title: 'Preparing your environment',
    detail: 'Bringing omnideck up to date. This usually takes a few minutes.',
  }),
  // Keeps the working title so resuming does not read as a separate screen that
  // has to be dismissed, while still saying that earlier work was kept.
  resuming: Object.freeze({
    title: 'Preparing your environment',
    detail: 'Continuing from where the last attempt stopped. Anything already finished is kept.',
  }),
  ready: Object.freeze({
    title: 'omnideck is ready',
    detail: 'Everything is prepared. Open omnideck whenever you’re ready.',
  }),
});

// The phases setup works through, in order. `activity` is the one line shown
// while a phase runs — it describes what is happening, and deliberately never
// names a component, because someone who just launched omnideck reads
// "downloading omnideck" as the app downloading itself. `label` is the shorter
// form used only in the failure report, where naming a step is the point.
//
// `weight` is the phase's share of the overall bar, taken from how long each
// really takes: the download is most of the wait and the checks barely
// register. Phases that do not apply to this computer are dropped and the
// remaining weights are renormalised, so the bar always ends at full.
const SETUP_PHASES = Object.freeze([
  Object.freeze({
    id: 'software',
    label: 'Computer setup',
    activity: 'Getting your computer ready…',
    weight: 25,
    appliesTo: null,
  }),
  Object.freeze({
    id: 'environment',
    label: 'Secure space',
    activity: 'Preparing a secure space to run in…',
    weight: 15,
    // Linux runs containers directly; there is no separate space to prepare.
    appliesTo: ['darwin', 'win32'],
  }),
  Object.freeze({
    id: 'download',
    label: 'Application files',
    activity: 'Downloading omnideck’s files…',
    weight: 50,
    appliesTo: null,
  }),
  Object.freeze({
    id: 'startup',
    label: 'Final checks',
    activity: 'Almost ready…',
    weight: 10,
    appliesTo: null,
  }),
]);

const PHASE_STATUS_VALUES = Object.freeze({
  pass: 'Done',
  waiting: 'Not started',
});

function phasesFor(platform) {
  return SETUP_PHASES.filter((phase) => !phase.appliesTo || phase.appliesTo.includes(platform));
}

const FAILURE_COPY = Object.freeze({
  support: Object.freeze({
    phase: null,
    result: 'Compatibility issue',
    title: 'This computer isn’t supported yet',
    detail: 'This version of omnideck can’t prepare the required environment on this computer.',
    value: 'Not supported',
    canRetry: false,
    primaryAction: 'supported-systems',
    primaryLabel: 'View supported systems',
  }),
  components: Object.freeze({
    phase: 'software',
    result: 'Component issue',
    title: 'Required software couldn’t be installed',
    detail: 'This can happen when an earlier attempt was interrupted. Trying again usually clears it.',
    value: 'Unavailable',
    canRetry: true,
  }),
  permission: Object.freeze({
    phase: 'software',
    result: 'Permission needed',
    title: 'omnideck needs your permission',
    detail: 'Permission wasn’t granted. Try again and approve the request from your computer.',
    value: 'Permission denied',
    canRetry: true,
  }),
  downloads: Object.freeze({
    phase: 'download',
    result: 'Download issue',
    title: 'The download didn’t finish',
    detail: 'Check your internet connection and try again. Anything already downloaded is kept.',
    value: 'Interrupted',
    canRetry: true,
  }),
  environment: Object.freeze({
    phase: 'environment',
    result: 'Environment issue',
    title: 'The secure workspace isn’t responding',
    detail: 'It was set up but will not answer. Trying again will attempt to repair it.',
    value: 'Not responding',
    canRetry: true,
  }),
  release: Object.freeze({
    phase: null,
    result: 'Installer issue',
    title: 'Download omnideck again',
    detail: 'This installer is incomplete or damaged. Download a fresh copy before trying again.',
    value: 'Invalid',
    canRetry: false,
    primaryAction: 'download',
    primaryLabel: 'Download omnideck',
  }),
  startup: Object.freeze({
    phase: 'startup',
    result: 'Startup issue',
    title: 'omnideck didn’t finish starting',
    detail: 'Everything installed, but omnideck did not answer in time. Trying again runs the startup checks.',
    value: 'Timed out',
    canRetry: true,
  }),
  restart: Object.freeze({
    phase: 'software',
    result: 'Restart required',
    title: 'Restart needed',
    detail: 'Your progress is saved. Restart your computer, then open omnideck and setup continues on its own.',
    value: 'Restart needed',
    canRetry: false,
    primaryAction: 'close',
    primaryLabel: 'Close omnideck',
  }),
  unknown: Object.freeze({
    phase: null,
    result: 'Setup issue',
    title: 'Setup didn’t finish',
    detail: 'Something stopped setup before it completed. Try again, or open the diagnostic log if it keeps happening.',
    value: 'Issue found',
    canRetry: true,
  }),
});

const RESTART_PATTERN = /restart|reboot|3010/i;
const PERMISSION_PATTERN = /permission|not authorized|authentication|cancel|denied/i;

// Guesses for a failure that arrived without a diagnostic of its own. Order
// matters: the first match wins.
const UNTAGGED_FAILURE_PATTERNS = Object.freeze([
  Object.freeze({ kind: 'restart', pattern: RESTART_PATTERN }),
  Object.freeze({ kind: 'permission', pattern: PERMISSION_PATTERN }),
  Object.freeze({ kind: 'downloads', pattern: /network|download|http|resolve|connection|pull/i }),
  Object.freeze({
    kind: 'release',
    pattern: /integrity|does not identify|manifest is invalid|does not match/i,
  }),
]);

// A failure that already knows what it is keeps its own classification.
// Matching prose against a child process transcript would undo that: podman
// output routinely mentions pulls, connections and URLs, so a precisely tagged
// startup or release failure would be rewritten as a download problem, pointing
// the diagnostics panel at the wrong checkpoint and dropping the action that
// actually resolves it.
function classifyFailure(error, transcript = '') {
  const message = String(error?.message || error || '');
  const tagged = error?.failureKind || error?.diagnostic;
  if (!tagged || !FAILURE_COPY[tagged]) {
    return UNTAGGED_FAILURE_PATTERNS.find(({ pattern }) => pattern.test(message))?.kind || 'unknown';
  }
  // A declined authorization prompt and a pending reboot both surface as
  // component failures, and only the wording tells them apart. Elevation steps
  // report the user's decision on the child process output rather than in the
  // exit status, so this one family reads the transcript too.
  if (tagged === 'components') {
    if (RESTART_PATTERN.test(transcript)) return 'restart';
    if (PERMISSION_PATTERN.test(transcript)) return 'permission';
  }
  return tagged;
}

// podman and its rootless port forwarder report an occupied host port in
// several different wordings across platforms and versions.
const PORT_CONFLICT_PATTERN = /address already in use|already allocated|cannot listen on the tcp port|ports are not available/i;

function isPortConflict(error) {
  return PORT_CONFLICT_PATTERN.test(`${error?.message || ''}\n${error?.output || ''}`);
}

function tagError(error, diagnostic, failureKind = diagnostic) {
  const tagged = error instanceof Error ? error : new Error(String(error));
  tagged.diagnostic ||= diagnostic;
  tagged.failureKind ||= failureKind;
  return tagged;
}

function testResourceNames(namespace = process.env.OMNIDECK_DESKTOP_TEST_NAMESPACE) {
  if (!namespace) {
    return {
      container: CONTAINER_NAME,
      homeVolume: HOME_VOLUME,
      stateVolume: STATE_VOLUME,
      machine: MACHINE_NAME,
    };
  }
  if (!/^[a-z0-9][a-z0-9-]{0,31}$/.test(namespace)) {
    throw new Error('OMNIDECK_DESKTOP_TEST_NAMESPACE must contain only lowercase letters, numbers, and hyphens.');
  }
  return {
    container: `${CONTAINER_NAME}-${namespace}`,
    homeVolume: `${HOME_VOLUME}-${namespace}`,
    stateVolume: `${STATE_VOLUME}-${namespace}`,
    machine: `${MACHINE_NAME}-${namespace}`,
  };
}

function splitLines(onLine) {
  let pending = '';
  return (chunk, flush = false) => {
    pending += chunk.toString();
    const lines = pending.split(/\r?\n/);
    pending = lines.pop() || '';
    for (const line of lines) {
      if (line.trim()) onLine(line.trim());
    }
    if (flush && pending.trim()) onLine(pending.trim());
  };
}

function installerUrl(filename) {
  return `https://github.com/podman-container-tools/podman/releases/download/${PODMAN_VERSION}/${filename}`;
}

function knownPodmanDirectories(platform, env) {
  if (platform === 'darwin') return ['/opt/podman/bin', '/usr/local/bin', '/opt/homebrew/bin'];
  if (platform === 'win32') {
    return [
      env.LOCALAPPDATA && path.join(env.LOCALAPPDATA, 'Programs', 'Podman'),
      env.ProgramFiles && path.join(env.ProgramFiles, 'Podman'),
      env.ProgramFiles && path.join(env.ProgramFiles, 'RedHat', 'Podman'),
    ].filter(Boolean);
  }
  return ['/usr/local/bin', '/usr/bin', '/bin'];
}

function parseOsRelease(contents) {
  const values = {};
  for (const line of contents.split(/\r?\n/)) {
    const match = line.match(/^([A-Z_]+)=(.*)$/);
    if (!match) continue;
    values[match[1]] = match[2].trim().replace(/^"(.*)"$/, '$1');
  }
  return values;
}

function linuxInstallCommands(distroId, executable) {
  const apt = ['ubuntu', 'debian', 'linuxmint', 'pop'];
  if (apt.includes(distroId)) {
    return [
      [executable('apt-get'), ['update']],
      [executable('apt-get'), ['install', '-y', 'podman']],
    ];
  }
  if (['fedora', 'rhel', 'centos', 'rocky', 'almalinux'].includes(distroId)) {
    return [[executable('dnf'), ['install', '-y', 'podman']]];
  }
  if (['arch', 'manjaro'].includes(distroId)) {
    return [[executable('pacman'), ['-S', '--needed', '--noconfirm', 'podman']]];
  }
  if (['opensuse', 'opensuse-leap', 'opensuse-tumbleweed', 'sles'].includes(distroId)) {
    return [[executable('zypper'), ['--non-interactive', 'install', 'podman']]];
  }
  if (distroId === 'alpine') {
    return [[executable('apk'), ['add', 'podman']]];
  }
  return [];
}

async function reserveAvailablePort(preferredPort = DEFAULT_APP_PORT) {
  const listen = (port) => new Promise((resolve, reject) => {
    const server = net.createServer();
    server.unref();
    server.once('error', reject);
    server.listen({ host: '127.0.0.1', port, exclusive: true }, () => {
      const address = server.address();
      server.close(() => resolve(address.port));
    });
  });

  try {
    return await listen(preferredPort);
  } catch (error) {
    if (error.code !== 'EADDRINUSE') throw error;
    return listen(0);
  }
}

async function sha256File(filename, onProgress = () => {}) {
  const { size } = await fsp.stat(filename);
  const hash = crypto.createHash('sha256');
  let processed = 0;
  for await (const chunk of fs.createReadStream(filename)) {
    hash.update(chunk);
    processed += chunk.length;
    onProgress(size > 0 ? processed / size : 1);
  }
  return hash.digest('hex');
}

async function replaceDownloadedFile(source, destination) {
  // fs.rename() does not replace an existing destination reliably on Windows.
  // A failed setup may leave the previous verified download behind.
  await fsp.rm(destination, { force: true });
  await fsp.rename(source, destination);
}

class OmniDeckRuntime {
  constructor({
    userDataPath,
    resourcesPath = path.join(__dirname, '..', 'build'),
    allowDevelopmentImagePull = false,
    onState,
  }) {
    this.userDataPath = userDataPath;
    this.resourcesPath = resourcesPath;
    this.allowDevelopmentImagePull = allowDevelopmentImagePull;
    this.onState = onState;
    this.runtimeRoot = path.join(userDataPath, 'runtime');
    this.downloadRoot = path.join(userDataPath, 'downloads');
    this.logPath = path.join(userDataPath, 'logs', 'desktop.log');
    const names = testResourceNames();
    this.containerName = names.container;
    this.homeVolume = names.homeVolume;
    this.stateVolume = names.stateVolume;
    this.machineName = names.machine;
    this.podmanPath = null;
    this.appPort = null;
    this.currentState = null;
    this.currentEnvironment = null;
    // Set only when a specific release has been chosen to install. While it is
    // set, it is what setup installs instead of the release this copy shipped
    // with.
    this.updateTarget = null;
    this.setupReason = 'first-run';
    this.lastProgressEmit = 0;
    this.phases = phasesFor(process.platform);
    this.phaseIndex = -1;
    this.phaseFraction = 0;
  }

  get appUrl() {
    if (!this.appPort) throw new Error('The omnideck runtime has not been prepared.');
    return `http://127.0.0.1:${this.appPort}`;
  }

  // The version currently installed on this computer, or null if nothing is.
  // Installations made before the version was recorded fall back to the version
  // of the application that performed them, which is the one it shipped with.
  async installedVersion() {
    const state = await readSetupState(this.userDataPath);
    if (!state || state.status !== 'complete') return null;
    return state.imageVersion || state.appVersion;
  }

  emit(stage, title, detail, options = {}) {
    this.currentState = {
      stage,
      title,
      detail,
      progress: options.progress ?? null,
      indeterminate: options.indeterminate ?? false,
      canStart: options.canStart ?? false,
      canRetry: options.canRetry ?? false,
      canOpen: options.canOpen ?? false,
      activity: options.activity ?? null,
      primaryAction: options.primaryAction ?? null,
      primaryLabel: options.primaryLabel ?? null,
      secondaryAction: options.secondaryAction ?? null,
      secondaryLabel: options.secondaryLabel ?? null,
      setupReason: options.setupReason ?? this.setupReason,
      diagnostics: options.diagnostics ?? null,
      diagnosticResult: options.diagnosticResult ?? null,
      technical: options.technical ?? null,
    };
    this.onState(this.currentState);
  }

  emitCopy(stage, copy, options = {}) {
    this.emit(stage, SETUP_COPY[copy].title, SETUP_COPY[copy].detail, options);
  }

  // A screen shown part-way through setup. It keeps the activity line and the
  // overall bar so neither blinks out between steps.
  emitStep(stage, copy, options = {}) {
    this.emitCopy(stage, copy, {
      activity: this.currentActivity(),
      progress: this.overallProgress(),
      ...options,
    });
  }

  workingCopy() {
    if (this.setupReason === 'update') return 'updating';
    if (this.setupReason === 'resume') return 'resuming';
    return 'preparing';
  }

  currentActivity() {
    return this.phases[this.phaseIndex]?.activity ?? null;
  }

  // How far through the whole of setup we are: every finished phase's weight,
  // plus how far into the current one. Renormalised over the phases that apply
  // to this computer so the bar always reaches full.
  overallProgress() {
    if (this.phaseIndex < 0) return null;
    const total = this.phases.reduce((sum, phase) => sum + phase.weight, 0);
    if (!total) return null;
    const done = this.phases
      .slice(0, this.phaseIndex)
      .reduce((sum, phase) => sum + phase.weight, 0);
    const current = this.phases[this.phaseIndex].weight * this.phaseFraction;
    return Math.max(0, Math.min(1, (done + current) / total));
  }

  // Moves to a phase. Everything before it counts as finished, which also keeps
  // the bar honest when a phase is skipped because its work was already done.
  beginPhase(id) {
    const index = this.phases.findIndex((phase) => phase.id === id);
    if (index < 0) return;
    this.phaseIndex = index;
    this.phaseFraction = 0;
    this.emitWorking();
  }

  emitWorking() {
    this.lastProgressEmit = Date.now();
    this.emitCopy('preparing', this.workingCopy(), {
      activity: this.currentActivity(),
      progress: this.overallProgress(),
      indeterminate: this.phaseIndex < 0,
    });
  }

  // Progress within the current phase, from callbacks that fire per chunk or
  // per output line. Emits are rate limited because the state crosses the
  // process boundary and re-renders the whole setup screen.
  emitProgressUpdate(fraction = null) {
    if (Number.isFinite(fraction)) {
      this.phaseFraction = Math.max(0, Math.min(1, fraction));
    }
    const now = Date.now();
    if (now - this.lastProgressEmit < PROGRESS_INTERVAL_MS) return;
    this.lastProgressEmit = now;
    this.emitCopy('preparing', this.workingCopy(), {
      activity: this.currentActivity(),
      progress: this.overallProgress(),
      indeterminate: this.phaseIndex < 0,
    });
  }

  // The rows shown on the failure screen. Everything before the phase that
  // failed is finished, that phase carries the problem, and the rest never
  // started. When a failure belongs to no phase — an unsupported computer, a
  // damaged download of the app itself — nothing is flagged, because no step
  // was in progress when it happened.
  failureSnapshot(failedPhaseId, failedValue) {
    const failedIndex = this.phases.findIndex((phase) => phase.id === failedPhaseId);
    const reached = failedIndex >= 0 ? failedIndex : this.phaseIndex;
    return this.phases.map((phase, index) => {
      if (index === failedIndex) {
        return { id: phase.id, label: phase.label, status: 'issue', value: failedValue };
      }
      const status = index < reached ? 'pass' : 'waiting';
      return { id: phase.id, label: phase.label, status, value: PHASE_STATUS_VALUES[status] };
    });
  }

  async desiredEnvironment() {
    try {
      // A chosen update outranks the release this copy shipped with. It is
      // already an immutable reference, so there is nothing left to resolve.
      if (this.updateTarget) {
        this.currentEnvironment = {
          imageRef: this.updateTarget.imageRef,
          sourceImage: this.updateTarget.imageRef,
          version: this.updateTarget.version,
        };
        return this.currentEnvironment;
      }
      const releaseImage = await this.releaseImage();
      if (releaseImage) {
        this.currentEnvironment = {
          imageRef: releaseImage.imageRef,
          sourceImage: releaseImage.imageRef,
          version: APP_VERSION,
        };
      } else if (this.allowDevelopmentImagePull) {
        this.currentEnvironment = {
          imageRef: `${DEVELOPMENT_IMAGE}#${APP_VERSION}`,
          sourceImage: DEVELOPMENT_IMAGE,
          version: APP_VERSION,
        };
      } else {
        throw new Error('This omnideck installer does not identify its application image.');
      }
      return this.currentEnvironment;
    } catch (error) {
      throw tagError(error, 'release');
    }
  }

  async saveSetupState(status, reason = this.setupReason) {
    if (!this.currentEnvironment) throw new Error('The target environment is not known.');
    return writeSetupState(this.userDataPath, {
      status,
      reason,
      appVersion: APP_VERSION,
      imageVersion: this.currentEnvironment.version ?? APP_VERSION,
      imageRef: this.currentEnvironment.imageRef,
    });
  }

  async prepare() {
    await Promise.all([
      fsp.mkdir(this.runtimeRoot, { recursive: true }),
      fsp.mkdir(this.downloadRoot, { recursive: true }),
      fsp.mkdir(path.dirname(this.logPath), { recursive: true }),
      fsp.mkdir(path.join(this.runtimeRoot, 'config'), { recursive: true }),
      fsp.mkdir(path.join(this.runtimeRoot, 'data'), { recursive: true }),
      fsp.mkdir(path.join(this.runtimeRoot, 'cache'), { recursive: true }),
      fsp.mkdir(path.join(this.runtimeRoot, 'auth'), { recursive: true }),
    ]);
    const authPath = path.join(this.runtimeRoot, 'auth', 'auth.json');
    try {
      await fsp.access(authPath);
    } catch {
      await fsp.writeFile(authPath, '{}\n', { mode: 0o600 });
    }
    try {
      const savedPort = Number.parseInt(
        await fsp.readFile(path.join(this.runtimeRoot, 'app-port'), 'utf8'),
        10,
      );
      if (savedPort < 1 || savedPort > 65535) throw new Error('Invalid saved port.');
      this.appPort = savedPort;
    } catch {
      await this.reserveNewAppPort();
    }
  }

  // The host port is a local detail that nothing else is keyed on, so a port
  // another program claimed while omnideck was closed can simply be exchanged
  // for a free one. The container carries the old mapping and has to be rebuilt
  // against the new port.
  async reserveNewAppPort() {
    const previous = this.appPort;
    let port = await reserveAvailablePort();
    // The port that just failed must not come back, even when nothing appears
    // to be holding it by the time it is probed again.
    if (port === previous) port = await reserveAvailablePort(0);
    this.appPort = port;
    await fsp.writeFile(
      path.join(this.runtimeRoot, 'app-port'),
      `${port}\n`,
      { mode: 0o600 },
    );
    return port;
  }

  runtimeEnv() {
    const directories = knownPodmanDirectories(process.platform, process.env);
    const currentPath = process.env.PATH || '';
    return {
      ...process.env,
      PATH: [...directories, currentPath].join(path.delimiter),
      XDG_CACHE_HOME: path.join(this.runtimeRoot, 'cache'),
      XDG_CONFIG_HOME: path.join(this.runtimeRoot, 'config'),
      XDG_DATA_HOME: path.join(this.runtimeRoot, 'data'),
      REGISTRY_AUTH_FILE: path.join(this.runtimeRoot, 'auth', 'auth.json'),
    };
  }

  async appendLog(line) {
    const timestamp = new Date().toISOString();
    await fsp.appendFile(this.logPath, `${timestamp} ${line}\n`).catch(() => {});
  }

  async findExecutable(name, env = this.runtimeEnv()) {
    const extension = process.platform === 'win32' && !name.endsWith('.exe') ? '.exe' : '';
    const filename = `${name}${extension}`;
    const candidates = [];
    for (const directory of (env.PATH || '').split(path.delimiter)) {
      if (directory) candidates.push(path.join(directory, filename));
    }
    // PATH order decides which match wins, so every candidate is probed at once
    // and the earliest one is taken rather than the first to finish. A long
    // Windows PATH made the sequential walk noticeable.
    const found = await Promise.all(candidates.map(
      (candidate) => fsp.access(candidate, fs.constants.X_OK).then(() => candidate, () => null),
    ));
    return found.find(Boolean) || null;
  }

  async run(executable, args, options = {}) {
    const env = options.env || this.runtimeEnv();
    const accepted = options.acceptExitCodes || [0];
    const label = options.label || path.basename(executable);
    await this.appendLog(`$ ${label} ${args.join(' ')}`);

    return new Promise((resolve, reject) => {
      const child = spawn(executable, args, {
        env,
        windowsHide: true,
        shell: false,
      });
      // stdout is kept separately because callers parse it as JSON. Podman
      // writes warnings to stderr on many ordinary invocations, and folding
      // those into the same buffer corrupts the payload. The interleaved
      // transcript is still what gets logged and attached to failures.
      let stdoutText = '';
      let transcript = '';
      const capture = (isStdout) => (line) => {
        if (isStdout) stdoutText = `${stdoutText}${line}\n`.slice(-MAX_CAPTURED_OUTPUT);
        transcript = `${transcript}${line}\n`.slice(-MAX_CAPTURED_OUTPUT);
        void this.appendLog(`[${label}] ${line}`);
        options.onLine?.(line);
      };
      const stdout = splitLines(capture(true));
      const stderr = splitLines(capture(false));
      child.stdout?.on('data', (chunk) => stdout(chunk));
      child.stderr?.on('data', (chunk) => stderr(chunk));
      child.on('error', (error) => reject(error));
      child.on('close', (code) => {
        stdout('', true);
        stderr('', true);
        const output = transcript.trim();
        if (options.acceptAnyExitCode || accepted.includes(code)) {
          resolve({ code, output, stdout: stdoutText.trim() });
          return;
        }
        const error = new Error(`${label} exited with code ${code}`);
        error.code = code;
        error.output = output;
        reject(error);
      });
    });
  }

  async startExisting() {
    const setupState = await readSetupState(this.userDataPath);
    const legacyFootprint = !setupState && await hasLegacySetupFootprint(this.userDataPath);

    if (!setupState && !legacyFootprint) {
      this.setupReason = 'first-run';
      this.emitCopy('welcome', 'welcome', { canStart: true });
      return { action: 'welcome', reason: this.setupReason };
    }

    if (setupState?.status === 'in-progress') {
      this.setupReason = setupState.reason === 'update' ? 'update' : 'resume';
      this.emitWorking();
      return { action: 'setup', reason: this.setupReason };
    }

    await this.prepare();
    let updateAvailable = false;
    try {
      const desired = await this.desiredEnvironment();
      updateAvailable = setupState?.status === 'complete'
        && setupState.imageRef !== desired.imageRef;
      if (updateAvailable) {
        // Health is judged against what is actually installed, so a deferred
        // update can still open the version already on this computer.
        this.currentEnvironment = {
          imageRef: setupState.imageRef,
          sourceImage: setupState.imageRef,
        };
      }

      this.podmanPath = await this.findExecutable('podman');
      if (!this.podmanPath) {
        if (!setupState) {
          this.setupReason = 'first-run';
          this.emitCopy('welcome', 'welcome', { canStart: true });
          return { action: 'welcome', reason: this.setupReason };
        }
        throw tagError(
          new Error('The required system component is unavailable.'),
          'components',
        );
      }

      // Container state answers the runtime question too: podman cannot report
      // a container without being reachable. The separate version probe only
      // runs when nothing came back, to tell an unreachable runtime apart from
      // a missing container. Every podman call is a round trip to the virtual
      // machine on macOS and Windows, and this one sat on every launch.
      const info = await this.containerInfo();
      if (!info) {
        await this.run(this.podmanPath, ['info', '--format', '{{.Version.Version}}'], {
          label: 'runtime check',
        }).catch((error) => {
          throw tagError(error, 'environment');
        });
      }

      if (!this.isCurrentContainer(info)) {
        // Nothing working to fall back to, so there is no choice worth offering.
        if (updateAvailable) {
          this.setupReason = 'update';
          this.emitWorking();
          return { action: 'setup', reason: this.setupReason };
        }
        if (!setupState && info) {
          this.setupReason = 'update';
          this.emitWorking();
          return { action: 'setup', reason: this.setupReason };
        }
        if (!setupState) {
          this.setupReason = 'first-run';
          this.emitCopy('welcome', 'welcome', { canStart: true });
          return { action: 'welcome', reason: this.setupReason };
        }
        throw tagError(
          new Error('The prepared omnideck environment is unavailable.'),
          'startup',
        );
      }

      const started = await this.startCurrentContainer(info)
        .catch((error) => {
          throw tagError(error, 'startup');
        });
      if (!started) {
        // The port moved, so the container has to be rebuilt around the new
        // one. Setup already knows how to do that.
        this.setupReason = 'repair';
        this.emitWorking();
        return { action: 'setup', reason: this.setupReason };
      }
      await this.waitForApp({ silent: true });
      this.setupReason = setupState?.reason || 'first-run';
      await this.saveSetupState('complete', this.setupReason);
      // A newer image is deliberately not acted on here. Opening the app must
      // never be interrupted, by a prompt or by an install, so a healthy
      // installation opens as it is and the newer image waits.
      return { action: 'open', reason: this.setupReason };
    } catch (error) {
      // An available update supersedes a broken installation: setup reinstalls
      // whatever is missing and applies the update in one pass, which is more
      // use to someone than being sent to diagnostics.
      if (updateAvailable) {
        this.setupReason = 'update';
        this.emitWorking();
        return { action: 'setup', reason: this.setupReason };
      }
      this.reportFailure(error);
      return { action: 'doctor', reason: setupState?.reason || 'repair' };
    }
  }

  async setup(reason = this.setupReason) {
    await this.prepare();
    this.setupReason = SETUP_REASONS.has(reason) ? reason : 'resume';

    const previousState = await readSetupState(this.userDataPath);
    const desired = await this.desiredEnvironment();
    if (
      previousState
      && previousState.imageRef !== desired.imageRef
      && previousState.status === 'complete'
    ) {
      this.setupReason = 'update';
    }
    await this.saveSetupState('in-progress', this.setupReason);
    this.beginPhase('software');

    if (process.platform === 'win32') {
      await this.ensureWindowsPrerequisites().catch((error) => {
        throw tagError(error, 'support');
      });
    }
    this.podmanPath = await this.findExecutable('podman');
    if (!this.podmanPath) {
      await this.installRuntime().catch((error) => {
        if (error.diagnostic) throw error;
        throw tagError(error, 'components');
      });
      this.podmanPath = await this.findExecutable('podman');
      if (!this.podmanPath) {
        throw tagError(
          new Error('The required system component was installed but could not be opened.'),
          'components',
        );
      }
    }

    this.beginPhase('environment');
    await this.ensureRuntimeReady().catch((error) => {
      throw tagError(error, 'environment');
    });
    this.beginPhase('download');
    await this.ensureContainer().catch((error) => {
      throw error.diagnostic ? error : tagError(error, 'startup');
    });
    this.beginPhase('startup');
    await this.waitForApp().catch((error) => {
      throw tagError(error, 'startup');
    });
    await this.saveSetupState('complete', this.setupReason);
    this.emitCopy('ready', 'ready', { progress: 1, canOpen: true });
  }

  async ensureWindowsPrerequisites() {
    const systemRoot = process.env.SystemRoot || process.env.WINDIR || 'C:\\Windows';
    const systemWsl = path.join(systemRoot, 'System32', 'wsl.exe');
    const wsl = await this.findExecutable('wsl.exe', process.env)
      || (fs.existsSync(systemWsl) ? systemWsl : null);
    if (!wsl) {
      throw tagError(
        new Error('omnideck requires Windows 11 with WSL 2 support.'),
        'support',
      );
    }

    const status = await this.run(wsl, ['--status'], {
      env: process.env,
      label: 'Windows workspace check',
      acceptAnyExitCode: true,
    });
    if (status.code === 0) return;

    const powershell = await this.findExecutable('powershell.exe', process.env);
    if (!powershell) {
      throw tagError(
        new Error('Windows could not prepare WSL 2 for omnideck.'),
        'components',
      );
    }
    this.emitStep('preparing', 'permissionWindows', { indeterminate: true });
    const script = [
      "$process = Start-Process -FilePath $env:OMNIDECK_WSL_PATH -ArgumentList @('--install', '--no-distribution') -Verb RunAs -Wait -PassThru",
      'exit $process.ExitCode',
    ].join('; ');
    // RunAs raises the elevation prompt, so a non-zero exit that is not the
    // reboot-pending code means the prompt was dismissed.
    await this.run(
      powershell,
      ['-NoLogo', '-NoProfile', '-NonInteractive', '-Command', script],
      {
        env: { ...process.env, OMNIDECK_WSL_PATH: wsl },
        label: 'Windows workspace setup',
        acceptExitCodes: [0, 3010],
      },
    ).catch((error) => {
      throw tagError(error, 'components', 'permission');
    });

    const updatedStatus = await this.run(wsl, ['--status'], {
      env: process.env,
      label: 'Windows workspace check',
      acceptAnyExitCode: true,
    });
    if (updatedStatus.code !== 0) {
      throw tagError(
        new Error('Windows restart required after enabling WSL 2.'),
        'components',
        'restart',
      );
    }
  }

  async installRuntime() {
    if (process.platform === 'linux') {
      await this.installRuntimeOnLinux();
      return;
    }

    const key = `${process.platform}-${process.arch}`;
    const installer = INSTALLERS[key];
    if (!installer) {
      throw tagError(
        new Error('This release does not include the required component for this computer architecture.'),
        'support',
      );
    }
    const destination = path.join(this.downloadRoot, installer.filename);
    await this.download(installerUrl(installer.filename), destination, installer.sha256);

    if (process.platform === 'darwin') {
      await this.run('/usr/sbin/pkgutil', ['--check-signature', destination], { label: 'verify installer' });
      const script = [
        'on run argv',
        'do shell script "/usr/sbin/installer -pkg " & quoted form of item 1 of argv & " -target /" with administrator privileges',
        'end run',
      ].join('\n');
      this.emitStep('preparing', 'permission', { indeterminate: true });
      // The only interactive step is the system authorization prompt, so a
      // failure here means it was declined or authentication did not succeed.
      await this.run('/usr/bin/osascript', ['-e', script, destination], { label: 'system installer' })
        .catch((error) => {
          throw tagError(error, 'components', 'permission');
        });
      return;
    }

    await this.verifyWindowsInstaller(destination);
    this.emitStep('preparing', 'permission', { indeterminate: true });
    await this.run(
      'msiexec.exe',
      ['/i', destination, '/passive', '/norestart', 'ALLUSERS=2', 'MSIINSTALLPERUSER=1'],
      { label: 'system installer', acceptExitCodes: [0, 3010] },
    );
  }

  async installRuntimeOnLinux() {
    const pkexec = await this.findExecutable('pkexec', process.env);
    if (!pkexec) {
      throw tagError(
        new Error('This Linux desktop does not provide a graphical system-permission prompt.'),
        'components',
      );
    }
    const release = parseOsRelease(await fsp.readFile('/etc/os-release', 'utf8').catch(() => ''));
    const executable = (name) => {
      for (const directory of ['/usr/bin', '/usr/sbin', '/bin', '/sbin']) {
        const candidate = path.join(directory, name);
        if (fs.existsSync(candidate)) return candidate;
      }
      return name;
    };
    const commands = linuxInstallCommands(release.ID || '', executable);
    if (commands.length === 0) {
      throw tagError(
        new Error('Automatic setup is not available for this Linux distribution yet.'),
        'support',
      );
    }
    for (const [command, args] of commands) {
      this.emitStep('preparing', 'permission', { indeterminate: true });
      // pkexec exits non-zero both when the prompt is dismissed and when the
      // install itself fails, but a dismissed prompt is by far the common case
      // and its guidance still points at the right next step.
      await this.run(pkexec, [command, ...args], {
        env: process.env,
        label: 'system installer',
      }).catch((error) => {
        throw tagError(error, 'components', 'permission');
      });
    }
  }

  async verifyWindowsInstaller(destination) {
    const powershell = await this.findExecutable('powershell.exe', process.env);
    if (!powershell) {
      throw new Error('Windows could not verify the downloaded system component.');
    }
    const script = [
      '$signature = Get-AuthenticodeSignature -LiteralPath $env:OMNIDECK_INSTALLER_PATH',
      'if ($signature.Status -ne "Valid") { exit 1 }',
    ].join('; ');
    await this.run(
      powershell,
      ['-NoLogo', '-NoProfile', '-NonInteractive', '-Command', script],
      {
        env: { ...process.env, OMNIDECK_INSTALLER_PATH: destination },
        label: 'verify installer',
      },
    );
  }

  async download(url, destination, expectedSha256) {
    const partial = `${destination}.partial`;
    try {
      const cachedDigest = await sha256File(
        destination,
        (fraction) => this.emitProgressUpdate(fraction),
      ).catch(() => null);
      if (cachedDigest === expectedSha256) return;
      if (cachedDigest) await fsp.rm(destination, { force: true });

      const response = await fetch(url, { redirect: 'follow' });
      if (!response.ok || !response.body) {
        throw new Error(`Download failed with HTTP ${response.status}.`);
      }
      const declaredLength = Number.parseInt(response.headers.get('content-length') || '', 10);
      const totalBytes = Number.isFinite(declaredLength) && declaredLength > 0
        ? declaredLength
        : null;
      const hash = crypto.createHash('sha256');
      let receivedBytes = 0;
      const progress = new Transform({
        transform: (chunk, _encoding, callback) => {
          hash.update(chunk);
          receivedBytes += chunk.length;
          this.emitProgressUpdate(totalBytes ? receivedBytes / totalBytes : null);
          callback(null, chunk);
        },
      });
      await pipeline(Readable.fromWeb(response.body), progress, fs.createWriteStream(partial));
      const digest = hash.digest('hex');
      if (digest !== expectedSha256) {
        throw new Error('The downloaded system component did not pass its security check.');
      }
      await replaceDownloadedFile(partial, destination);
    } catch (error) {
      await fsp.rm(partial, { force: true });
      throw tagError(error, 'downloads');
    }
  }

  async ensureRuntimeReady() {
    try {
      await this.run(this.podmanPath, ['info', '--format', '{{.Version.Version}}'], {
        label: 'runtime check',
      });
      return;
    } catch (error) {
      if (process.platform === 'linux') throw error;
    }

    this.emitWorking();
    const inspection = await this.run(
      this.podmanPath,
      ['machine', 'inspect', this.machineName],
      { label: 'workspace check', acceptExitCodes: [0, 125] },
    );
    if (inspection.code === 0) {
      await this.run(this.podmanPath, ['machine', 'start', this.machineName], {
        label: 'start workspace',
        onLine: () => this.emitProgressUpdate(),
      });
    } else {
      const hostMemoryGiB = os.totalmem() / (1024 ** 3);
      const memoryMiB = hostMemoryGiB >= 16 ? '6144' : '4096';
      await this.run(
        this.podmanPath,
        [
          'machine', 'init',
          '--cpus', String(Math.max(2, Math.min(4, os.cpus().length))),
          '--memory', memoryMiB,
          '--disk-size', '60',
          '--now',
          '--update-connection=true',
          this.machineName,
        ],
        {
          label: 'prepare workspace',
          onLine: () => this.emitProgressUpdate(),
        },
      );
    }
    await this.run(this.podmanPath, ['info', '--format', '{{.Version.Version}}'], {
      label: 'runtime check',
    });
  }

  async containerInfo() {
    const result = await this.run(
      this.podmanPath,
      ['container', 'inspect', this.containerName],
      { label: 'app check', acceptExitCodes: [0, 125] },
    );
    if (result.code !== 0) return null;
    try {
      const inspection = JSON.parse(result.stdout);
      return Array.isArray(inspection) ? inspection[0] || null : inspection;
    } catch {
      throw new Error('omnideck could not read the existing environment state.');
    }
  }

  isCurrentContainer(info) {
    if (!info) return false;
    const environmentLabel = info.Config?.Labels?.[IMAGE_REF_LABEL];
    if (environmentLabel && this.currentEnvironment) {
      return environmentLabel === this.currentEnvironment.imageRef;
    }
    return info.Config?.Labels?.[IMAGE_LABEL] === APP_VERSION
      && info.Config?.Image === IMAGE;
  }

  // Starts a container that is already known to be the current one. Returns
  // false when starting cannot succeed and the container has to be rebuilt.
  async startCurrentContainer(info) {
    if (info.State?.Status === 'running') return true;
    try {
      await this.run(this.podmanPath, ['start', this.containerName], { label: 'start app' });
      return true;
    } catch (error) {
      if (!isPortConflict(error)) throw error;
      await this.reserveNewAppPort();
      return false;
    }
  }

  async startContainer() {
    const info = await this.containerInfo();
    if (!this.isCurrentContainer(info)) return false;
    return this.startCurrentContainer(info);
  }

  async releaseImage() {
    const roots = [
      path.join(this.resourcesPath, 'runtime'),
      path.join(__dirname, '..', 'build', 'runtime'),
    ];
    for (const root of [...new Set(roots)]) {
      const manifestPath = path.join(root, IMAGE_MANIFEST);
      let manifest;
      try {
        manifest = JSON.parse(await fsp.readFile(manifestPath, 'utf8'));
      } catch (error) {
        if (error.code === 'ENOENT') continue;
        throw new Error('The omnideck runtime image manifest is invalid.');
      }
      if (
        manifest.schemaVersion !== 2
        || manifest.appVersion !== APP_VERSION
        || !/^ghcr\.io\/[a-z0-9._/-]+@sha256:[a-f0-9]{64}$/.test(manifest.imageRef || '')
      ) {
        throw new Error('The omnideck runtime image does not match this application release.');
      }
      return manifest;
    }
    return null;
  }

  async imageExists(imageRef = IMAGE) {
    const result = await this.run(
      this.podmanPath,
      ['image', 'exists', imageRef],
      { label: 'application image check', acceptExitCodes: [0, 1, 125] },
    );
    return result.code === 0;
  }

  async ensureImage() {
    const environment = this.currentEnvironment || await this.desiredEnvironment();
    if (environment.sourceImage === DEVELOPMENT_IMAGE) {
      if (await this.imageExists(DEVELOPMENT_IMAGE)) {
        await this.run(this.podmanPath, ['tag', DEVELOPMENT_IMAGE, IMAGE], {
          label: 'prepare development app',
        });
        return;
      }
      this.emitWorking();
      await this.run(
        this.podmanPath,
        ['pull', DEVELOPMENT_IMAGE],
        {
          label: 'download development app',
          onLine: () => this.emitProgressUpdate(),
        },
      ).catch((error) => {
        throw tagError(error, 'downloads');
      });
      await this.run(this.podmanPath, ['tag', DEVELOPMENT_IMAGE, IMAGE], {
        label: 'prepare development app',
      });
      return;
    }

    if (!await this.imageExists(environment.sourceImage)) {
      this.emitWorking();
      await this.run(
        this.podmanPath,
        ['pull', environment.sourceImage],
        {
          label: 'download application',
          onLine: () => this.emitProgressUpdate(),
        },
      ).catch((error) => {
        throw tagError(error, 'downloads');
      });
    }
    if (!await this.imageExists(environment.sourceImage)) {
      throw tagError(
        new Error('The pinned omnideck image could not be downloaded.'),
        'downloads',
      );
    }
    await this.run(this.podmanPath, ['tag', environment.sourceImage, IMAGE], {
      label: 'prepare application',
    });
  }

  async ensureContainer() {
    if (await this.startContainer()) return;
    await this.ensureImage();

    const existing = await this.containerInfo();
    if (existing) {
      this.emitWorking();
      await this.run(this.podmanPath, ['rm', '--force', this.containerName], {
        label: 'replace app',
      });
    }

    // volume exists reports through its exit status, so it avoids the second
    // call that inspecting-then-creating needs.
    for (const volume of [this.homeVolume, this.stateVolume]) {
      const present = await this.run(
        this.podmanPath,
        ['volume', 'exists', volume],
        { label: 'storage check', acceptExitCodes: [0, 1, 125] },
      );
      if (present.code !== 0) {
        await this.run(this.podmanPath, ['volume', 'create', volume], { label: 'prepare storage' });
      }
    }

    try {
      await this.runAppContainer();
    } catch (error) {
      if (!isPortConflict(error)) throw error;
      // Another program took the port between reserving it and binding it. A
      // run that fails on the port can still leave the container behind, so it
      // is cleared before rebuilding against a free one.
      await this.reserveNewAppPort();
      await this.run(this.podmanPath, ['rm', '--force', this.containerName], {
        label: 'replace app',
        acceptAnyExitCode: true,
      });
      await this.runAppContainer();
    }
  }

  async runAppContainer() {
    return this.run(
      this.podmanPath,
      [
        'run', '-d',
        '--name', this.containerName,
        '--restart', 'always',
        '--log-driver', 'k8s-file',
        '--log-opt', 'max-size=150mb',
        '--label', `${IMAGE_LABEL}=${APP_VERSION}`,
        '--label', `${IMAGE_REF_LABEL}=${this.currentEnvironment?.imageRef || IMAGE}`,
        '--memory', '2g',
        '--shm-size', '1024m',
        '-p', `127.0.0.1:${this.appPort}:8080`,
        '-v', `${this.homeVolume}:/home/omnideck`,
        '-v', `${this.stateVolume}:/var/lib/omnideck`,
        '-e', 'ENABLE_DESKTOP=false',
        '-e', 'OLLAMA_HOST=http://host.containers.internal:11434',
        '-e', 'PORT=8080',
        IMAGE,
      ],
      { label: 'start app' },
    );
  }

  async waitForApp({ silent = false } = {}) {
    const deadline = Date.now() + 120_000;
    let delay = 150;
    while (Date.now() < deadline) {
      try {
        const response = await fetch(this.appUrl, { signal: AbortSignal.timeout(3_000) });
        if (response.ok) return;
      } catch {
        // Startup is still in progress.
      }
      await new Promise((resolve) => setTimeout(resolve, delay));
      // An already-warm container answers almost at once, so the first polls
      // are quick; the interval then eases off for a slow first run.
      delay = Math.min(1_000, Math.round(delay * 1.6));
    }
    throw tagError(new Error('omnideck took too long to start.'), 'startup');
  }

  reportFailure(error) {
    const transcript = String(error?.output || '');
    const raw = `${error?.message || error}\n${transcript}`.trim();
    void this.appendLog(`[failure] ${raw}`);
    const failureKind = classifyFailure(error, transcript);
    const copy = FAILURE_COPY[failureKind] || FAILURE_COPY.unknown;
    this.emit('error', copy.title, copy.detail, {
      canRetry: copy.canRetry ?? false,
      primaryAction: copy.primaryAction ?? null,
      primaryLabel: copy.primaryLabel ?? null,
      secondaryAction: 'show-logs',
      secondaryLabel: 'Show diagnostic log',
      diagnostics: this.failureSnapshot(copy.phase, copy.value),
      diagnosticResult: copy.result,
      technical: raw.slice(0, 4_000),
    });
  }
}

module.exports = {
  APP_VERSION,
  SETUP_PHASES,
  FAILURE_COPY,
  IMAGE,
  IMAGE_REF_LABEL,
  OmniDeckRuntime,
  SETUP_COPY,
  installerUrl,
  linuxInstallCommands,
  parseOsRelease,
  replaceDownloadedFile,
  reserveAvailablePort,
  sha256File,
  testResourceNames,
};
