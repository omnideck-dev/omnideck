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
    detail: 'Downloading and installing required components. This may take several minutes.',
  }),
  permission: Object.freeze({
    title: 'Preparing your environment',
    detail: 'Your computer may ask for permission to install required components. omnideck never sees or stores your password.',
  }),
  updating: Object.freeze({
    title: 'Preparing your environment',
    detail: 'Applying the latest updates… This may take several minutes.',
  }),
  finishing: Object.freeze({
    title: 'Finishing setup',
    detail: 'Getting everything ready…',
  }),
  ready: Object.freeze({
    title: 'omnideck is ready',
    detail: 'Everything is prepared. Open omnideck whenever you’re ready.',
  }),
});

const DIAGNOSTIC_DEFINITIONS = Object.freeze([
  Object.freeze({ id: 'support', label: 'Computer support' }),
  Object.freeze({ id: 'components', label: 'Required components' }),
  Object.freeze({ id: 'downloads', label: 'Required downloads' }),
  Object.freeze({ id: 'environment', label: 'Local environment' }),
  Object.freeze({ id: 'release', label: 'Release files' }),
  Object.freeze({ id: 'startup', label: 'omnideck startup' }),
]);

const FAILURE_COPY = Object.freeze({
  support: Object.freeze({
    result: 'Compatibility issue',
    title: 'This computer isn’t supported yet',
    detail: 'This version of omnideck can’t prepare the required environment on this computer.',
    value: 'Not supported',
  }),
  components: Object.freeze({
    result: 'Component issue',
    title: 'omnideck needs attention',
    detail: 'A required component couldn’t be installed or started. Try setup again.',
    value: 'Unavailable',
  }),
  permission: Object.freeze({
    diagnostic: 'components',
    result: 'Permission needed',
    title: 'omnideck needs attention',
    detail: 'Permission wasn’t granted. Try again and approve the request from your computer.',
    value: 'Permission denied',
  }),
  downloads: Object.freeze({
    result: 'Download issue',
    title: 'omnideck needs attention',
    detail: 'A required download didn’t finish. Check your connection and try again.',
    value: 'Interrupted',
  }),
  environment: Object.freeze({
    result: 'Environment issue',
    title: 'omnideck needs attention',
    detail: 'The local environment isn’t responding. Try again to repair it.',
    value: 'Not responding',
  }),
  release: Object.freeze({
    result: 'Installer issue',
    title: 'Download omnideck again',
    detail: 'This installer is incomplete or damaged. Download a fresh copy before trying again.',
    value: 'Invalid',
  }),
  startup: Object.freeze({
    result: 'Startup issue',
    title: 'omnideck needs attention',
    detail: 'Setup finished, but omnideck didn’t start. Try again to run the startup checks.',
    value: 'Timed out',
  }),
  restart: Object.freeze({
    diagnostic: 'components',
    result: 'Restart required',
    title: 'Restart needed',
    detail: 'Restart your computer, then open omnideck to continue setup.',
    value: 'Restart needed',
  }),
  unknown: Object.freeze({
    diagnostic: 'components',
    result: 'Setup issue',
    title: 'omnideck needs attention',
    detail: 'Setup didn’t finish. Try again, or open the diagnostic log if the issue continues.',
    value: 'Issue found',
  }),
});

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

