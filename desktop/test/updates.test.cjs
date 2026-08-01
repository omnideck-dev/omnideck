const assert = require('node:assert/strict');
const test = require('node:test');

const {
  compareVersions,
  findUpdate,
  isReleaseVersion,
  parseVersion,
  selectUpdate,
} = require('../src/updates.cjs');

// What the registry actually holds: a handful of versions among a long tail of
// branch builds and moving tags.
const REGISTRY_TAGS = [
  'latest', 'main', 'main-6e0b4db', 'main-cf1b2b9',
  '0.1.0-alpha.4', '0.1.0-alpha.5', '0.1.0', '0.2.0', '0.10.0',
];

test('a version with a suffix is not a release', () => {
  assert.equal(isReleaseVersion('1.2.3'), true);
  assert.equal(isReleaseVersion('1.2.3-alpha.1'), false);
  assert.equal(isReleaseVersion('main-6e0b4db'), false);
  assert.equal(isReleaseVersion('latest'), false);
  assert.equal(isReleaseVersion('v1.2.3'), false);
  assert.equal(isReleaseVersion('1.2'), false);
});

test('versions order by number, not by text', () => {
  // The reason to compare parts as numbers: as text, "10" sorts before "9".
  assert.equal(compareVersions('0.10.0', '0.9.0'), 1);
  assert.equal(compareVersions('1.0.0', '1.0.0'), 0);
  assert.equal(compareVersions('1.0.1', '1.1.0'), -1);
});

test('a preview comes before the release it precedes', () => {
  assert.equal(compareVersions('0.1.0-alpha.5', '0.1.0'), -1);
  assert.equal(compareVersions('0.1.0-alpha.5', '0.1.0-alpha.10'), -1);
  assert.equal(compareVersions('0.1.0-alpha.2', '0.1.0-beta.1'), -1);
});

test('an unrecognised version is not compared, it is refused', () => {
  assert.throws(() => compareVersions('latest', '1.0.0'), /unrecognised/);
  assert.equal(parseVersion('main-6e0b4db'), null);
});

test('the newest release is chosen out of everything the registry holds', () => {
  assert.equal(
    selectUpdate({ tags: REGISTRY_TAGS, installedVersion: '0.1.0' }),
    '0.10.0',
  );
});

test('a preview install follows the release line', () => {
  // Someone on a preview is moved to the first real release, not left behind.
  assert.equal(
    selectUpdate({ tags: ['0.1.0', '0.1.0-alpha.6'], installedVersion: '0.1.0-alpha.5' }),
    '0.1.0',
  );
});

test('nothing is offered when the installed version is the newest', () => {
  assert.equal(selectUpdate({ tags: REGISTRY_TAGS, installedVersion: '0.10.0' }), null);
  assert.equal(selectUpdate({ tags: REGISTRY_TAGS, installedVersion: '1.0.0' }), null);
});

test('a registry with no releases at all offers nothing', () => {
  // The state of things until the first release is tagged.
  assert.equal(
    selectUpdate({
      tags: ['latest', 'main', 'main-6e0b4db', '0.1.0-alpha.5'],
      installedVersion: '0.1.0-alpha.5',
    }),
    null,
  );
});

test('a skipped version stays skipped', () => {
  assert.equal(
    selectUpdate({ tags: ['0.1.0'], installedVersion: '0.0.9', skippedVersion: '0.1.0' }),
    null,
  );
});

test('skipping one version does not skip the next', () => {
  assert.equal(
    selectUpdate({
      tags: ['0.1.0', '0.2.0'],
      installedVersion: '0.0.9',
      skippedVersion: '0.1.0',
    }),
    '0.2.0',
  );
});

test('a stale skip cannot suppress a newer install', () => {
  // Skipped 0.2.0, then installed 0.3.0 by hand: 0.4.0 must still be offered.
  assert.equal(
    selectUpdate({
      tags: ['0.4.0'],
      installedVersion: '0.3.0',
      skippedVersion: '0.2.0',
    }),
    '0.4.0',
  );
});

test('an installation whose version cannot be read is left alone', () => {
  assert.equal(selectUpdate({ tags: ['9.9.9'], installedVersion: 'previously-installed' }), null);
  assert.equal(selectUpdate({ tags: ['9.9.9'], installedVersion: undefined }), null);
});

function registry({ tags, digest = `sha256:${'c'.repeat(64)}`, onRequest = () => {} }) {
  return async (url, options = {}) => {
    onRequest(url, options);
    if (url.includes('/token?')) {
      return { ok: true, status: 200, json: async () => ({ token: 'anonymous' }) };
    }
    if (url.includes('/tags/list')) {
      return { ok: true, status: 200, json: async () => ({ tags }) };
    }
    return {
      ok: true,
      status: 200,
      headers: { get: (name) => (name === 'docker-content-digest' ? digest : null) },
    };
  };
}

test('an available release is reported as an immutable reference', async () => {
  const found = await findUpdate({
    repository: 'omnideck-dev/omnideck',
    installedVersion: '0.1.0-alpha.5',
    fetchImpl: registry({ tags: REGISTRY_TAGS }),
  });

  // The digest, not the tag: a tag can be repointed afterwards, a digest cannot.
  assert.deepEqual(found, {
    version: '0.10.0',
    imageRef: `ghcr.io/omnideck-dev/omnideck@sha256:${'c'.repeat(64)}`,
  });
});

test('nothing to install means nothing is asked of the registry', async () => {
  const asked = [];
  const found = await findUpdate({
    repository: 'omnideck-dev/omnideck',
    installedVersion: '9.9.9',
    fetchImpl: registry({ tags: REGISTRY_TAGS, onRequest: (url) => asked.push(url) }),
  });

  assert.equal(found, null);
  assert.equal(
    asked.some((url) => url.includes('/manifests/')),
    false,
    'the digest lookup should not happen when there is no release to look up',
  );
});

test('a digest the registry will not vouch for is refused', async () => {
  await assert.rejects(
    findUpdate({
      repository: 'omnideck-dev/omnideck',
      installedVersion: '0.1.0',
      fetchImpl: registry({ tags: ['0.2.0'], digest: 'not-a-digest' }),
    }),
    /did not identify/,
  );
});

test('a registry that refuses to answer is an error, not an update', async () => {
  await assert.rejects(
    findUpdate({
      repository: 'omnideck-dev/omnideck',
      installedVersion: '0.1.0',
      fetchImpl: async () => ({ ok: false, status: 503, json: async () => ({}) }),
    }),
    /503/,
  );
});
