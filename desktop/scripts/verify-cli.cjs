const { spawnSync } = require('node:child_process');
const path = require('node:path');

const { RUNTIME_SCHEMA_VERSION, cliFilename, validateRuntimeStatus } = require('../src/cli-backend.cjs');

function main() {
  const executable = path.join(__dirname, '..', 'build', 'runtime', cliFilename(process.platform));
  const result = spawnSync(executable, ['--json', 'runtime', 'status'], {
    encoding: 'utf8',
    shell: false,
    windowsHide: true,
  });
  if (result.error) throw result.error;
  if (result.status !== 0) {
    throw new Error(`Bundled CLI runtime status failed: ${(result.stderr || result.stdout).trim()}`);
  }
  const status = validateRuntimeStatus(JSON.parse(result.stdout));
  if (['darwin', 'win32'].includes(process.platform)
      && status.machineName
      && status.machineName !== 'omnideck-runtime') {
    throw new Error(`Bundled CLI selected unexpected machine ${status.machineName}.`);
  }
  process.stdout.write(
    `Verified bundled CLI runtime schema ${RUNTIME_SCHEMA_VERSION} (${status.state}).\n`,
  );
}

try {
  main();
} catch (error) {
  process.stderr.write(`${error.stack || error}\n`);
  process.exitCode = 1;
}
