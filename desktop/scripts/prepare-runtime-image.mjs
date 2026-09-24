import { readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const scriptDirectory = path.dirname(fileURLToPath(import.meta.url));
const projectDirectory = path.dirname(scriptDirectory);
const repositoryDirectory = path.dirname(projectDirectory);
const imageRef = process.argv[2] || '';

if (!/^ghcr\.io\/[a-z0-9._/-]+@sha256:[a-f0-9]{64}$/.test(imageRef)) {
  throw new Error('Usage: node scripts/prepare-runtime-image.mjs <immutable GHCR image ref>');
}

const [configText, imageVersionText] = await Promise.all([
  readFile(path.join(projectDirectory, 'src-tauri', 'tauri.conf.json'), 'utf8'),
  readFile(path.join(repositoryDirectory, 'desktop', 'container-version.txt'), 'utf8'),
]);
const appVersion = JSON.parse(configText).version;
const imageVersion = imageVersionText.trim();
if (!/^\d+\.\d+\.\d+$/.test(imageVersion)) {
  throw new Error('desktop/container-version.txt must contain a plain X.Y.Z release.');
}

const manifest = {
  schemaVersion: 3,
  appVersion,
  imageVersion,
  imageRef,
};
const destination = path.join(projectDirectory, 'src-tauri', 'resources', 'image-manifest.json');
await writeFile(destination, `${JSON.stringify(manifest, null, 2)}\n`, { mode: 0o644 });
process.stdout.write(`${destination}\n`);
