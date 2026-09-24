import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

const testRoot = path.dirname(fileURLToPath(import.meta.url));
const validator = path.join(testRoot, 'validate-proof.mjs');
const vendor = JSON.parse(await readFile(path.join(testRoot, '../../src-tauri/binaries/vendor-manifest.json'), 'utf8'));

async function fixture(mutation = false) {
  const root = await mkdtemp(path.join(os.tmpdir(), 'omnideck-hardware-proof-'));
  const application = path.join(root, 'omnideck-fixture');
  const proof = path.join(root, 'proof.json');
  const report = path.join(root, 'report.json');
  await writeFile(application, Buffer.alloc(1024, 1));
  await writeFile(proof, JSON.stringify({
    cliVersion: vendor.version,
    cliCommit: vendor.commit,
    schemaVersion: 4,
    runtime: 'podman',
    state: 'ready',
    ready: true,
    operations: ['--version', '--json runtime status'],
    mutation,
  }));
  return { root, application, proof, report };
}

test('accepts the exact read-only packaged smoke proof', async (t) => {
  const paths = await fixture();
  t.after(() => rm(paths.root, { recursive: true, force: true }));
  const result = spawnSync(process.execPath, [
    validator,
    '--proof', paths.proof,
    '--application', paths.application,
    '--report', paths.report,
    '--require-ready',
  ], { encoding: 'utf8' });
  assert.equal(result.status, 0, result.stderr);
  const report = JSON.parse(await readFile(paths.report, 'utf8'));
  assert.equal(report.result, 'pass');
  assert.equal(report.proof.mutation, false);
});

test('rejects a smoke proof that reports a mutation', async (t) => {
  const paths = await fixture(true);
  t.after(() => rm(paths.root, { recursive: true, force: true }));
  const result = spawnSync(process.execPath, [
    validator,
    '--proof', paths.proof,
    '--application', paths.application,
    '--report', paths.report,
  ], { encoding: 'utf8' });
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /packaged smoke must remain read-only/);
});
