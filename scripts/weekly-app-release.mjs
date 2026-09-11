#!/usr/bin/env node
import { execFileSync } from 'node:child_process';
import { appendFileSync, existsSync, readFileSync, readdirSync, unlinkSync, writeFileSync } from 'node:fs';
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
  return execFileSync('git', args, { cwd: root, encoding: 'utf8' }).trim();
}
function fragmentsAt(root, ref) {
  return git(root, 'ls-tree', '-r', '--name-only', ref, '--', 'release-notes.d').split('\n')
    .filter(p => p.endsWith('.md') && !/\/readme\.md$/i.test(p))
    .map(p => parseFragment(git(root, 'show', `${ref}:${p}`) + '\n', p))
    .filter(f => f.target === 'app');
}
function noteCommit(root, path) {
  const commit = git(root, 'log', '--diff-filter=A', '--format=%H', 'HEAD', '--', path).split('\n')[0];
  if (!commit) throw new Error(`Cannot find release baseline for ${path}`);
  return commit;
}
export function planRelease({ root, tags, manualVersion = '', preOneBreaking = 'minor' }) {
  const published = [...new Set(tags.filter(t => SEMVER.test(t)))].sort(compareVersions);
  if (!published.length) throw new Error('No published app version found; bootstrap manually');
  const previous = published.at(-1);
  const head = git(root, 'rev-parse', 'HEAD');
  const notesPath = version => `docs/releases/app-v${version}.md`;
  const recordPath = version => `docs/releases/app-v${version}.json`;
  const ensureNotes = (version, ref) => {
    if (git(root, 'show', `${ref}:${notesPath(version)}`).split('\n')[0] !== `# omnideck app ${version}`)
      throw new Error(`Invalid release notes for ${version}`);
    if (fragmentsAt(root, ref).length) throw new Error(`Unconsumed app fragments at ${ref}`);
  };
  if (manualVersion) {
    if (compareVersions(manualVersion, previous) < 0) throw new Error('Refusing a release below the latest published version');
    ensureNotes(manualVersion, head);
    return { version: manualVersion, previous, source_sha: head, notes_sha: head, prepare: false };
  }
  const pending = readdirSync(resolve(root, 'docs/releases'))
    .map(p => p.match(/^app-v(\d+\.\d+\.\d+)\.md$/)?.[1])
    .filter(v => v && compareVersions(v, previous) > 0).sort(compareVersions);
  if (pending.length > 1) throw new Error('Multiple unpublished release notes; resolve them before autoshipping');
  if (pending.length) {
    const version = pending[0];
    const notesSha = noteCommit(root, notesPath(version));
    ensureNotes(version, notesSha);
    const recordFile = resolve(root, recordPath(version));
    const record = existsSync(recordFile) ? JSON.parse(git(root, 'show', `${notesSha}:${recordPath(version)}`)) : null;
    const sourceSha = record?.source_sha || notesSha;
    if (record && (record.version !== version || record.previous !== previous || !/^[a-f0-9]{40}$/.test(sourceSha)))
      throw new Error('Pending release record does not match published baseline');
    git(root, 'merge-base', '--is-ancestor', sourceSha, notesSha);
    const changed = git(root, 'diff', '--name-only', sourceSha, notesSha).split('\n').filter(Boolean);
    if (changed.some(p => !p.startsWith('release-notes.d/') && p !== notesPath(version) && p !== recordPath(version)))
      throw new Error('Pending release includes changes beyond notes and fragment consumption');
    return { version, previous, source_sha: sourceSha, notes_sha: notesSha, prepare: false };
  }
  const baseline = noteCommit(root, notesPath(previous));
  git(root, 'merge-base', '--is-ancestor', baseline, head);
  const fragments = fragmentsAt(root, head);
  const commits = git(root, 'rev-list', `${baseline}..${head}`).split('\n').filter(Boolean);
  const messages = commits.filter(sha => {
    const paths = git(root, 'diff', '--name-only', `${sha}^`, sha).split('\n');
    return paths.some(p => p && isAppPath(p)) || paths.some(p => fragments.some(f => f.source === p));
  }).map(sha => git(root, 'show', '-s', '--format=%B', sha));
  const changedPaths = git(root, 'diff', '--name-only', baseline, head).split('\n').filter(Boolean);
  if (!fragments.length && !changedPaths.some(isAppPath)) return { skip: true, previous, reason: 'No unreleased app changes' };
  const bump = requiredBump(fragments, messages);
  const version = nextVersion(previous, bump, preOneBreaking);
  const notes = renderReleaseNotes(fragments.length ? fragments : [{
    type: 'changed', area: 'maintenance', body: 'Internal application maintenance and dependency updates.',
  }], version, 'app');
  return { version, previous, source_sha: head, prepare: true, bump, fragments: fragments.map(f => f.source), notes };
}
export function prepareRelease(root, plan) {
  if (!plan.prepare || git(root, 'rev-parse', 'HEAD') !== plan.source_sha) throw new Error('Release source changed since planning');
  if (git(root, 'status', '--porcelain')) throw new Error('Release checkout must be clean');
  const notesPath = `docs/releases/app-v${plan.version}.md`;
  const recordPath = `docs/releases/app-v${plan.version}.json`;
  if (existsSync(resolve(root, notesPath)) || existsSync(resolve(root, recordPath))) throw new Error('Release files already exist');
  const current = fragmentsAt(root, 'HEAD').map(f => f.source);
  if (JSON.stringify(current) !== JSON.stringify(plan.fragments)) throw new Error('App fragments changed since planning');
  writeFileSync(resolve(root, notesPath), plan.notes);
  writeFileSync(resolve(root, recordPath), JSON.stringify({ version: plan.version, previous: plan.previous, source_sha: plan.source_sha, bump: plan.bump }, null, 2) + '\n');
  for (const path of plan.fragments) unlinkSync(resolve(root, path));
  git(root, 'add', '--', notesPath, recordPath, ...plan.fragments);
}
export function verifyCi(runs, sha) {
  const matching = runs.filter(r => r.head_sha === sha && r.head_branch === 'main' && r.event === 'push')
    .sort((a, b) => b.id - a.id);
  if (!matching.length || matching[0].status !== 'completed' || matching[0].conclusion !== 'success')
    throw new Error(`Latest main CI for ${sha} has not succeeded; rerun after CI passes`);
}
function main() {
  const [command, planFile, extra] = process.argv.slice(2);
  const root = process.cwd();
  if (command === 'plan') {
    const pages = JSON.parse(readFileSync(extra, 'utf8'));
    const tags = pages.flat().flatMap(p => p.metadata.container.tags);
    const plan = planRelease({ root, tags, manualVersion: process.env.VERSION || '', preOneBreaking: process.env.PRE_ONE_BREAKING || 'minor' });
    writeFileSync(planFile, JSON.stringify(plan, null, 2) + '\n');
    if (process.env.GITHUB_OUTPUT) appendFileSync(process.env.GITHUB_OUTPUT,
      `skip=${Boolean(plan.skip)}\nversion=${plan.version || ''}\nsource_sha=${plan.source_sha || ''}\nprepare=${Boolean(plan.prepare)}\n`);
    const summary = plan.skip ? plan.reason : `App ${plan.previous} → ${plan.version}\n\nSource: ${plan.source_sha}\n\n${plan.notes || 'Resume/promote existing release notes.'}`;
    console.log(summary);
    if (process.env.GITHUB_STEP_SUMMARY) appendFileSync(process.env.GITHUB_STEP_SUMMARY, summary + '\n');
  } else if (command === 'prepare') prepareRelease(root, JSON.parse(readFileSync(planFile, 'utf8')));
  else if (command === 'verify-ci') {
    const plan = JSON.parse(readFileSync(planFile, 'utf8'));
    verifyCi(JSON.parse(readFileSync(extra, 'utf8')).workflow_runs, plan.source_sha);
  } else throw new Error('Usage: weekly-app-release.mjs plan PLAN TAGS | prepare PLAN | verify-ci PLAN RUNS');
}
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try { main(); } catch (error) { console.error(error.message); process.exitCode = 1; }
}
