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

const DEFAULT_APP_PORT = 2337;
const CONTAINER_NAME = 'omnideck-desktop';
const HOME_VOLUME = 'omnideck-desktop-home';
const STATE_VOLUME = 'omnideck-desktop-state';
const IMAGE = `localhost/omnideck/runtime:${APP_VERSION}`;
const DEVELOPMENT_IMAGE = 'ghcr.io/omnideck-dev/omnideck:main';
const IMAGE_LABEL = 'dev.omnideck.version';
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
    this.podmanPath = null;
    this.appPort = null;
    this.currentState = null;
  }

  get appUrl() {
    if (!this.appPort) throw new Error('The OmniDeck runtime has not been prepared.');
    return `http://127.0.0.1:${this.appPort}`;
  }

  emit(stage, title, detail, options = {}) {
    this.currentState = {
      stage,
      title,
      detail,
      progress: options.progress ?? null,
      canStart: options.canStart ?? false,
      canRetry: options.canRetry ?? false,
      canOpen: options.canOpen ?? false,
    };
    this.onState(this.currentState);
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
    await this.prepare();
    this.emit('checking', 'Opening OmniDeck', 'Checking your private workspace…');
    this.podmanPath = await this.findExecutable('podman');
    if (!this.podmanPath) {
      this.emit(
        'welcome',
        'Welcome to OmniDeck',
        'A one-time setup will prepare a private workspace and download OmniDeck.',
        { canStart: true },
      );
      return false;
    }

    try {
      await this.run(this.podmanPath, ['info', '--format', '{{.Version.Version}}'], {
        label: 'runtime check',
      });
      const started = await this.startContainer();
      if (!started) {
        this.emit(
          'welcome',
          'Welcome to OmniDeck',
          'A one-time setup will prepare OmniDeck and your private workspace.',
          { canStart: true },
        );
        return false;
      }
      await this.waitForApp();
      return true;
    } catch {
      this.emit(
        'welcome',
        'Finish setting up OmniDeck',
        'OmniDeck needs to finish preparing its private workspace on this computer.',
        { canStart: true },
      );
      return false;
    }
  }

  async setup() {
    await this.prepare();
    this.emit('installing', 'Preparing OmniDeck', 'Checking the required system components…');
    if (process.platform === 'win32') {
      await this.ensureWindowsPrerequisites();
    }
    this.podmanPath = await this.findExecutable('podman');
    if (!this.podmanPath) {
      await this.installRuntime();
      this.podmanPath = await this.findExecutable('podman');
      if (!this.podmanPath) throw new Error('The required system component was installed but could not be opened.');
    }

    await this.ensureRuntimeReady();
    await this.ensureContainer();
    await this.waitForApp();
    this.emit(
      'ready',
      'OmniDeck is ready',
      'Your private workspace is prepared. Open it whenever you’re ready.',
      { progress: 1, canOpen: true },
    );
  }

  async ensureWindowsPrerequisites() {
    const systemRoot = process.env.SystemRoot || process.env.WINDIR || 'C:\\Windows';
    const systemWsl = path.join(systemRoot, 'System32', 'wsl.exe');
    const wsl = await this.findExecutable('wsl.exe', process.env)
      || (fs.existsSync(systemWsl) ? systemWsl : null);
    if (!wsl) {
      throw new Error('OmniDeck requires Windows 11 with WSL 2 support.');
    }

    const status = await this.run(wsl, ['--status'], {
      env: process.env,
      label: 'Windows workspace check',
      acceptAnyExitCode: true,
    });
    if (status.code === 0) return;

    const powershell = await this.findExecutable('powershell.exe', process.env);
    if (!powershell) {
      throw new Error('Windows could not prepare WSL 2 for OmniDeck.');
    }
    this.emit(
      'installing',
      'Preparing Windows',
      'Windows will ask for permission to enable its private workspace feature.',
    );
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
      throw new Error('Windows restart required after enabling WSL 2.');
    }
  }

  async installRuntime() {
    this.emit(
      'installing',
      'Installing required components',
      'Your computer may ask for permission. OmniDeck never sees or stores your password.',
    );
    if (process.platform === 'linux') {
      await this.installRuntimeOnLinux();
      return;
    }

    const key = `${process.platform}-${process.arch}`;
    const installer = INSTALLERS[key];
    if (!installer) {
      throw new Error('This prototype does not yet include the required component for this computer architecture.');
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
      await this.run('/usr/bin/osascript', ['-e', script, destination], { label: 'system installer' });
      return;
    }

    await this.verifyWindowsInstaller(destination);
    await this.run(
      'msiexec.exe',
      ['/i', destination, '/passive', '/norestart', 'ALLUSERS=2', 'MSIINSTALLPERUSER=1'],
      { label: 'system installer', acceptExitCodes: [0, 3010] },
    );
  }

  async installRuntimeOnLinux() {
    const pkexec = await this.findExecutable('pkexec', process.env);
    if (!pkexec) {
      throw new Error('This Linux desktop does not provide a graphical system-permission prompt.');
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
      throw new Error('Automatic setup is not available for this Linux distribution yet.');
    }
    for (const [command, args] of commands) {
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
    const response = await fetch(url, { redirect: 'follow' });
    if (!response.ok || !response.body) throw new Error(`Download failed with HTTP ${response.status}.`);
    const total = Number(response.headers.get('content-length')) || null;
    let received = 0;
    const hash = crypto.createHash('sha256');
    const progress = new Transform({
      transform: (chunk, _encoding, callback) => {
        received += chunk.length;
        hash.update(chunk);
        this.emit(
          'downloading',
          'Downloading required components',
          total ? `${Math.round((received / total) * 100)}% complete` : 'Downloading…',
          { progress: total ? received / total : null },
        );
        callback(null, chunk);
      },
    });
    await pipeline(Readable.fromWeb(response.body), progress, fs.createWriteStream(partial));
    const digest = hash.digest('hex');
    if (digest !== expectedSha256) {
      await fsp.rm(partial, { force: true });
      throw new Error('The downloaded system component did not pass its security check.');
    }
    await replaceDownloadedFile(partial, destination);
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

    this.emit(
      'preparing',
      'Preparing your private workspace',
      'This is a one-time download and can take several minutes.',
    );
    const inspection = await this.run(
      this.podmanPath,
      ['machine', 'inspect', MACHINE_NAME],
      { label: 'workspace check', acceptExitCodes: [0, 125] },
    );
    if (inspection.code === 0) {
      await this.run(this.podmanPath, ['machine', 'start', MACHINE_NAME], {
        label: 'start workspace',
        onLine: () => this.emit('preparing', 'Starting your private workspace', 'Almost ready…'),
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
          MACHINE_NAME,
        ],
        {
          label: 'prepare workspace',
          onLine: () => this.emit(
            'preparing',
            'Preparing your private workspace',
            'Downloading and configuring the workspace…',
          ),
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
      ['container', 'inspect', CONTAINER_NAME],
      { label: 'app check', acceptExitCodes: [0, 125] },
    );
    if (result.code !== 0) return null;
    try {
      const inspection = JSON.parse(result.output);
      return Array.isArray(inspection) ? inspection[0] || null : inspection;
    } catch {
      throw new Error('OmniDeck could not read the existing workspace state.');
    }
  }

  isCurrentContainer(info) {
    return info?.Config?.Labels?.[IMAGE_LABEL] === APP_VERSION
      && info?.Config?.Image === IMAGE;
  }

  async startContainer() {
    const info = await this.containerInfo();
    if (!this.isCurrentContainer(info)) return false;
    if (info.State?.Status !== 'running') {
      this.emit('starting', 'Starting OmniDeck', 'Opening your workspace…');
      await this.run(this.podmanPath, ['start', CONTAINER_NAME], { label: 'start app' });
    }
    return true;
  }

  async bundledImage() {
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
        throw new Error('The bundled OmniDeck image manifest is invalid.');
      }
      if (
        manifest.schemaVersion !== 1
        || manifest.appVersion !== APP_VERSION
        || manifest.imageRef !== IMAGE
        || manifest.architecture !== (process.arch === 'x64' ? 'amd64' : process.arch)
        || path.basename(manifest.archive || '') !== manifest.archive
        || !/^[a-f0-9]{64}$/.test(manifest.archiveSha256 || '')
      ) {
        throw new Error('The bundled OmniDeck image does not match this application release.');
      }
      const archivePath = path.join(root, manifest.archive);
      try {
        await fsp.access(archivePath, fs.constants.R_OK);
      } catch {
        throw new Error('The bundled OmniDeck image archive is missing.');
      }
      return { ...manifest, archivePath };
    }
    return null;
  }

  async imageExists() {
    const result = await this.run(
      this.podmanPath,
      ['image', 'exists', IMAGE],
      { label: 'application image check', acceptExitCodes: [0, 1, 125] },
    );
    return result.code === 0;
  }

  async ensureImage() {
    if (await this.imageExists()) return;
    const bundle = await this.bundledImage();
    if (!bundle) {
      if (!this.allowDevelopmentImagePull) {
        throw new Error('This OmniDeck installer does not contain its application image.');
      }
      this.emit('downloading', 'Downloading development build', 'Receiving OmniDeck…');
      await this.run(this.podmanPath, ['pull', DEVELOPMENT_IMAGE], {
        label: 'download development app',
        onLine: () => this.emit('downloading', 'Downloading development build', 'Receiving OmniDeck…'),
      });
      await this.run(this.podmanPath, ['tag', DEVELOPMENT_IMAGE, IMAGE], {
        label: 'prepare development app',
      });
      return;
    }

    let lastPercent = -1;
    this.emit(
      'loading-image',
      'Preparing OmniDeck',
      'Checking the bundled application…',
      { progress: 0 },
    );
    const digest = await sha256File(bundle.archivePath, (value) => {
      const percent = Math.floor(value * 100);
      if (percent === lastPercent) return;
      lastPercent = percent;
      this.emit(
        'loading-image',
        'Preparing OmniDeck',
        `Checking application files… ${percent}%`,
        { progress: value },
      );
    });
    if (digest !== bundle.archiveSha256) {
      throw new Error('The bundled OmniDeck application did not pass its integrity check.');
    }

    this.emit('loading-image', 'Unpacking OmniDeck', 'Installing the bundled application…');
    await this.run(this.podmanPath, ['load', '--input', bundle.archivePath], {
      label: 'load application',
      onLine: () => this.emit(
        'loading-image',
        'Unpacking OmniDeck',
        'Installing application files…',
      ),
    });
    if (!await this.imageExists()) {
      throw new Error('The bundled OmniDeck image could not be loaded.');
    }
  }

  async ensureContainer() {
    if (await this.startContainer()) return;
    await this.ensureImage();

    const existing = await this.containerInfo();
    if (existing) {
      this.emit('starting', 'Updating OmniDeck', 'Switching to this release…');
      await this.run(this.podmanPath, ['rm', '--force', CONTAINER_NAME], {
        label: 'replace app',
      });
    }

    for (const volume of [HOME_VOLUME, STATE_VOLUME]) {
      const inspected = await this.run(
        this.podmanPath,
        ['volume', 'inspect', volume],
        { label: 'storage check', acceptExitCodes: [0, 125] },
      );
      if (inspected.code !== 0) {
        await this.run(this.podmanPath, ['volume', 'create', volume], { label: 'prepare storage' });
      }
    }

    this.emit('starting', 'Starting OmniDeck', 'Finishing first-time setup…');
    await this.run(
      this.podmanPath,
      [
        'run', '-d',
        '--name', CONTAINER_NAME,
        '--restart', 'always',
        '--label', `${IMAGE_LABEL}=${APP_VERSION}`,
        '--memory', '2g',
        '--shm-size', '1024m',
        '-p', `127.0.0.1:${this.appPort}:8080`,
        '-v', `${HOME_VOLUME}:/home/omnideck`,
        '-v', `${STATE_VOLUME}:/var/lib/omnideck`,
        '-e', 'ENABLE_DESKTOP=false',
        '-e', 'OLLAMA_HOST=http://host.containers.internal:11434',
        '-e', 'PORT=8080',
        IMAGE,
      ],
      { label: 'start app' },
    );
  }

  async waitForApp() {
    this.emit('starting', 'Starting OmniDeck', 'Waiting for the app to become ready…');
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
    throw new Error('OmniDeck took too long to start.');
  }

  reportFailure(error) {
    const raw = `${error?.message || error}\n${error?.output || ''}`.trim();
    void this.appendLog(`[failure] ${raw}`);
    let detail = 'Setup did not finish. You can retry without losing downloaded files.';
    if (/restart|3010|wsl/i.test(raw)) {
      detail = 'Windows needs to restart before OmniDeck can finish setup.';
    } else if (/permission|not authorized|authentication|cancel/i.test(raw)) {
      detail = 'The system permission request was cancelled or denied.';
    } else if (/network|download|http|resolve|connection/i.test(raw)) {
      detail = 'A required download failed. Check your connection and try again.';
    } else if (/integrity|does not contain|archive is missing|does not match/i.test(raw)) {
      detail = 'This OmniDeck installer is incomplete or damaged. Download it again and retry.';
    }
    this.emit('error', 'OmniDeck couldn’t finish setup', detail, { canRetry: true });
  }
}

module.exports = {
  APP_VERSION,
  IMAGE,
  OmniDeckRuntime,
  installerUrl,
  linuxInstallCommands,
  parseOsRelease,
  replaceDownloadedFile,
  reserveAvailablePort,
  sha256File,
};