function splitLines(buffer, onLine) {
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
    this.setupReason = 'first-run';
    this.diagnostics = new Map();
    this.resetDiagnostics();
  }

  get appUrl() {
    if (!this.appPort) throw new Error('The omnideck runtime has not been prepared.');
    return `http://127.0.0.1:${this.appPort}`;
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
      primaryAction: options.primaryAction ?? null,
      primaryLabel: options.primaryLabel ?? null,
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

  emitWorking() {
    const copy = this.setupReason === 'update' ? 'updating' : 'preparing';
    this.emitCopy('preparing', copy, { indeterminate: true });
  }

  resetDiagnostics() {
    this.diagnostics.clear();
    for (const definition of DIAGNOSTIC_DEFINITIONS) {
      this.diagnostics.set(definition.id, {
        ...definition,
        status: 'waiting',
        value: 'Not checked',
      });
    }
  }

  markDiagnostic(id, status, value) {
    const diagnostic = this.diagnostics.get(id);
    if (!diagnostic) return;
    this.diagnostics.set(id, { ...diagnostic, status, value });
  }

  diagnosticSnapshot() {
    return DIAGNOSTIC_DEFINITIONS.map(({ id }) => ({ ...this.diagnostics.get(id) }));
  }

  async desiredEnvironment() {
    try {
      const releaseImage = await this.releaseImage();
      if (releaseImage) {
        this.currentEnvironment = {
          imageRef: releaseImage.imageRef,
          sourceImage: releaseImage.imageRef,
        };
      } else if (this.allowDevelopmentImagePull) {
        this.currentEnvironment = {
          imageRef: `${DEVELOPMENT_IMAGE}#${APP_VERSION}`,
          sourceImage: DEVELOPMENT_IMAGE,
        };
      } else {
        throw new Error('This omnideck installer does not identify its application image.');
      }
      this.markDiagnostic('release', 'pass', 'Verified');
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
    const portPath = path.join(this.runtimeRoot, 'app-port');
    try {
      const savedPort = Number.parseInt(await fsp.readFile(portPath, 'utf8'), 10);
      if (savedPort < 1 || savedPort > 65535) throw new Error('Invalid saved port.');
      this.appPort = savedPort;
    } catch {
      this.appPort = await reserveAvailablePort();
      await fsp.writeFile(portPath, `${this.appPort}\n`, { mode: 0o600 });
    }
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
    for (const candidate of candidates) {
      try {
        await fsp.access(candidate, fs.constants.X_OK);
        return candidate;
      } catch {
        // Keep looking.
      }
    }
    return null;
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
      let output = '';
      const capture = (line) => {
        output = `${output}${line}\n`.slice(-1_000_000);
        void this.appendLog(`[${label}] ${line}`);
        options.onLine?.(line);
      };
      const stdout = splitLines('', capture);
      const stderr = splitLines('', capture);
      child.stdout?.on('data', (chunk) => stdout(chunk));
      child.stderr?.on('data', (chunk) => stderr(chunk));
      child.on('error', (error) => reject(error));
      child.on('close', (code) => {
        stdout('', true);
        stderr('', true);
        if (options.acceptAnyExitCode || accepted.includes(code)) {
          resolve({ code, output: output.trim() });
          return;
        }
        const error = new Error(`${label} exited with code ${code}`);
        error.code = code;
        error.output = output.trim();
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
    this.resetDiagnostics();
    try {
      const desired = await this.desiredEnvironment();
      if (setupState?.status === 'complete' && setupState.imageRef !== desired.imageRef) {
        this.setupReason = 'update';
        this.emitWorking();
        return { action: 'setup', reason: this.setupReason };
      }

      this.markDiagnostic('support', 'pass', 'Supported');
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
      this.markDiagnostic('components', 'pass', 'Installed');
      await this.run(this.podmanPath, ['info', '--format', '{{.Version.Version}}'], {
        label: 'runtime check',
      }).catch((error) => {
        throw tagError(error, 'environment');
      });
      this.markDiagnostic('environment', 'pass', 'Ready');

      const info = await this.containerInfo();
      if (!this.isCurrentContainer(info)) {
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

      this.markDiagnostic('downloads', 'pass', 'Available');
      if (info.State?.Status !== 'running') {
        await this.run(this.podmanPath, ['start', this.containerName], {
          label: 'start app',
        }).catch((error) => {
          throw tagError(error, 'startup');
        });
      }
      await this.waitForApp({ silent: true });
      this.markDiagnostic('startup', 'pass', 'Ready');
      this.setupReason = setupState?.reason || 'first-run';
      await this.saveSetupState('complete', this.setupReason);
      return { action: 'open', reason: this.setupReason };
    } catch (error) {
      this.reportFailure(error);
      return { action: 'doctor', reason: setupState?.reason || 'repair' };
    }
  }

  async setup(reason = this.setupReason) {
    await this.prepare();
    this.resetDiagnostics();
    this.setupReason = reason === 'update'
      ? 'update'
      : reason === 'repair'
        ? 'repair'
        : reason === 'first-run'
          ? 'first-run'
          : 'resume';

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
    this.emitWorking();
    this.markDiagnostic('support', 'pass', 'Supported');

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
    this.markDiagnostic('components', 'pass', 'Ready');

    await this.ensureRuntimeReady().catch((error) => {
      throw tagError(error, 'environment');
    });
    this.markDiagnostic('environment', 'pass', 'Ready');
    await this.ensureContainer().catch((error) => {
      throw error.diagnostic ? error : tagError(error, 'startup');
    });
    this.markDiagnostic('downloads', 'pass', 'Available');
    await this.waitForApp().catch((error) => {
      throw tagError(error, 'startup');
    });
    this.markDiagnostic('startup', 'pass', 'Ready');
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
    this.emitCopy('preparing', 'permission', { indeterminate: true });
    const script = [
      "$process = Start-Process -FilePath $env:OMNIDECK_WSL_PATH -ArgumentList @('--install', '--no-distribution') -Verb RunAs -Wait -PassThru",
      'exit $process.ExitCode',
    ].join('; ');
    await this.run(
      powershell,
      ['-NoLogo', '-NoProfile', '-NonInteractive', '-Command', script],
      {
        env: { ...process.env, OMNIDECK_WSL_PATH: wsl },
        label: 'Windows workspace setup',
        acceptExitCodes: [0, 3010],
      },
    );

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
      this.emitCopy('preparing', 'permission', { indeterminate: true });
      await this.run('/usr/bin/osascript', ['-e', script, destination], { label: 'system installer' });
      return;
    }

    await this.verifyWindowsInstaller(destination);
    this.emitCopy('preparing', 'permission', { indeterminate: true });
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
      this.emitCopy('preparing', 'permission', { indeterminate: true });
      await this.run(pkexec, [command, ...args], {
        env: process.env,
        label: 'system installer',
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
      const cachedDigest = await sha256File(destination, () => this.emitWorking()).catch(() => null);
      if (cachedDigest === expectedSha256) return;
      if (cachedDigest) await fsp.rm(destination, { force: true });

      const response = await fetch(url, { redirect: 'follow' });
      if (!response.ok || !response.body) {
        throw new Error(`Download failed with HTTP ${response.status}.`);
      }
      const hash = crypto.createHash('sha256');
      const progress = new Transform({
        transform: (chunk, _encoding, callback) => {
          hash.update(chunk);
          this.emitWorking();
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
        onLine: () => this.emitWorking(),
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
          onLine: () => this.emitWorking(),
        },
      );
    }
    await this.run(this.podmanPath, ['info', '--format', '{{.Version.Version}}'], {
      label: 'runtime check',
    });
  }

  async containerExists() {
    return Boolean(await this.containerInfo());
  }

  async containerInfo() {
    const result = await this.run(
      this.podmanPath,
      ['container', 'inspect', this.containerName],
      { label: 'app check', acceptExitCodes: [0, 125] },
    );
    if (result.code !== 0) return null;
    try {
      const inspection = JSON.parse(result.output);
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

  async startContainer({ silent = false } = {}) {
    const info = await this.containerInfo();
    if (!this.isCurrentContainer(info)) return false;
    if (info.State?.Status !== 'running') {
      if (!silent) this.emitCopy('finishing', 'finishing', { indeterminate: true });
      await this.run(this.podmanPath, ['start', this.containerName], { label: 'start app' });
    }
    return true;
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
          onLine: () => this.emitWorking(),
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
          onLine: () => this.emitWorking(),
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

    for (const volume of [this.homeVolume, this.stateVolume]) {
      const inspected = await this.run(
        this.podmanPath,
        ['volume', 'inspect', volume],
        { label: 'storage check', acceptExitCodes: [0, 125] },
      );
      if (inspected.code !== 0) {
        await this.run(this.podmanPath, ['volume', 'create', volume], { label: 'prepare storage' });
      }
    }

    this.emitCopy('finishing', 'finishing', { indeterminate: true });
    await this.run(
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
    if (!silent) this.emitCopy('finishing', 'finishing', { indeterminate: true });
    const deadline = Date.now() + 120_000;
    while (Date.now() < deadline) {
      try {
        const response = await fetch(this.appUrl, { signal: AbortSignal.timeout(3_000) });
        if (response.ok) return;
      } catch {
        // Startup is still in progress.
      }
      await new Promise((resolve) => setTimeout(resolve, 1_000));
    }
    throw tagError(new Error('omnideck took too long to start.'), 'startup');
  }

  reportFailure(error) {
    const raw = `${error?.message || error}\n${error?.output || ''}`.trim();
    void this.appendLog(`[failure] ${raw}`);
    let failureKind = error?.failureKind || error?.diagnostic || 'unknown';
    if (/restart|3010/i.test(raw)) {
      failureKind = 'restart';
    } else if (/permission|not authorized|authentication|cancel|denied/i.test(raw)) {
      failureKind = 'permission';
    } else if (/network|download|http|resolve|connection|pull/i.test(raw)) {
      failureKind = 'downloads';
    } else if (/integrity|does not identify|manifest is invalid|does not match/i.test(raw)) {
      failureKind = 'release';
    }
    const copy = FAILURE_COPY[failureKind] || FAILURE_COPY.unknown;
    const diagnostic = copy.diagnostic || failureKind;
    this.markDiagnostic(diagnostic, 'issue', copy.value);
    this.emit('error', copy.title, copy.detail, {
      canRetry: !['support', 'release', 'restart'].includes(failureKind),
      primaryAction: failureKind === 'support'
        ? 'supported-systems'
        : failureKind === 'release'
          ? 'download'
          : failureKind === 'restart'
            ? 'close'
            : null,
      primaryLabel: failureKind === 'support'
        ? 'View supported systems'
        : failureKind === 'release'
          ? 'Download omnideck'
          : failureKind === 'restart'
            ? 'Close omnideck'
            : null,
      diagnostics: this.diagnosticSnapshot(),
      diagnosticResult: copy.result,
      technical: raw.slice(0, 4_000),
    });
  }
}

module.exports = {
  APP_VERSION,
  DIAGNOSTIC_DEFINITIONS,
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
