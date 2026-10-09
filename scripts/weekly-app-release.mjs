#!/usr/bin/env node
import { execFileSync } from 'node:child_process';
import { appendFileSync, readFileSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseFragment, renderReleaseNotes } from './release-notes.mjs';

const SEMVER = /^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$/;
const levels = ['patch', 'minor', 'major'];
export function compareVersions(a, b) {
  if (!SEMVER.test(a) || !SEMVER.test(b)) throw new Error('Expected plain X.Y.Z versions');
  const left = a.split('.').map(Number), right = b.split('.').map(Number);
  for (let i = 0; i < 3; i++) if (left[i] !== right[i]) return left[i] - right[i];
  return 0;
}
export function nextVersion(current, bump, preOneBreaking = 'minor') {
  if (!SEMVER.test(current) || !levels.includes(bump)) throw new Error('Invalid version or bump');
  if (!['minor', 'major'].includes(preOneBreaking)) throw new Error('Invalid pre-1.0 breaking policy');
  const parts = current.split('.').map(Number);
  if (bump === 'major' && parts[0] === 0 && preOneBreaking === 'minor') bump = 'minor';
  const index = { major: 0, minor: 1, patch: 2 }[bump];
  parts[index]++;
  for (let i = index + 1; i < 3; i++) parts[i] = 0;
  return parts.join('.');
}
export function requiredBump(fragments, messages) {
  const candidates = fragments.flatMap(f => [f.bump || 'patch', { added: 'minor', removed: 'major' }[f.type] || 'patch']);
  for (const message of messages) {
    if (/^[^\n]+!:/m.test(message) || /^BREAKING[ -]CHANGE:\s/m.test(message)) candidates.push('major');
    else if (/^feat(?:\([^\n]+\))?: /m.test(message)) candidates.push('minor');
  }
  return levels[Math.max(0, ...candidates.map(b => levels.indexOf(b)))];
}
export function isAppPath(path) {
  return !/^(desktop\/|docs\/|plans\/|mockups\/|artifacts\/|tests\/|\.github\/|release-notes\.d\/|\.openai\/)/.test(path)
    && !/^(AGENTS\.md|README\.md|CONTRIBUTING\.md|LICENSE|Justfile|\.gitignore)$/.test(path);
}
function git(root, ...args) {
  return execFileSync('git', args, { cwd: root, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] }).trim();
}
// App releases through 0.5.0 used committed notes rather than release tags.
export const LAST_LEGACY_VERSION = '0.5.0';
const SHA = /^[a-f0-9]{40}$/;
export const DIGEST = /^sha256:[a-f0-9]{64}$/;
const RECORD_MARKER = '\n<!-- omnideck-app-release\n';

function fragmentsAt(root, ref) {
  return git(root, 'ls-tree', '-r', '--name-only', ref, '--', 'release-notes.d').split('\n')
    .filter(p => p.endsWith('.md') && !/\/readme\.md$/i.test(p))
    .map(p => parseFragment(git(root, 'show', `${ref}:${p}`) + '\n', p))
    .filter(f => f.target === 'app');
}
export function fragmentsSince(root, baseline, source = 'HEAD') {
  const old = fragmentsAt(root, baseline);
  const current = fragmentsAt(root, source);
  for (const fragment of old) {
    const path = fragment.source;
    // Published fragments are an append-only history. A correction gets a new
    // fragment, rather than silently rewriting an earlier release's input.
    if (!current.some(f => f.source === path)
        || git(root, 'rev-parse', `${baseline}:${path}`) !== git(root, 'rev-parse', `${source}:${path}`))
      throw new Error(`Published app fragment changed: ${path}; add a new fragment instead`);
  }
  return current.filter(f => !old.some(previous => previous.source === f.source));
}

