import { spawnSync } from 'node:child_process';

const packageScript = process.argv[2];
const maxAttempts = 3;

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

  const delayMs = attempt * 5_000;
  console.warn(`${packageScript} failed; retrying in ${delayMs / 1_000}s.`);
  await new Promise((resolve) => setTimeout(resolve, delayMs));
}
