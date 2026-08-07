const { spawnSync } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');

const { targetForBuild } = require('./build-cli.cjs');

function parseGoBuildSettings(output) {
  const settings = {};
  for (const line of String(output || '').split(/\r?\n/)) {
    const match = line.match(/^\s*build\s+([A-Z0-9_]+)=(.*)$/);
    if (match) settings[match[1]] = match[2];
  }
  return settings;
}

function verifyCliTarget({
  desktopRoot = path.join(__dirname, '..'),
  env = process.env,
  go = env.OMNIDECK_GO_PATH || 'go',
} = {}) {
  const target = targetForBuild({ env });
  const filename = target.goos === 'windows' ? 'omnideck-cli.exe' : 'omnideck-cli';
  const runtimeRoot = path.join(desktopRoot, 'build', 'runtime');
  const executable = path.join(runtimeRoot, filename);
  if (!fs.existsSync(executable)) {
    throw new Error(`The bundled CLI was not found at ${executable}.`);
  }
  const unexpected = fs.readdirSync(runtimeRoot)
    .filter((entry) => entry.startsWith('omnideck-cli') && entry !== filename);
  if (unexpected.length > 0) {
    throw new Error(
      `The package contains CLI files for another target: ${unexpected.join(', ')}.`,
    );
  }
  const result = spawnSync(go, ['version', '-m', executable], {
    cwd: desktopRoot,
    encoding: 'utf8',
    shell: false,
    windowsHide: true,
  });
  if (result.error) throw result.error;
  if (result.status !== 0) {
    throw new Error(result.stderr.trim() || `go version -m exited with ${result.status}.`);
  }
  const settings = parseGoBuildSettings(result.stdout);
  if (settings.GOOS !== target.goos || settings.GOARCH !== target.goarch) {
    throw new Error(
      `The package targets ${target.goos}/${target.goarch}, but its bundled CLI targets ${settings.GOOS || 'unknown'}/${settings.GOARCH || 'unknown'}.`,
    );
  }
  process.stdout.write(`Verified bundled CLI target ${target.goos}/${target.goarch}.\n`);
  return target;
}

if (require.main === module) {
  try {
    verifyCliTarget();
  } catch (error) {
    process.stderr.write(`${error.stack || error}\n`);
    process.exitCode = 1;
  }
}

module.exports = { parseGoBuildSettings, verifyCliTarget };