function changesSince(root, baseline, source) {
  git(root, 'merge-base', '--is-ancestor', baseline, source);
  const fragments = fragmentsSince(root, baseline, source);
  const commits = git(root, 'rev-list', `${baseline}..${source}`).split('\n').filter(Boolean);
  const messages = commits.filter(sha => {
    const paths = git(root, 'diff', '--name-only', `${sha}^`, sha).split('\n');
    return paths.some(p => p && isAppPath(p)) || paths.some(p => fragments.some(f => f.source === p));
  }).map(sha => git(root, 'show', '-s', '--format=%B', sha));
  const changedPaths = git(root, 'diff', '--name-only', baseline, source).split('\n').filter(Boolean);
  const bump = requiredBump(fragments, messages);
  return { fragments, bump, changed: fragments.length > 0 || changedPaths.some(isAppPath) };
}
function notesFor(fragments, version) {
  return renderReleaseNotes(fragments.length ? fragments : [{
    type: 'changed', area: 'maintenance', body: 'Internal application maintenance and dependency updates.',
  }], version, 'app');
}
export function releaseBody(plan, digest) {
  if (!DIGEST.test(digest)) throw new Error('Invalid source image digest');
  const record = {
    schema: 1, version: plan.version, previous: plan.previous,
    baseline_sha: plan.baseline_sha, source_sha: plan.source_sha,
    source_digest: digest, bump: plan.bump, fragments: plan.fragments,
  };
  return plan.notes.trimEnd() + '\n' + RECORD_MARKER + JSON.stringify(record, null, 2) + '\n-->\n';
}
export function readRelease(release) {
  const match = release.tag_name?.match(/^app-v(\d+\.\d+\.\d+)$/);
  if (!match) return null; // Desktop releases use their own v* tag namespace.
  const parts = (release.body || '').split(RECORD_MARKER);
  if (parts.length !== 2 || !parts[1].endsWith('\n-->\n'))
    throw new Error(`Missing app release record: ${release.tag_name}`);
  const record = JSON.parse(parts[1].slice(0, -5));
  if (record.schema !== 1 || record.version !== match[1]
      || !SEMVER.test(record.version) || !SEMVER.test(record.previous)
      || compareVersions(record.version, record.previous) <= 0
      || !SHA.test(record.source_sha) || !SHA.test(record.baseline_sha)
      || !DIGEST.test(record.source_digest) || !levels.includes(record.bump)
      || !Array.isArray(record.fragments) || record.fragments.some(p => typeof p !== 'string'))
    throw new Error(`Invalid app release record: ${release.tag_name}`);
  if (release.prerelease) throw new Error('App container releases must not be prereleases');
  return { ...record, notes: parts[0].trimEnd() + '\n', release_id: release.id, draft: release.draft };
}
function verifyRecord(root, record, head) {
  git(root, 'merge-base', '--is-ancestor', record.source_sha, head);
  const changes = changesSince(root, record.baseline_sha, record.source_sha);
  if (!changes.changed || compareVersions(record.version, nextVersion(record.previous, changes.bump)) < 0
      || record.bump !== changes.bump
      || JSON.stringify(record.fragments) !== JSON.stringify(changes.fragments.map(f => f.source))
      || record.notes !== notesFor(changes.fragments, record.version))
    throw new Error('App release record does not match its committed source');
  const tag = `refs/tags/app-v${record.version}`;
  let target;
  try { target = git(root, 'rev-parse', '--verify', `${tag}^{commit}`); }
  catch { if (!record.draft) throw new Error(`Missing published app tag: ${tag}`); }
  if (target && target !== record.source_sha) throw new Error(`App tag points at the wrong source: ${tag}`);
}

function baselineFor(root, version, records) {
  const record = records.find(r => !r.draft && r.version === version);
  if (record) return record.source_sha;
  if (compareVersions(version, LAST_LEGACY_VERSION) > 0)
    throw new Error('Container version has no app release record; refusing to guess its source');
  const baseline = git(root, 'log', '--diff-filter=A', '--format=%H', 'HEAD', '--', `docs/releases/app-v${version}.md`).split('\n')[0];
  if (!baseline) throw new Error('Cannot find the legacy release baseline');
  return baseline;
}

