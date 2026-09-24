import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const scriptRoot = path.dirname(fileURLToPath(import.meta.url));
const vendorManifest = JSON.parse(
  await readFile(path.resolve(scriptRoot, '../../src-tauri/binaries/vendor-manifest.json'), 'utf8'),
);

function parseArguments(arguments_) {
  const result = { requireReady: false };
  for (let index = 0; index < arguments_.length; index += 1) {
    const argument = arguments_[index];
    if (argument === '--require-ready') {
      result.requireReady = true;
      continue;
    }
    if (!['--proof', '--application', '--report'].includes(argument)) {
      throw new Error(`unknown argument: ${argument}`);
    }
    result[argument.slice(2)] = arguments_[index + 1];
    index += 1;
  }
  assert(result.proof, '--proof is required');
  assert(result.application, '--application is required');
  assert(result.report, '--report is required');
  return result;
}

const options = parseArguments(process.argv.slice(2));
const proof = JSON.parse(await readFile(path.resolve(options.proof), 'utf8'));
assert.equal(proof.mutation, false, 'packaged smoke must remain read-only');
assert.equal(proof.cliVersion, vendorManifest.version, 'packaged sidecar version does not match the vendor manifest');
assert.equal(proof.cliCommit, vendorManifest.commit, 'packaged sidecar commit does not match the vendor manifest');
assert.equal(proof.schemaVersion, 4, 'runtime status did not use schema version 4');
assert.deepEqual(
  proof.operations,
  ['--version', '--json runtime status'],
  'packaged smoke performed an unexpected operation',
);
if (options.requireReady) assert.equal(proof.ready, true, 'runtime was not ready');

const application = await readFile(path.resolve(options.application));
const report = {
  schemaVersion: 1,
  result: 'pass',
  host: { platform: process.platform, architecture: process.arch },
  application: {
    name: path.basename(options.application),
    sha256: createHash('sha256').update(application).digest('hex'),
    size: application.length,
  },
  proof,
};
const reportPath = path.resolve(options.report);
await mkdir(path.dirname(reportPath), { recursive: true });
await writeFile(reportPath, `${JSON.stringify(report, null, 2)}\n`, 'utf8');
process.stdout.write(`Packaged desktop smoke passed for ${proof.cliVersion} (${proof.cliCommit}).\n`);
