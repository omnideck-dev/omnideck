import { chmod, readdir } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const scriptRoot = path.dirname(fileURLToPath(import.meta.url));
const iconRoot = path.resolve(scriptRoot, '../src-tauri/icons');

if (process.platform !== 'win32') {
  const entries = await readdir(iconRoot, { withFileTypes: true });
  await Promise.all(
    entries
      .filter((entry) => entry.isFile())
      .map((entry) => chmod(path.join(iconRoot, entry.name), 0o644)),
  );
}

process.stdout.write('Prepared desktop icon assets.\n');
