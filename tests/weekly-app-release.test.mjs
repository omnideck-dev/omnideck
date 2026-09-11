import assert from 'node:assert/strict';
import test from 'node:test';
import { execFileSync } from 'node:child_process';
import { mkdtempSync, mkdirSync, writeFileSync, existsSync, rmSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';
import { compareVersions, nextVersion, requiredBump, planRelease, prepareRelease, verifyCi } from '../scripts/weekly-app-release.mjs';

function fixture(t) {
  const root = mkdtempSync(join(fileURLToPath(new URL('../', import.meta.url)), '.weekly-release-test-'));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const git = (...args) => execFileSync('git', args, { cwd: root, encoding: 'utf8' }).trim();
  const write = (path, text) => { mkdirSync(join(root, path, '..'), { recursive: true }); writeFileSync(join(root, path), text); };
  const commit = message => { git('add', '.'); git('commit', '-qm', message); return git('rev-parse', 'HEAD'); };
  git('init', '-q', '-b', 'main'); git('config', 'user.name', 'Test'); git('config', 'user.email', 'test@example.com');
  write('docs/releases/app-v0.3.0.md', '# omnideck app 0.3.0\n');
  write('server/app.py', 'original\n');
  commit('chore(release): prepare app 0.3.0');
  const fragment = (name, target = 'app', type = 'fixed', bump = '') => write(`release-notes.d/${name}.md`, `---\ntarget: ${target}\ntype: ${type}\narea: browser\n${bump ? `bump: ${bump}\n` : ''}---\n\nA reviewed change.\n`);
  const plan = (options = {}) => planRelease({ root, tags: ['0.2.9', 'latest', '0.3.0', 'main-abc1234', '0.4.0-beta.1'], ...options });
  return { root, git, write, commit, fragment, plan };
}

test('numeric semver, features, fixes, and pre-1.0 breaking policy', () => {
  assert.ok(compareVersions('0.10.0', '0.9.9') > 0);
  assert.equal(nextVersion('0.3.9', 'patch'), '0.3.10');
  assert.equal(nextVersion('0.3.9', 'minor'), '0.4.0');
  assert.equal(nextVersion('0.3.9', 'major'), '0.4.0');
  assert.equal(nextVersion('0.3.9', 'major', 'major'), '1.0.0');
  assert.equal(nextVersion('1.3.9', 'major'), '2.0.0');
  assert.throws(() => compareVersions('01.0.0', '1.0.0'));
  assert.equal(requiredBump([{ type: 'fixed' }], []), 'patch');
  assert.equal(requiredBump([{ type: 'added' }], []), 'minor');
  assert.equal(requiredBump([{ type: 'changed', bump: 'major' }], []), 'major');
  assert.equal(requiredBump([], ['feat(api)!: remove endpoint']), 'major');
  assert.equal(requiredBump([], ['fix(api): change\n\nBREAKING CHANGE: changed contract']), 'major');
});

test('empty, desktop-only, and documentation changes skip app publication', t => {
  const f = fixture(t);
  assert.equal(f.plan().skip, true);
  f.fragment('desktop', 'desktop', 'added'); f.write('desktop/app.rs', 'new'); f.write('docs/readme.md', 'new');
  f.commit('feat(desktop)!: change host');
  assert.equal(f.plan().skip, true);
});

test('mixed targets bump only for app changes and consume only app fragments', t => {
  const f = fixture(t);
  f.fragment('desktop', 'desktop', 'added', 'major'); f.write('desktop/app.rs', 'new'); f.commit('feat(desktop)!: change host');
  f.fragment('app'); f.write('server/app.py', 'fixed'); f.commit('fix(browser): correct state');
  const plan = f.plan();
  assert.equal(plan.version, '0.3.1');
  prepareRelease(f.root, plan);
  assert.ok(existsSync(join(f.root, 'release-notes.d/desktop.md')));
  assert.equal(existsSync(join(f.root, 'release-notes.d/app.md')), false);
  f.commit('chore(release): prepare app 0.3.1');
  assert.equal(f.plan().source_sha, plan.source_sha);
  assert.equal(f.plan().prepare, false);
  assert.equal(f.plan({ tags: ['0.3.0', '0.3.1'] }).skip, true);
});

test('unnoted app maintenance ships a patch; feature and breaking titles raise it', t => {
  const f = fixture(t);
  f.write('server/app.py', 'refactor'); f.commit('refactor(runtime): simplify ownership');
  assert.equal(f.plan().version, '0.3.1');
  assert.match(f.plan().notes, /Internal application maintenance/);
  f.fragment('feature'); f.write('server/app.py', 'feature'); f.commit('feat(runtime): new capability');
  assert.equal(f.plan().version, '0.4.0');
  f.write('server/app.py', 'breaking'); f.commit('refactor(runtime)!: change interface');
  assert.equal(f.plan({ preOneBreaking: 'major' }).version, '1.0.0');
});

test('failed publication resumes the pinned source even after more main changes', t => {
  const f = fixture(t);
  f.fragment('first'); f.write('server/app.py', 'fix'); f.commit('fix: first');
  const plan = f.plan(); prepareRelease(f.root, plan); f.commit('chore(release): prepare app 0.3.1');
  f.fragment('later', 'app', 'added'); f.write('server/app.py', 'feature'); f.commit('feat: later');
  const retry = f.plan();
  assert.equal(retry.version, '0.3.1'); assert.equal(retry.source_sha, plan.source_sha);
  const next = f.plan({ tags: ['0.3.0', '0.3.1'] });
  assert.equal(next.version, '0.4.0'); assert.deepEqual(next.fragments, ['release-notes.d/later.md']);
});

test('source changes abort preparation; manual releases require consumed notes', t => {
  const f = fixture(t);
  f.fragment('first'); f.commit('fix: first');
  const plan = f.plan(); f.write('server/app.py', 'changed'); f.commit('fix: later');
  assert.throws(() => prepareRelease(f.root, plan), /source changed/);
  assert.throws(() => f.plan({ manualVersion: '0.2.9' }), /below/);
  assert.throws(() => f.plan({ manualVersion: '0.3.0' }), /Unconsumed/);
});

test('manually prepared notes resume from their own tested commit', t => {
  const f = fixture(t);
  f.write('server/app.py', 'fix'); f.commit('fix: change');
  f.write('docs/releases/app-v0.3.1.md', '# omnideck app 0.3.1\n');
  const sha = f.commit('chore(release): prepare app 0.3.1');
  assert.equal(f.plan().source_sha, sha);
});

test('CI verification requires latest exact-source main push success', () => {
  const success = { id: 1, head_sha: 'abc', head_branch: 'main', event: 'push', status: 'completed', conclusion: 'success' };
  verifyCi([success], 'abc');
  assert.throws(() => verifyCi([success], 'other'));
  assert.throws(() => verifyCi([{ ...success, event: 'pull_request' }], 'abc'));
  assert.throws(() => verifyCi([success, { ...success, id: 2, conclusion: 'failure' }], 'abc'));
  assert.throws(() => verifyCi([{ ...success, status: 'in_progress', conclusion: null }], 'abc'));
});

test('a lower explicit bump cannot downgrade an added or removed change', () => {
  assert.equal(requiredBump([{ type: 'added', bump: 'patch' }], []), 'minor');
  assert.equal(requiredBump([{ type: 'removed', bump: 'minor' }], []), 'major');
});

test('ambiguous pending releases and dirty preparation fail closed', t => {
  const f = fixture(t);
  f.fragment('fix'); f.commit('fix: change');
  const plan = f.plan(); f.write('untracked.txt', 'work');
  assert.throws(() => prepareRelease(f.root, plan), /clean/);
  f.write('docs/releases/app-v0.3.1.md', '# omnideck app 0.3.1\n');
  f.write('docs/releases/app-v0.4.0.md', '# omnideck app 0.4.0\n'); f.commit('chore: ambiguous notes');
  assert.throws(() => f.plan(), /Multiple unpublished/);
});

test('a pending source record cannot hide untested code in a notes commit', t => {
  const f = fixture(t);
  f.fragment('fix'); f.commit('fix: change');
  const plan = f.plan(); prepareRelease(f.root, plan);
  f.write('server/app.py', 'unverified change'); f.commit('chore(release): prepare app 0.3.1');
  assert.throws(() => f.plan(), /beyond notes/);
});

test('breaking commits on a merged branch are included even with a plain merge title', t => {
  const f = fixture(t);
  f.git('checkout', '-qb', 'feature');
  f.write('server/app.py', 'breaking'); f.fragment('breaking'); f.commit('fix(api)!: change contract');
  f.git('checkout', '-q', 'main'); f.git('merge', '--no-ff', '-qm', 'Merge feature branch', 'feature');
  assert.equal(f.plan({ preOneBreaking: 'major' }).version, '1.0.0');
});
