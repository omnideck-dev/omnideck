import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const scriptRoot = path.dirname(fileURLToPath(import.meta.url));

export const binaryRoot = path.resolve(scriptRoot, '../src-tauri/binaries');
export const manifest = JSON.parse(
  await readFile(path.join(binaryRoot, 'vendor-manifest.json'), 'utf8'),
);

export function sha256(value) {
  return createHash('sha256').update(value).digest('hex');
}

export function sidecarFilename(targetTriple) {
  const extension = targetTriple.includes('windows') ? '.exe' : '';
  return `omnideck-cli-${targetTriple}${extension}`;
}

export function selectSidecarTargets(requestedTargets) {
  if (requestedTargets.length === 0) return manifest.targets;
  const knownTargets = new Map(
    manifest.targets.map((target) => [target.targetTriple, target]),
  );
  return requestedTargets.map((targetTriple) => {
    assert(knownTargets.has(targetTriple), `unsupported CLI target: ${targetTriple}`);
    return knownTargets.get(targetTriple);
  });
}
