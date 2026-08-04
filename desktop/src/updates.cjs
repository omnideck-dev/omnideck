// Finding a newer container release in the registry it is published to.
//
// Only plain version tags count — 1.2.3 and nothing else. A tag carrying a
// suffix is a preview, and someone running the released application should
// never be moved onto one. Everything else in the registry (branch tags, moving
// tags like latest) is ignored: those point at whatever was built most
// recently, which is not a release and is not something to follow.
//
// Nothing here downloads an image. Listing tags and asking for one tag's digest
// are two small requests, so this can run on a timer without costing anything.
const RELEASE = /^(\d+)\.(\d+)\.(\d+)$/;
const VERSION = /^(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?$/;
const REGISTRY = 'https://ghcr.io';
const MANIFEST_TYPES = [
  'application/vnd.oci.image.index.v1+json',
  'application/vnd.oci.image.manifest.v1+json',
  'application/vnd.docker.distribution.manifest.list.v2+json',
  'application/vnd.docker.distribution.manifest.v2+json',
].join(',');

function parseVersion(value) {
  const match = VERSION.exec(String(value || '').trim());
  if (!match) return null;
  return {
    major: Number(match[1]),
    minor: Number(match[2]),
    patch: Number(match[3]),
    prerelease: match[4] ? match[4].split('.') : [],
  };
}

function isReleaseVersion(value) {
  return RELEASE.test(String(value || '').trim());
}

// Ordering follows the usual rules: numbers compare as numbers, a version with
// a suffix comes before the same version without one, and a shorter run of
// matching identifiers comes first.
function compareIdentifiers(left, right) {
  const leftNumeric = /^\d+$/.test(left);
  const rightNumeric = /^\d+$/.test(right);
  if (leftNumeric && rightNumeric) return Math.sign(Number(left) - Number(right));
  if (leftNumeric) return -1;
  if (rightNumeric) return 1;
  if (left === right) return 0;
  return left < right ? -1 : 1;
}

function comparePrerelease(left, right) {
  if (left.length === 0 && right.length === 0) return 0;
  if (left.length === 0) return 1;
  if (right.length === 0) return -1;
  for (let index = 0; index < Math.min(left.length, right.length); index += 1) {
    const order = compareIdentifiers(left[index], right[index]);
    if (order !== 0) return order;
  }
  return Math.sign(left.length - right.length);
}

function compareVersions(left, right) {
  const a = typeof left === 'string' ? parseVersion(left) : left;
  const b = typeof right === 'string' ? parseVersion(right) : right;
  if (!a || !b) throw new Error('Cannot compare an unrecognised version.');
  return Math.sign(a.major - b.major)
    || Math.sign(a.minor - b.minor)
    || Math.sign(a.patch - b.patch)
    || comparePrerelease(a.prerelease, b.prerelease);
}

// The newest release worth moving to, or null. Anything not strictly newer than
// what is installed is no update, which is what keeps this from ever walking
// backwards. A skipped version silences itself and everything below it, so
// skipping means "not this one" rather than "never again".
function selectUpdate({ tags = [], installedVersion, skippedVersion = null }) {
  if (!parseVersion(installedVersion)) return null;
  const floor = skippedVersion && parseVersion(skippedVersion)
    && compareVersions(skippedVersion, installedVersion) > 0
    ? skippedVersion
    : installedVersion;

  let best = null;
  for (const tag of tags) {
    if (!isReleaseVersion(tag)) continue;
    if (compareVersions(tag, floor) <= 0) continue;
    if (!best || compareVersions(tag, best) > 0) best = tag;
  }
  return best;
}

async function readJson(response) {
  if (!response.ok) throw new Error(`The registry answered ${response.status}.`);
  return response.json();
}

// Anonymous pull access, which is all a public repository needs. No credentials
// are stored or sent.
async function pullToken(repository, fetchImpl) {
  const url = `${REGISTRY}/token?scope=${
    encodeURIComponent(`repository:${repository}:pull`)}&service=ghcr.io`;
  const { token } = await readJson(await fetchImpl(url));
  if (!token) throw new Error('The registry did not grant read access.');
  return token;
}

async function listTags(repository, token, fetchImpl) {
  const response = await fetchImpl(
    `${REGISTRY}/v2/${repository}/tags/list?n=1000`,
    { headers: { authorization: `Bearer ${token}` } },
  );
  const { tags } = await readJson(response);
  return Array.isArray(tags) ? tags : [];
}

// A HEAD gives the digest in a header without transferring the manifest, let
// alone the image.
async function resolveDigest(repository, tag, token, fetchImpl) {
  const response = await fetchImpl(
    `${REGISTRY}/v2/${repository}/manifests/${tag}`,
    { method: 'HEAD', headers: { authorization: `Bearer ${token}`, accept: MANIFEST_TYPES } },
  );
  if (!response.ok) throw new Error(`The registry answered ${response.status}.`);
  const digest = response.headers.get('docker-content-digest') || '';
  if (!/^sha256:[a-f0-9]{64}$/.test(digest)) {
    throw new Error('The registry did not identify that release.');
  }
  return digest;
}

// Returns the release to move to as { version, imageRef }, or null when the
// installed version is already current. The digest is what gets installed: a
// tag can be repointed, a digest cannot.
async function findUpdate({
  repository,
  installedVersion,
  skippedVersion = null,
  fetchImpl = fetch,
}) {
  const token = await pullToken(repository, fetchImpl);
  const version = selectUpdate({
    tags: await listTags(repository, token, fetchImpl),
    installedVersion,
    skippedVersion,
  });
  if (!version) return null;
  const digest = await resolveDigest(repository, version, token, fetchImpl);
  return { version, imageRef: `ghcr.io/${repository}@${digest}` };
}

module.exports = {
  compareVersions,
  findUpdate,
  isReleaseVersion,
  parseVersion,
  selectUpdate,
};
