const { spawnSync } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');

function commandOutput(command, args, cwd, fallback) {
  const result = spawnSync(command, args, {
    cwd,
    encoding: 'utf8',
    shell: false,
    windowsHide: true,
  });
  return result.status === 0 ? result.stdout.trim() || fallback : fallback;
}

function targetForHost(platform = process.platform, arch = process.arch) {
  const goos = platform === 'win32' ? 'windows' : platform;
  const goarch = arch === 'x64' ? 'amd64' : arch;
  return validateTarget(goos, goarch);
}

function validateTarget(goos, goarch) {
  if (!['windows', 'darwin', 'linux'].includes(goos)) {
    throw new Error(`Unsupported CLI target operating system: ${goos}`);
  }
  if (!['amd64', 'arm64'].includes(goarch)) {
    throw new Error(`Unsupported CLI target architecture: ${goarch}`);
  }
  return { goos, goarch };
}

function targetForBuild({
  env = process.env,
  platform = process.platform,
  arch = process.arch,
} = {}) {
  const explicitOS = env.OMNIDECK_CLI_GOOS;
  const explicitArch = env.OMNIDECK_CLI_GOARCH;
  if (Boolean(explicitOS) !== Boolean(explicitArch)) {
    throw new Error('OMNIDECK_CLI_GOOS and OMNIDECK_CLI_GOARCH must be set together.');
  }
  if (explicitOS) return validateTarget(explicitOS, explicitArch);
  return targetForHost(platform, arch);
}

function bundledCliPaths(outputRoot) {
  return [
    path.join(outputRoot, 'omnideck-cli'),
    path.join(outputRoot, 'omnideck-cli.exe'),
  ];
}

function removeOtherCliOutputs(outputRoot, keep = null) {
  const keptPath = keep && path.resolve(keep);
  for (const candidate of bundledCliPaths(outputRoot)) {
    if (path.resolve(candidate) !== keptPath) fs.rmSync(candidate, { force: true });
  }
}

function main() {
  const desktopRoot = path.join(__dirname, '..');
  const source = path.resolve(
    process.env.OMNIDECK_CLI_SOURCE || path.join(desktopRoot, '..', '..', 'cli'),
  );
  const { goos, goarch } = targetForBuild();
  const extension = goos === 'windows' ? '.exe' : '';
  const outputRoot = path.join(desktopRoot, 'build', 'runtime');
  const output = path.join(outputRoot, `omnideck-cli${extension}`);
  fs.mkdirSync(outputRoot, { recursive: true });

  const prebuilt = process.env.OMNIDECK_CLI_PREBUILT;
  if (prebuilt) {
    const sourceBinary = path.resolve(prebuilt);
    if (!fs.existsSync(sourceBinary)) {
      throw new Error(`The prebuilt Omnideck CLI was not found at ${sourceBinary}.`);
    }
    if (sourceBinary !== path.resolve(output)) {
      fs.rmSync(output, { force: true });
      fs.copyFileSync(sourceBinary, output);
    }
    removeOtherCliOutputs(outputRoot, output);
    if (goos !== 'windows') fs.chmodSync(output, 0o755);
    process.stdout.write(`${output}\n`);
    return;
  }

  if (!fs.existsSync(path.join(source, 'go.mod'))) {
    throw new Error(
      `Omnideck CLI source was not found at ${source}. Set OMNIDECK_CLI_SOURCE to its checkout.`,
    );
  }

  const go = process.env.OMNIDECK_GO_PATH || 'go';
  removeOtherCliOutputs(outputRoot);
  const version = commandOutput('git', ['describe', '--tags', '--always', '--dirty'], source, 'dev');
  const commit = commandOutput('git', ['rev-parse', '--short', 'HEAD'], source, 'none');
  const date = new Date(
    process.env.SOURCE_DATE_EPOCH ? Number(process.env.SOURCE_DATE_EPOCH) * 1000 : Date.now(),
  ).toISOString().replace('.000Z', 'Z');
  const ldflags = [
    `-X main.version=${version}`,
    `-X main.commit=${commit}`,
    `-X main.date=${date}`,
  ].join(' ');

  const result = spawnSync(go, [
    'build',
    '-buildvcs=false',
    '-trimpath',
    '-ldflags', ldflags,
    '-o', output,
    '.',
  ], {
    cwd: source,
    env: {
      ...process.env,
      CGO_ENABLED: '0',
      GOOS: goos,
      GOARCH: goarch,
    },
    shell: false,
    stdio: 'inherit',
    windowsHide: true,
  });
  if (result.error) throw result.error;
  if (result.status !== 0) process.exit(result.status ?? 1);
  if (goos !== 'windows') fs.chmodSync(output, 0o755);
  process.stdout.write(`${output}\n`);
}

if (require.main === module) {
  try {
    main();
  } catch (error) {
    process.stderr.write(`${error.stack || error}\n`);
    process.exitCode = 1;
  }
}

module.exports = {
  bundledCliPaths,
  main,
  removeOtherCliOutputs,
  targetForBuild,
  targetForHost,
  validateTarget,
};