export function planRelease({ root, tags, releases = [], manualVersion = '', preOneBreaking = 'minor' }) {
  const published = [...new Set(tags.filter(t => SEMVER.test(t)))].sort(compareVersions);
  if (!published.length) throw new Error('No published app version found; bootstrap manually');
  const records = releases.map(readRelease).filter(Boolean);
  if (new Set(records.map(r => r.version)).size !== records.length) throw new Error('Duplicate app release records');
  const drafts = records.filter(r => r.draft);
  if (drafts.length > 1) throw new Error('Multiple pending app releases; resolve them before autoshipping');
  const previous = published.at(-1);
  const head = git(root, 'rev-parse', 'HEAD');
  if (manualVersion && !SEMVER.test(manualVersion)) throw new Error('Expected plain X.Y.Z version');
  if (records.some(r => !r.draft && !published.includes(r.version)))
    throw new Error('Published app release has no corresponding container version');
  if (drafts.length) {
    const pending = drafts[0];
    const baseline = published.filter(v => v !== pending.version).at(-1);
    if (pending.previous !== baseline || compareVersions(pending.version, baseline) <= 0)
      throw new Error('Pending release does not match the published baseline');
    if (manualVersion && manualVersion !== pending.version) throw new Error('Finish the pending release before choosing another version');
    if (pending.baseline_sha !== baselineFor(root, pending.previous, records))
      throw new Error('Pending release source does not match the previous release baseline');
    verifyRecord(root, pending, head);
    return pending; // Includes a checkpoint after an image push but before publication.
  }
  const latest = records.find(r => !r.draft && r.version === previous);
  if (latest) {
    verifyRecord(root, latest, head);
    if (manualVersion === previous) return latest; // Safe, digest-checked retry.
  }
  const baseline = baselineFor(root, previous, records);
  const changes = changesSince(root, baseline, head);
  if (!changes.changed) {
    if (manualVersion) throw new Error('No unreleased app changes for the requested version');
    return { skip: true, previous, reason: 'No unreleased app changes' };
  }
  const minimum = nextVersion(previous, changes.bump, preOneBreaking);
  const version = manualVersion || minimum;
  if (compareVersions(version, minimum) < 0) throw new Error(`Version must be at least ${minimum}`);
  return {
    version, previous, source_sha: head, baseline_sha: baseline,
    bump: changes.bump, fragments: changes.fragments.map(f => f.source),
    notes: notesFor(changes.fragments, version),
  };
}
export function verifyCi(runs, sha) {
  const matching = runs.filter(r => r.head_sha === sha && r.head_branch === 'main' && r.event === 'push')
    .sort((a, b) => b.id - a.id);
  if (!matching.length || matching[0].status !== 'completed' || matching[0].conclusion !== 'success')
    throw new Error(`Latest main CI for ${sha} has not succeeded; rerun after CI passes`);
}
function main() {
  const [command, planFile, extra, releasesFile] = process.argv.slice(2);
  const root = process.cwd();
  if (command === 'plan') {
    const pages = JSON.parse(readFileSync(extra, 'utf8'));
    const tags = pages.flat().flatMap(p => p.metadata.container.tags);
    const releases = JSON.parse(readFileSync(releasesFile, 'utf8')).flat();
    const plan = planRelease({ root, tags, releases, manualVersion: process.env.VERSION || '', preOneBreaking: process.env.PRE_ONE_BREAKING || 'minor' });
    writeFileSync(planFile, JSON.stringify(plan, null, 2) + '\n');
    if (process.env.GITHUB_OUTPUT) appendFileSync(process.env.GITHUB_OUTPUT,
      `skip=${Boolean(plan.skip)}\nversion=${plan.version || ''}\nsource_sha=${plan.source_sha || ''}\n`);
    const summary = plan.skip ? plan.reason : `App ${plan.previous} → ${plan.version}\n\nSource: ${plan.source_sha}\n\n${plan.notes}`;
    console.log(summary);
    if (process.env.GITHUB_STEP_SUMMARY) appendFileSync(process.env.GITHUB_STEP_SUMMARY, summary + '\n');
  } else if (command === 'verify-ci') {
    const plan = JSON.parse(readFileSync(planFile, 'utf8'));
    verifyCi(JSON.parse(readFileSync(extra, 'utf8')).workflow_runs, plan.source_sha);
  } else throw new Error('Usage: weekly-app-release.mjs plan PLAN TAGS RELEASES | verify-ci PLAN RUNS');
}
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try { main(); } catch (error) { console.error(error.message); process.exitCode = 1; }
}
