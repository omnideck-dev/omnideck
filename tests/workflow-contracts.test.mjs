import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');
const releaseNoteWorkflow = await read('../.github/workflows/release-note-policy.yml');
const desktopWorkflow = await read('../.github/workflows/desktop.yml');
const publishWorkflow = await read('../.github/workflows/publish.yml');
const aptInstaller = await read('../.github/scripts/install-apt-packages.sh');

test('release-note metadata events cancel stale checks for the same pull request', () => {
  assert.match(
    releaseNoteWorkflow,
    /group: release-note-policy-\$\{\{ github\.event\.pull_request\.number \|\| github\.ref \}\}/,
  );
  assert.match(
    releaseNoteWorkflow,
    /cancel-in-progress: \$\{\{ github\.event_name == 'pull_request' \}\}/,
  );
});

test('app notes do not start the native desktop package matrix', () => {
  assert.equal(
    [...desktopWorkflow.matchAll(/- "docs\/releases\/v\*\.md"/g)].length,
    2,
  );
  assert.doesNotMatch(desktopWorkflow, /docs\/releases\/\*\*/);
});

test('browser jobs reuse hosted Chrome instead of downloading Playwright browsers', () => {
  assert.doesNotMatch(publishWorkflow, /playwright install/);
  assert.equal(
    [...publishWorkflow.matchAll(/runs-on: ubuntu-24\.04/g)].length >= 2,
    true,
  );
  assert.match(publishWorkflow, /google-chrome --version/);
  assert.match(
    publishWorkflow,
    /just e2e tests\/e2e\/ --browser-channel chrome/,
  );
});

test('Linux package installation is retried and time-bounded', () => {
  assert.equal(
    [...desktopWorkflow.matchAll(/bash \.github\/scripts\/install-apt-packages\.sh/g)]
      .length,
    2,
  );
  assert.doesNotMatch(desktopWorkflow, /sudo apt-get/);
  assert.match(aptInstaller, /readonly max_attempts=3/);
  assert.match(aptInstaller, /readonly command_timeout=180/);
  assert.match(aptInstaller, /Acquire::Retries=3/);
  assert.match(aptInstaller, /Acquire::http::Timeout=30/);
  assert.match(aptInstaller, /Acquire::https::Timeout=30/);
  assert.match(aptInstaller, /DPkg::Lock::Timeout=120/);
});
