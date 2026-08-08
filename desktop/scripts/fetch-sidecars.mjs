import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import { chmod, copyFile, mkdir, mkdtemp, readFile, readdir, rm, writeFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const scriptRoot = path.dirname(fileURLToPath(import.meta.url));
const binaryRoot = path.resolve(scriptRoot, '../src-tauri/binaries');
const manifest = JSON.parse(await readFile(path.join(binaryRoot, 'vendor-manifest.json'), 'utf8'));
const archiveRoot = process.env.OMNIDECK_CLI_ARCHIVE_DIR
  ? path.resolve(process.env.OMNIDECK_CLI_ARCHIVE_DIR)
  : null;

function sha256(value) {
  return createHash('sha256').update(value).digest('hex');
}

function filename(targetTriple) {
  return `omnideck-cli-${targetTriple}${targetTriple.includes('windows') ? '.exe' : ''}`;
}

function run(command, args) {
  const result = spawnSync(command, args, { encoding: 'utf8', windowsHide: true });
  if (result.error) throw result.error;
  assert.equal(result.status, 0, result.stderr || `${command} exited with ${result.status}`);
}

function powershellLiteral(value) {
  return `'${value.replaceAll("'", "''")}'`;
}

async function findExtractedBinary(root, expectedName) {
  const candidates = [];
  async function visit(directory) {
    for (const entry of await readdir(directory, { withFileTypes: true })) {
      const entryPath = path.join(directory, entry.name);
      if (entry.isDirectory()) await visit(entryPath);
      else if (entry.name === expectedName) candidates.push(entryPath);
    }
  }
  await visit(root);
  assert.equal(candidates.length, 1, `expected one extracted ${expectedName}, found ${candidates.length}`);
  return candidates[0];
}

function selectTargets(requested) {
  if (requested.length === 0) return manifest.targets;
  const known = new Map(manifest.targets.map((target) => [target.targetTriple, target]));
  return requested.map((targetTriple) => {
    assert(known.has(targetTriple), `unsupported CLI target: ${targetTriple}`);
    return known.get(targetTriple);
  });
}

async function releaseAsset(name) {
  if (archiveRoot) return readFile(path.join(archiveRoot, name));
  const url = `${manifest.downloadBaseUrl}/${name}`;
  let lastError;
  for (let attempt = 1; attempt <= 3; attempt += 1) {
    try {
      const response = await fetch(url, { signal: AbortSignal.timeout(60_000) });
      assert(response.ok, `failed to download ${name}: HTTP ${response.status}`);
      return Buffer.from(await response.arrayBuffer());
    } catch (error) {
      lastError = error;
      if (attempt < 3) await new Promise((resolve) => setTimeout(resolve, attempt * 1_000));
    }
  }
  throw lastError;
}

assert.equal(manifest.schemaVersion, 1);
assert.match(manifest.downloadBaseUrl, /^https:\/\/github\.com\/omnideck-dev\/cli\/releases\/download\//);

await mkdir(binaryRoot, { recursive: true });
await mkdir(path.join(binaryRoot, 'sbom'), { recursive: true });
const selected = selectTargets(process.argv.slice(2).filter((argument) => argument !== '--'));

for (const target of selected) {
  const sbomDestination = path.join(binaryRoot, 'sbom', target.sbom);
  let sbomIsValid = false;
  try {
    sbomIsValid = sha256(await readFile(sbomDestination)) === target.sbomSha256;
  } catch (error) {
    if (error.code !== 'ENOENT') throw error;
  }
  if (!sbomIsValid) {
    const sbom = await releaseAsset(target.sbom);
    assert.equal(sha256(sbom), target.sbomSha256, `${target.sbom} checksum mismatch`);
    await writeFile(sbomDestination, sbom);
  }

  const destination = path.join(binaryRoot, filename(target.targetTriple));
  try {
    if (sha256(await readFile(destination)) === target.binarySha256) {
      process.stdout.write(`Using verified ${target.targetTriple} sidecar.\n`);
      continue;
    }
  } catch (error) {
    if (error.code !== 'ENOENT') throw error;
  }

  const temporaryRoot = await mkdtemp(path.join(os.tmpdir(), 'omnideck-cli-'));
  try {
    const archive = await releaseAsset(target.archive);
    assert.equal(sha256(archive), target.archiveSha256, `${target.archive} checksum mismatch`);

    const archivePath = path.join(temporaryRoot, target.archive);
    const extractRoot = path.join(temporaryRoot, 'extract');
    await mkdir(extractRoot);
    await writeFile(archivePath, archive);
    if (target.archive.endsWith('.zip')) {
      if (process.platform === 'win32') {
        const command = [
          `Expand-Archive -LiteralPath ${powershellLiteral(archivePath)}`,
          `-DestinationPath ${powershellLiteral(extractRoot)} -Force`,
        ].join(' ');
        run('powershell.exe', [
          '-NoProfile',
          '-NonInteractive',
          '-EncodedCommand',
          Buffer.from(command, 'utf16le').toString('base64'),
        ]);
      } else {
        run('unzip', ['-q', archivePath, '-d', extractRoot]);
      }
    } else {
      run('tar', ['-xzf', archivePath, '-C', extractRoot]);
    }

    const extracted = await findExtractedBinary(
      extractRoot,
      target.targetTriple.includes('windows') ? 'omnideck.exe' : 'omnideck',
    );
    const contents = await readFile(extracted);
    assert.equal(sha256(contents), target.binarySha256, `${target.targetTriple} binary checksum mismatch`);
    await copyFile(extracted, destination);
    if (!target.targetTriple.includes('windows')) await chmod(destination, 0o755);
    process.stdout.write(`Fetched and verified ${target.targetTriple} sidecar.\n`);
  } finally {
    await rm(temporaryRoot, { recursive: true, force: true });
  }
}
