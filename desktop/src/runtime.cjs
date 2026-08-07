const fsp = require('node:fs/promises');
const path = require('node:path');
const { spawn } = require('node:child_process');
const net = require('node:net');
const { version: APP_VERSION } = require('../package.json');
const {
  SETUP_REASONS,
  readSetupState,
  writeSetupState,
} = require('./setup-state.cjs');
const { compareVersions, isReleaseVersion, parseVersion } = require('./updates.cjs');
const { OmnideckCliBackend } = require('./cli-backend.cjs');
const { knownRuntimeDirectories } = require('./runtime-env.cjs');

// One above the port the command line tool installs on by default, so a machine
// running both does not have the two of them fighting over the same one. A port
// is only ever chosen once, when omnideck is installed, and kept from then on.
const DEFAULT_APP_PORT = 2338;
// The port the command line tool installs on by default, and the one this
// application used before it moved off. An installation made then is still on
// it, which is the one arrangement where both cannot run at once, so it is
// exchanged for a free one the next time omnideck opens.
const LEGACY_APP_PORT = 2337;
// The port omnideck listens on inside its container. Only the host side of the
// mapping ever changes.
const CONTAINER_NAME = 'omnideck-desktop';
const HOME_VOLUME = 'omnideck-desktop-home';
const STATE_VOLUME = 'omnideck-desktop-state';
const DEVELOPMENT_IMAGE = 'ghcr.io/omnideck-dev/omnideck:main';
const IMAGE_MANIFEST = 'image-manifest.json';
const MACHINE_NAME = 'omnideck-runtime';
const MAX_CAPTURED_OUTPUT = 1_000_000;
// Per-chunk progress callbacks fire thousands of times for a large download or
// hash. Each emit crosses the process boundary and re-renders the setup screen,
// so they are rate limited to something a person can actually perceive.
const PROGRESS_INTERVAL_MS = 100;
const PLATFORM_WAIT_GUIDANCE = Object.freeze({
  win32: Object.freeze({
    wsl: Object.freeze({
      title: 'Windows is still enabling WSL 2',
      detail: 'Windows may be finishing updates in the background. Leave its setup window open. If the percentage has not changed for 10 minutes, cancel that setup, restart Windows, then open omnideck and try again.',
    }),
    installer: Object.freeze({
      title: 'Podman is still installing',
      detail: 'Leave the Windows installer open while it finishes. If its progress has not changed for 10 minutes, cancel it, restart Windows, then open omnideck and try again.',
    }),
    runtime: Object.freeze({
      title: 'The secure space is still starting',
      detail: 'The first start can take longer while Podman prepares WSL 2. If nothing changes for 10 minutes, close omnideck, restart Windows, then open omnideck and try again.',
    }),
  }),
  darwin: Object.freeze({
    installer: Object.freeze({
      title: 'Podman is waiting to finish installing',
      detail: 'Look for the macOS password prompt and approve it. If the installer still has not moved after 10 minutes, cancel it, restart your Mac, then open omnideck and try again.',
    }),
    runtime: Object.freeze({
      title: 'The secure space is still starting',
      detail: 'The first Podman start can take several minutes. If nothing changes for 10 minutes, close omnideck, restart your Mac, then open omnideck and try again.',
    }),
  }),
  linux: Object.freeze({
    installer: Object.freeze({
      title: 'Podman is still installing',
      detail: 'Your package manager may still be downloading files. If nothing changes for 10 minutes, cancel the system prompt, check your internet connection, then open omnideck and try again.',
    }),
    runtime: Object.freeze({
      title: 'Podman is taking longer than expected',
      detail: 'If nothing changes for 10 minutes, close omnideck, make sure Podman runs from a terminal, then open omnideck and try again.',
    }),
  }),
});
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
    detail: 'Windows must restart to finish enabling required features. Save any open work, then restart now or later. If you restart now, omnideck reopens after you sign in and continues setup.',
    value: 'Restart needed',
    canRetry: false,
    primaryAction: 'restart',
    primaryLabel: 'Restart now',
    secondaryAction: 'close',
    secondaryLabel: 'Restart later',
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
  if (!/^[a-z0-9][a-z0-9-]{0,24}$/.test(namespace)) {
    throw new Error('OMNIDECK_DESKTOP_TEST_NAMESPACE must contain only lowercase letters, numbers, and hyphens.');
  }
  return {
    container: `${CONTAINER_NAME}-${namespace}`,
    homeVolume: `${HOME_VOLUME}-${namespace}`,
    stateVolume: `${STATE_VOLUME}-${namespace}`,
    // Podman 6 limits machine names to 30 characters. Production keeps the
    // descriptive name above; isolated tests use a compact, unmistakable one.
    machine: `odrt-${namespace}`,
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

class OmnideckRuntime {
  constructor({
    userDataPath,
    resourcesPath = path.join(__dirname, '..', 'build'),
    allowDevelopmentImagePull = false,
    platform = process.platform,
    onState,
    cliBackend = null,
  }) {
    this.userDataPath = userDataPath;
    this.resourcesPath = resourcesPath;
    this.allowDevelopmentImagePull = allowDevelopmentImagePull;
    this.platform = platform;
    this.onState = onState;
    this.runtimeRoot = path.join(userDataPath, 'runtime');
    this.downloadRoot = path.join(userDataPath, 'downloads');
    this.logPath = path.join(userDataPath, 'logs', 'desktop.log');
    const names = testResourceNames();
    this.containerName = names.container;
    this.homeVolume = names.homeVolume;
    this.stateVolume = names.stateVolume;
    this.machineName = names.machine;
    this.containerMemory = '2g';
    this.containerSHMSize = '1024m';
    this.appPort = null;
    this.currentState = null;
    this.currentEnvironment = null;
    // Set only when a specific release has been chosen to install. While it is
    // set, it is what setup installs instead of the release this copy shipped
    // with.
    this.updateTarget = null;
    this.setupReason = 'first-run';
    this.lastProgressEmit = 0;
    this.phases = phasesFor(this.platform);
    this.phaseIndex = -1;
    this.phaseFraction = 0;
    this.cliBackend = cliBackend || new OmnideckCliBackend({
      resourcesPath: this.resourcesPath,
      platform: this.platform,
      env: () => this.runtimeEnv(),
      run: (...args) => this.run(...args),
    });
  }

  get appUrl() {
    if (!this.appPort) throw new Error('The omnideck runtime has not been prepared.');
    return `http://127.0.0.1:${this.appPort}`;
  }

  // What is on this computer, or null if nothing is. An unfinished install does
  // not change the answer: until the new release is actually in place, the one
  // it is replacing is still the one installed, and the record says so.
  async installedRelease() {
    const state = await readSetupState(this.userDataPath);
    if (!state) return null;
    return {
      version: state.imageVersion,
      imageRef: state.imageRef,
    };
  }

  async installedVersion() {
    return (await this.installedRelease())?.version || null;
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

  emitWaitGuidance(step) {
    const copy = PLATFORM_WAIT_GUIDANCE[this.platform]?.[step]
      || PLATFORM_WAIT_GUIDANCE.linux.runtime;
    const progress = this.overallProgress();
    this.emit('preparing', copy.title, copy.detail, {
      activity: this.currentActivity(),
      progress,
      indeterminate: !Number.isFinite(progress),
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
          version: releaseImage.imageVersion,
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
      return this.keepNewerInstall();
    } catch (error) {
      throw tagError(error, 'release');
    }
  }

  // The release this copy shipped with is a floor, not a target. An update
  // outlives the copy that installed it, so a computer can be running something
  // newer than the installer sitting on it — and repairing that installation
  // must not walk it back to what the installer happens to carry.
  async keepNewerInstall() {
    const shipped = this.currentEnvironment;
    const installed = await this.installedRelease();
    if (
      !installed
      || !/@sha256:[a-f0-9]{64}$/.test(installed.imageRef)
      || !parseVersion(installed.version)
      || !parseVersion(shipped.version)
      || compareVersions(installed.version, shipped.version) <= 0
    ) {
      return this.currentEnvironment;
    }
    this.currentEnvironment = {
      imageRef: installed.imageRef,
      sourceImage: installed.imageRef,
      version: installed.version,
    };
    return this.currentEnvironment;
  }

  // The recorded release is what is installed, not what is being installed. An
  // install that is still running has not replaced anything yet, so the record
  // keeps naming the release already on this computer until the new one is in
  // place. Writing the target early would erase the only evidence that the
  // computer had moved past the release this copy shipped with, and a failed
  // install would then be followed by one that moves it back.
  async saveSetupState(status, reason = this.setupReason) {
    if (!this.currentEnvironment) throw new Error('The target environment is not known.');
    const installed = status === 'in-progress' ? await this.installedRelease() : null;
    return writeSetupState(this.userDataPath, {
      status,
      reason,
      appVersion: APP_VERSION,
      imageVersion: installed?.version || this.currentEnvironment.version,
      imageRef: installed?.imageRef || this.currentEnvironment.imageRef,
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
      // An installation still sitting on the command line tool's port is moved
      // off it, so the two stop competing. The container carries the old
      // mapping and is rebuilt around the new port, the same way it is when a
      // port is lost to another program.
      if (savedPort === LEGACY_APP_PORT) await this.reserveNewAppPort();
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
    const directories = knownRuntimeDirectories(this.platform, process.env);
    const currentPath = process.env.PATH || '';
    return {
      ...process.env,
      PATH: [...directories, currentPath].join(path.delimiter),
      // Registry credentials remain application-private, but Podman's machine
      // and connection configuration must be the user's normal configuration.
      // That is how the desktop and CLI see the same omnideck-runtime machine.
      REGISTRY_AUTH_FILE: path.join(this.runtimeRoot, 'auth', 'auth.json'),
    };
  }

  async appendLog(line) {
    const timestamp = new Date().toISOString();
    await fsp.appendFile(this.logPath, `${timestamp} ${line}\n`).catch(() => {});
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
      let settled = false;
      let inactivityTimer = null;
      let inactivityShown = false;
      const clearInactivity = () => {
        if (inactivityTimer) clearTimeout(inactivityTimer);
        inactivityTimer = null;
      };
      const armInactivity = () => {
        if (inactivityShown || !Number.isFinite(options.inactivityMs) || options.inactivityMs <= 0) return;
        clearInactivity();
        inactivityTimer = setTimeout(() => {
          inactivityTimer = null;
          inactivityShown = true;
          options.onInactivity?.();
        }, options.inactivityMs);
      };
      const finish = (callback, value) => {
        if (settled) return;
        settled = true;
        clearInactivity();
        callback(value);
      };
      const capture = (isStdout) => (line) => {
        armInactivity();
        if (isStdout) stdoutText = `${stdoutText}${line}\n`.slice(-MAX_CAPTURED_OUTPUT);
        transcript = `${transcript}${line}\n`.slice(-MAX_CAPTURED_OUTPUT);
        void this.appendLog(`[${label}] ${line}`);
        options.onLine?.(line);
      };
      const stdout = splitLines(capture(true));
      const stderr = splitLines(capture(false));
      child.stdout?.on('data', (chunk) => stdout(chunk));
      child.stderr?.on('data', (chunk) => stderr(chunk));
      child.on('error', (error) => finish(reject, error));
      child.on('close', (code) => {
        stdout('', true);
        stderr('', true);
        const output = transcript.trim();
        if (options.acceptAnyExitCode || accepted.includes(code)) {
          finish(resolve, { code, output, stdout: stdoutText.trim() });
          return;
        }
        const error = new Error(`${label} exited with code ${code}`);
        error.code = code;
        error.output = output;
        finish(reject, error);
      });
      armInactivity();
    });
  }

  async startExisting() {
    const setupState = await readSetupState(this.userDataPath);

    if (!setupState) {
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
          version: setupState.imageVersion,
        };
      }

      let status;
      try {
        status = await this.cliBackend.instanceStatus(this.containerName);
      } catch (error) {
        // Nothing working to fall back to, so there is no choice worth offering.
        if (updateAvailable) {
          this.setupReason = 'update';
          this.emitWorking();
          return { action: 'setup', reason: this.setupReason };
        }
        throw tagError(error, error.failureKind || 'startup');
      }

      const expectedImage = this.currentEnvironment.sourceImage;
      if (status.image !== expectedImage || Number.parseInt(status.webUiPort, 10) !== this.appPort) {
        this.setupReason = 'repair';
        this.emitWorking();
        return { action: 'setup', reason: this.setupReason };
      }

      if (status.status !== 'running') {
        try {
          status = await this.cliBackend.startInstance(this.containerName);
        } catch (error) {
          if (error.code !== 'PORT_IN_USE') throw tagError(error, 'startup');
          await this.reserveNewAppPort();
          this.setupReason = 'repair';
          this.emitWorking();
          return { action: 'setup', reason: this.setupReason };
        }
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
    await this.ensureRuntimeReady().catch((error) => {
      throw error.diagnostic ? error : tagError(error, 'environment');
    });
    // A machine that was already ready has no CLI environment events to
    // stream. Briefly mark that applicable phase complete so fresh Desktop
    // setup and bare CLI setup keep the same four-step story.
    const environmentIndex = this.phases.findIndex((phase) => phase.id === 'environment');
    if (environmentIndex >= 0 && this.phaseIndex < environmentIndex) {
      this.beginPhase('environment');
      this.phaseFraction = 1;
      this.emitWorking();
    }
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

  async ensureRuntimeReady() {
    const sharedStatus = await this.cliBackend.status();
    if (sharedStatus.ready) {
      this.assertSharedMachine(sharedStatus);
      return;
    }

    const completed = await this.cliBackend.ensure({
      onEvent: (event) => {
        if (['software', 'environment'].includes(event.stage) && event.state === 'start') {
          this.beginPhase(event.stage);
        }
        if (Number.isFinite(event.progress)) {
          this.phaseFraction = Math.max(0, Math.min(1, event.progress));
        } else if (event.state === 'done') {
          this.phaseFraction = 1;
        }
        if (event.state === 'permission') {
          this.emit('preparing', 'Waiting for your permission', event.detail, {
            activity: event.activity || this.currentActivity(),
            progress: this.overallProgress(),
            indeterminate: true,
          });
        } else if (event.state === 'waiting') {
          this.emit('preparing', 'Setup is still working', event.detail, {
            activity: event.activity || this.currentActivity(),
            progress: this.overallProgress(),
            indeterminate: !Number.isFinite(this.overallProgress()),
          });
        } else {
          this.emitWorking();
        }
      },
    });
    this.assertSharedMachine(completed);
    if (!completed.ready) throw new Error('Podman setup finished, but the Omnideck runtime is not ready.');
  }

  assertSharedMachine(status) {
    const container = status.resources?.container;
    if (typeof container?.memory === 'string') this.containerMemory = container.memory;
    if (typeof container?.shmSize === 'string') this.containerSHMSize = container.shmSize;
    if (!['darwin', 'win32'].includes(this.platform) || !status.ready) return;
    if (status.machineName !== MACHINE_NAME) {
      throw new Error(
        `The bundled Omnideck CLI selected ${status.machineName || 'an unknown Podman machine'} instead of ${MACHINE_NAME}.`,
      );
    }
    this.machineName = MACHINE_NAME;
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
        manifest.schemaVersion !== 3
        || manifest.appVersion !== APP_VERSION
        || !isReleaseVersion(manifest.imageVersion)
        || !/^ghcr\.io\/[a-z0-9._/-]+@sha256:[a-f0-9]{64}$/.test(manifest.imageRef || '')
      ) {
        throw new Error('The omnideck runtime image does not match this application release.');
      }
      return manifest;
    }
    return null;
  }

  async ensureContainer() {
    const reconcile = () => this.cliBackend.ensureEnvironment({
      name: this.containerName,
      image: this.currentEnvironment.sourceImage,
      port: this.appPort,
      memory: this.containerMemory,
      shmSize: this.containerSHMSize,
      homeVolume: this.homeVolume,
      stateVolume: this.stateVolume,
      onEvent: (event) => {
        if (event.stage === 'pull_image') this.beginPhase('download');
        if (['create_container', 'replace_container', 'start_container', 'save_config'].includes(event.stage)) {
          this.beginPhase('startup');
        }
        if (event.state === 'progress') this.emitProgressUpdate();
        else this.emitWorking();
      },
      onInactivity: () => this.emitWaitGuidance(
        this.currentActivity() === 'Downloading omnideck…' ? 'installer' : 'runtime',
      ),
    });
    try {
      return await reconcile();
    } catch (error) {
      if (error.code !== 'PORT_IN_USE') throw error;
      await this.reserveNewAppPort();
      return reconcile();
    }
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
      secondaryAction: copy.secondaryAction ?? 'show-logs',
      secondaryLabel: copy.secondaryLabel ?? 'Show diagnostic log',
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
  OmnideckRuntime,
  SETUP_COPY,
  reserveAvailablePort,
  testResourceNames,
};
