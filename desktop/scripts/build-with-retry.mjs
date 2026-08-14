import { spawnSync } from 'node:child_process';
import { rmSync } from 'node:fs';
import path from 'node:path';

const packageScript = process.argv[2];
const maxAttempts = 3;
const targetByPackageScript = {
  'build:windows': 'x86_64-pc-windows-msvc',
  'build:windows:arm64': 'aarch64-pc-windows-msvc',
  'build:macos': 'aarch64-apple-darwin',
  'build:macos:x64': 'x86_64-apple-darwin',
  'build:linux': 'x86_64-unknown-linux-gnu',
  'build:linux:arm64': 'aarch64-unknown-linux-gnu',
};

if (!packageScript || !/^build:[a-z0-9:-]+$/.test(packageScript)) {
  console.error('Usage: node scripts/build-with-retry.mjs <build:package-script>');
  process.exit(2);
}

for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
  console.log(`Running ${packageScript} (attempt ${attempt}/${maxAttempts})`);
  const result = spawnSync(`pnpm run ${packageScript}`, {
    shell: true,
    stdio: 'inherit',
    windowsHide: true,
  });

  if (result.status === 0) process.exit(0);

  if (attempt === maxAttempts) {
    if (result.error) console.error(result.error.message);
    process.exit(result.status ?? 1);
  }

  const target = targetByPackageScript[packageScript];
  if (!target) {
    console.error(`No retry cleanup target is configured for ${packageScript}.`);
    process.exit(2);
  }
  const bundleDirectory = path.resolve('src-tauri', 'target', target, 'release', 'bundle');
  rmSync(bundleDirectory, { recursive: true, force: true });
  console.warn(`Removed incomplete bundle output before retrying: ${bundleDirectory}`);

  const delayMs = attempt * 5_000;
  console.warn(`${packageScript} failed; retrying in ${delayMs / 1_000}s.`);
  await new Promise((resolve) => setTimeout(resolve, delayMs));
}
