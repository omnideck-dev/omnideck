#!/usr/bin/env node
import { execFileSync } from 'node:child_process';
import { appendFileSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { DIGEST, readRelease, releaseBody } from '../../scripts/weekly-app-release.mjs';

// The draft is the durable checkpoint. Every side effect after its creation is
// safe to retry, including a successful registry push followed by an API failure.
export function publishRelease({ plan, digest, adapter, dryRun = false }) {
  const tag = `app-v${plan.version}`;
  const body = releaseBody(plan, digest);
  readRelease({ tag_name: tag, body, draft: true }); // Validate before any writes.
  if (plan.source_digest && plan.source_digest !== digest)
    throw new Error('Tested image digest changed since the release was reserved');
  let release = adapter.findRelease(tag);
  if (release && (release.body !== body || release.prerelease || release.tag_name !== tag
      || (release.draft && release.target_commitish !== plan.source_sha)))
    throw new Error('Existing release differs from the planned source, notes, or digest');
  if (plan.release_id && release?.id !== plan.release_id)
    throw new Error('Planned release record disappeared or was replaced');
  const target = adapter.tagTarget(tag);
  if (target && target !== plan.source_sha) throw new Error('Release tag points at a different source');
  if (release && !release.draft && !target) throw new Error('Published release tag is missing');
  const existingDigest = adapter.imageDigest(plan.version);
  if (existingDigest && existingDigest !== digest) throw new Error('Container version already points at a different digest');
  if (!release && existingDigest) throw new Error('Container version exists without its release checkpoint');
  if (release && !release.draft && !existingDigest) throw new Error('Published release image is missing');
  if (dryRun) return { tag, digest, dryRun: true };
  if (!release) {
    release = adapter.createDraft({
      tag_name: tag, target_commitish: plan.source_sha,
      name: `omnideck app ${plan.version}`, body,
      draft: true, prerelease: false, make_latest: 'false',
    });
    if (!release.draft || release.body !== body || release.tag_name !== tag
        || release.target_commitish !== plan.source_sha) throw new Error('Could not verify release checkpoint');
  }
  if (!existingDigest) adapter.promoteImage(plan.version, digest);
  if (adapter.imageDigest(plan.version) !== digest) throw new Error('Published image does not match tested source');
  if (release.draft) release = adapter.publishDraft(release.id);
  if (release.draft || release.body !== body || release.prerelease || release.tag_name !== tag)
    throw new Error('Could not verify published release');
  if (adapter.tagTarget(tag) !== plan.source_sha) throw new Error('Published tag does not match tested source');
  return { tag, digest, url: release.html_url };
}

function run(command, args, options = {}) {
  return execFileSync(command, args, { encoding: 'utf8', stdio: ['pipe', 'pipe', 'pipe'], ...options }).trim();
}
function api(path, { method = 'GET', data, optional = false } = {}) {
  try {
    return JSON.parse(run('gh', ['api', '--method', method, path,
      ...(data ? ['--input', '-'] : [])], data ? { input: JSON.stringify(data) } : {}));
  } catch (error) {
    if (optional && /\(HTTP 404\)/.test(String(error.stderr))) return null;
    throw error;
  }
}
export function githubAdapter(repo) {
  if (!/^[\w.-]+\/[\w.-]+$/.test(repo || '')) throw new Error('Invalid repository');
  const base = `repos/${repo}`;
  const image = `ghcr.io/${repo.toLowerCase()}`;
  return {
    findRelease(tag) {
      // The by-tag endpoint promises published releases only. Listing with a
      // write-capable token also includes the drafts used as checkpoints.
      const releases = JSON.parse(run('gh', ['api', '--paginate', '--slurp', `${base}/releases?per_page=100`])).flat();
      const matches = releases.filter(r => r.tag_name === tag);
      if (matches.length > 1) throw new Error('Duplicate app release records');
      return matches[0] || null;
    },
    tagTarget(tag) {
      let ref = api(`${base}/git/ref/tags/${tag}`, { optional: true });
      if (!ref) return null;
      let object = ref.object;
      for (let depth = 0; object.type === 'tag' && depth < 5; depth++)
        object = api(`${base}/git/tags/${object.sha}`).object;
      if (object.type !== 'commit') throw new Error('Release tag does not resolve to a commit');
      return object.sha;
    },
    createDraft(data) { return api(`${base}/releases`, { method: 'POST', data }); },
    publishDraft(id) {
      return api(`${base}/releases/${id}`, { method: 'PATCH', data: { draft: false, make_latest: 'false' } });
    },
    imageDigest(version) {
      try {
        const digest = run('docker', ['buildx', 'imagetools', 'inspect', `${image}:${version}`, '--format', '{{.Manifest.Digest}}']);
        if (!DIGEST.test(digest)) throw new Error('Invalid registry digest');
        return digest;
      } catch (error) {
        // Only a missing manifest permits a new version. Auth/network failures
        // must not be mistaken for an unused container version.
        if (/not found|manifest unknown/i.test(String(error.stderr))) return null;
        throw error;
      }
    },
    promoteImage(version, digest) {
      run('docker', ['buildx', 'imagetools', 'create', '--tag', `${image}:${version}`, `${image}@${digest}`]);
    },
  };
}
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    const result = publishRelease({
      plan: JSON.parse(readFileSync(process.argv[2], 'utf8')),
      digest: process.env.SOURCE_DIGEST,
      adapter: githubAdapter(process.env.GITHUB_REPOSITORY),
      dryRun: process.env.DRY_RUN === 'true',
    });
    const summary = result.dryRun ? `Dry run verified ${result.tag} at ${result.digest}`
      : `Released ${result.tag} at ${result.digest}\n\n${result.url}`;
    console.log(summary);
    if (process.env.GITHUB_STEP_SUMMARY) appendFileSync(process.env.GITHUB_STEP_SUMMARY, summary + '\n');
  } catch (error) { console.error(error.message); process.exitCode = 1; }
}
